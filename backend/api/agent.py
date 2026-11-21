"""/api/agent: what the signed-in user's mail agent sends, the files it may send, alerts, its settings, and the
"Needs you" count. /api/account (DELETE): delete the account and everything in it."""
import base64
import binascii

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update

from agents.inbox_pipeline import fact_check_claims
from config import settings
from database import connection
from database.models import (
    AgentAlert, ApiToken, AuditLog, Claim, Email, KnownContact, MailAccount, MailTask, OutgoingMail, ShieldApproval,
    SimulatedOutbox, User, UserFile, UserSession, UserSettings, WhatsAppCheck, WhatsAppLink, WhatsAppLinkCode,
)
from services import auth, files, gmail_account, mail_sender, runtime_settings, shield_runtime
from services.auth import CurrentUser
from shield import outgoing
from shield.providers.gmail import can_send

router = APIRouter(prefix="/api/agent", tags=["agent"])
account_router = APIRouter(prefix="/api/account", tags=["account"])


# ---------------------------------------------------------------------------------- settings, counts


class AgentSettingsRequest(BaseModel):
    autonomy: str | None = Field(default=None, pattern="^(auto|drafts|off)$")
    digest_enabled: bool | None = None


@router.get("/settings")
async def get_agent_settings(user: CurrentUser = Depends(auth.current_user)):
    return await runtime_settings.agent_settings(user.id)


@router.put("/settings")
async def put_agent_settings(body: AgentSettingsRequest, user: CurrentUser = Depends(auth.session_user)):
    try:
        return await runtime_settings.set_agent_settings(user.id, user.actor, body.autonomy, body.digest_enabled)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/needs-you")
async def needs_you(user: CurrentUser = Depends(auth.current_user)):
    """Counts for the "Needs you" badge."""
    async with connection.session_factory()() as s:
        approvals = await s.scalar(select(func.count()).select_from(ShieldApproval).where(
            ShieldApproval.user_id == user.id, ShieldApproval.status == "pending")) or 0
        alerts = await s.scalar(select(func.count()).select_from(AgentAlert).where(
            AgentAlert.user_id == user.id, AgentAlert.status == "open")) or 0
        queued = await s.scalar(select(func.count()).select_from(OutgoingMail).where(
            OutgoingMail.user_id == user.id, OutgoingMail.status == "scheduled")) or 0
    return {"approvals": approvals, "alerts": alerts, "outgoing_scheduled": queued, "total": approvals + alerts}


# ----------------------------------------------------------------------------------------- outgoing


@router.get("/outgoing")
async def outgoing_list(user: CurrentUser = Depends(auth.current_user)):
    return {"undo_seconds": settings.MAIL_SEND_DELAY_SECONDS, "items": await mail_sender.list_outgoing(user.id)}


@router.post("/outgoing/{outgoing_id}/cancel")
async def outgoing_cancel(outgoing_id: str, user: CurrentUser = Depends(auth.session_user)):
    try:
        out = await mail_sender.cancel(user.id, outgoing_id)
    except mail_sender.SendError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Too late to undo: {exc}") from None
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown message")
    return out


@router.post("/outgoing/{outgoing_id}/send-now")
async def outgoing_send_now(outgoing_id: str, user: CurrentUser = Depends(auth.session_user)):
    try:
        out = await mail_sender.send_now(user.id, outgoing_id)
    except mail_sender.SendError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown message")
    return out


# ------------------------------------------------------------------------------------------ compose


class ComposeRequest(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=500)
    body: str = Field(default="", max_length=20000)
    file_ids: list[str] = Field(default_factory=list, max_length=5)
    confirm: bool = False  # send even though the check found something


async def _compose_check(user: CurrentUser, body: ComposeRequest) -> dict:
    recipients = outgoing.addresses(body.to)
    if not recipients:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Enter a valid email address.")
    findings = [f.to_dict() for f in outgoing.check(f"{body.subject}\n{body.body}", recipients,
                                                    await mail_sender.known_contacts(user.id))]
    for fid in body.file_ids:
        if await files.get(user.id, fid) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "An attached file is not in My files.")
    claims = []
    text = body.body.strip()
    if settings.INBOX_USE_LLM and len(text) >= 40:
        # Fact-check claims you are about to send, like any forward you receive (your history only).
        try:
            items, _, _ = await fact_check_claims([text[:600]], [], "auto", user_id=user.id)
            claims = [i.model_dump() for i in items if i.verdict in ("FALSE", "MISLEADING")]
        except Exception:  # noqa: BLE001 - the security checks stand without the fact-check
            claims = []
    for c in claims:
        findings.append({"kind": "false_claim", "message": f"This looks {c['verdict'].lower()}: {c['claim'][:160]}"})
    return {"recipients": recipients, "findings": findings, "ok": not findings}


@router.post("/compose/check")
async def compose_check(body: ComposeRequest, user: CurrentUser = Depends(auth.current_user)):
    """Check a message before sending: identity and bank numbers, secrets, lookalike recipients, false claims."""
    return await _compose_check(user, body)


@router.post("/compose/send")
async def compose_send(body: ComposeRequest, user: CurrentUser = Depends(auth.session_user)):
    """Send a message you wrote, from your Gmail, after the same check. Queued with the undo window."""
    if not can_send(await gmail_account.scope(user.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Connect Gmail with permission to send first (Settings).")
    check = await _compose_check(user, body)
    if check["findings"] and not body.confirm:
        raise HTTPException(status.HTTP_409_CONFLICT, {"message": "The check found something. Review it, then "
                                                                  "confirm to send anyway.", **check})
    out = await mail_sender.enqueue(user.id, to=", ".join(check["recipients"]), subject=body.subject, body=body.body,
                                    file_ids=body.file_ids, origin="user")
    return {"outgoing": out.to_dict(), "check": check}


# --------------------------------------------------------------------------------------------- files


class FileUpload(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(default="application/octet-stream", max_length=100)
    data_base64: str = Field(max_length=(10 * 1024 * 1024 // 3 + 1) * 4 + 8)
    shareable: bool = False
    description: str | None = Field(default=None, max_length=300)


class FileUpdate(BaseModel):
    shareable: bool | None = None
    description: str | None = Field(default=None, max_length=300)


@router.get("/files")
async def list_files(user: CurrentUser = Depends(auth.current_user)):
    return {"max_bytes": settings.MAX_FILE_BYTES, "items": await files.list_files(user.id)}


@router.post("/files", status_code=status.HTTP_201_CREATED)
async def upload_file(body: FileUpload, user: CurrentUser = Depends(auth.session_user)):
    try:
        data = base64.b64decode(body.data_base64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file data is not valid base64.") from None
    try:
        row = await files.add(user.id, body.filename, body.content_type, data, body.shareable, body.description)
    except files.FileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    await shield_runtime.audit().append(user.actor, "file_added", {"file_id": row.id, "shareable": row.shareable},
                                        user_id=user.id)
    return row.to_dict()


@router.patch("/files/{file_id}")
async def update_file(file_id: str, body: FileUpdate, user: CurrentUser = Depends(auth.session_user)):
    out = await files.update(user.id, file_id, body.shareable, body.description)
    if out is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown file")
    await shield_runtime.audit().append(user.actor, "file_updated", {"file_id": file_id, "shareable": out["shareable"]},
                                        user_id=user.id)
    return out


@router.delete("/files/{file_id}")
async def delete_file(file_id: str, user: CurrentUser = Depends(auth.session_user)):
    if not await files.remove(user.id, file_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown file")
    return {"deleted": True}


# -------------------------------------------------------------------------------------------- alerts


@router.get("/alerts")
async def list_alerts(user: CurrentUser = Depends(auth.current_user)):
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(AgentAlert).where(AgentAlert.user_id == user.id, AgentAlert.status == "open")
                                .order_by(AgentAlert.created_at.desc()).limit(100))).all()
        return {"items": [r.to_dict() for r in rows]}


@router.post("/alerts/{alert_id}/dismiss")
async def dismiss_alert(alert_id: str, user: CurrentUser = Depends(auth.session_user)):
    async with connection.session_factory()() as s:
        res = await s.execute(update(AgentAlert).where(AgentAlert.id == alert_id, AgentAlert.user_id == user.id)
                              .values(status="dismissed"))
        await s.commit()
    if res.rowcount != 1:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown alert")
    return {"dismissed": True}


# ------------------------------------------------------------------------------------ delete account


OWNED = (Claim, Email, ShieldApproval, SimulatedOutbox, WhatsAppCheck, MailTask, MailAccount, OutgoingMail, KnownContact,
         AgentAlert, UserFile, UserSettings, ApiToken, WhatsAppLink, WhatsAppLinkCode, UserSession)


@account_router.delete("")
async def delete_account(user: CurrentUser = Depends(auth.session_user)):
    """Disconnect Gmail (revoked at Google), then delete everything this user owns and the account itself.
    Audit records are kept for the hash chain but detached from the person (user_id cleared)."""
    try:
        await gmail_account.disconnect(user.id)
    except Exception:  # noqa: BLE001 - deletion goes ahead even if Google is unreachable
        pass
    async with connection.session_factory()() as s:
        for model in OWNED:
            await s.execute(delete(model).where(model.user_id == user.id))
        await s.execute(update(AuditLog).where(AuditLog.user_id == user.id).values(user_id=None))
        await s.execute(delete(User).where(User.id == user.id))
        await s.commit()
    from fastapi.responses import JSONResponse

    resp = JSONResponse({"deleted": True})
    auth.clear_session_cookies(resp)
    return resp
