"""/api/mail: the signed-in user's mail agent and their own Gmail connection.

Every route acts on the signed-in user's inbox only. The OAuth callback is reached by the browser coming back
from Google, so it carries the user's session cookie; the single-use `state` must also have been started by
that same user (plus PKCE and a rate limit).
"""
import base64
import binascii
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from api.verify import RateLimiter
from config import settings
from services import auth, gmail_account, llm_status, mail_agent, mail_sender, runtime_settings
from services.auth import CurrentUser
from shield.email_parser import MAX_BYTES
from shield.providers.base import ProviderAuthError, ProviderTemporaryError, RawMessageRef
from shield.providers.gmail import REQUESTED_SCOPES, ScopeError

router = APIRouter(prefix="/api/mail", tags=["mail"])
callback_limiter = RateLimiter(20, noun="Gmail connection attempts")


class ProviderRequest(BaseModel):
    provider: Literal["auto", "gmail", "eml"]


class SyncRequest(BaseModel):
    mode: Literal["full", "rules"] = "full"


class UploadRequest(BaseModel):
    raw: str | None = Field(default=None, max_length=MAX_BYTES + 1)
    eml_base64: str | None = Field(default=None, max_length=(MAX_BYTES // 3 + 1) * 4 + 4)
    mode: Literal["full", "rules"] = "full"


class StepRequest(BaseModel):
    task: Literal["extract_action_items", "draft_reply", "propose_calendar_event", "propose_forward",
                  "propose_share_data", "propose_open_link", "report_phishing", "quarantine_email"]
    target: str | None = Field(default=None, max_length=500, description="recipient address or URL, typed by the user")


def _use_llm(mode: str) -> bool:
    return mode == "full" and settings.INBOX_USE_LLM


@router.get("/status")
async def mail_status(user: CurrentUser = Depends(auth.current_user)):
    """Which inbox the agent reads for this user, their Gmail connection, and whether the AI part is available."""
    name, _ = await mail_agent.active_provider(user.id)
    remaining = llm_status.breaker.remaining()
    return {
        "active_provider": name, "provider_setting": await runtime_settings.mail_provider(user.id),
        "gmail": await gmail_account.status(user.id),
        "demo_inbox": {"messages": len(await mail_agent.eml_provider(user.id).list_new(None))},
        "poll_seconds": settings.MAIL_POLL_SECONDS, "poll_enabled": settings.MAIL_POLL_ENABLED,
        "llm": {"state": "quota_exhausted" if remaining else ("ok" if settings.INBOX_USE_LLM else "disabled"),
                "retry_after_seconds": remaining or None},
    }


@router.put("/provider")
async def set_provider(body: ProviderRequest, user: CurrentUser = Depends(auth.session_user)):
    """Choose the inbox: 'gmail' (live), 'eml' (demo inbox) or 'auto' (Gmail when connected). Saved per user."""
    try:
        await runtime_settings.set_mail_provider(user.id, body.provider, user.actor)
    except Exception:  # noqa: BLE001
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "The provider choice could not be saved, so it was not changed. Try again.") from None
    return await mail_status(user)


@router.post("/gmail/connect")
async def gmail_connect(user: CurrentUser = Depends(auth.session_user)):
    """Start the Google consent flow for this user's own Gmail (read, send, labels). Send the browser to `auth_url`."""
    try:
        url = gmail_account.start_connect(user.id, login_hint=user.email)
    except gmail_account.GmailSetupError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    return {"auth_url": url, "scope": " ".join(REQUESTED_SCOPES), "expires_in": gmail_account.STATE_TTL_SECONDS}


def _back(result: str, reason: str | None = None) -> RedirectResponse:
    url = f"/settings?gmail={result}" + (f"&reason={reason}" if reason else "")
    return RedirectResponse(url, status_code=status.HTTP_303_SEE_OTHER)


@router.get("/gmail/callback")
async def gmail_callback(request: Request, code: str | None = Query(default=None, max_length=2048),
                         state: str | None = Query(default=None, max_length=256),
                         error: str | None = Query(default=None, max_length=100)):
    """Google redirects here after consent; we redirect back to the settings page."""
    callback_limiter.check(request.client.host if request.client else "unknown")
    user = await auth.optional_user(request)
    if user is None or user.via != "session":
        return RedirectResponse("/login?next=/settings", status_code=status.HTTP_303_SEE_OTHER)
    if error or not code or not state:
        return _back("error", "denied" if error else "missing_code")
    try:
        await gmail_account.finish_connect(state, code, user.id)
    except ScopeError:
        return _back("error", "scope_not_allowed")
    except gmail_account.AddressTaken:
        return _back("error", "address_taken")
    except gmail_account.GmailSetupError:
        return _back("error", "not_configured")
    except ProviderTemporaryError:
        return _back("error", "google_unreachable")
    except ProviderAuthError:
        return _back("error", "auth_failed")
    return _back("connected")


@router.post("/gmail/disconnect")
async def gmail_disconnect(user: CurrentUser = Depends(auth.session_user)):
    """Revoke this user's Gmail token at Google and delete it here."""
    return await gmail_account.disconnect(user.id)


@router.post("/sync")
async def sync_now(body: SyncRequest | None = None, user: CurrentUser = Depends(auth.current_user)):
    """Fetch and process new mail from this user's inbox now (the poller also does this for Gmail)."""
    name, provider = await mail_agent.active_provider(user.id)
    if provider is None:
        status_ = await gmail_account.status(user.id)
        raise HTTPException(status.HTTP_409_CONFLICT, "Gmail is not connected" + (
            " (reconnect required)" if status_["reconnect_required"] else ""))
    report = await mail_agent.sync(user.id, provider, use_llm=_use_llm((body or SyncRequest()).mode))
    if name == "gmail" and not report.reconnect_required:
        await mail_agent.scan_sent(user.id, provider)  # learn contacts, warn about leaks in sent mail
    await mail_sender.dispatch_due(user.id)  # anything whose undo window has passed
    return report.model_dump()


@router.post("/upload")
async def upload(body: UploadRequest, user: CurrentUser = Depends(auth.current_user)):
    """Give your mail agent an .eml file or pasted message (your demo inbox); returns its task."""
    if body.eml_base64:
        try:
            data = base64.b64decode(body.eml_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "eml_base64 is not valid base64") from None
    elif body.raw and body.raw.strip():
        data = body.raw.encode("utf-8")
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide raw or eml_base64")
    if len(data) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Email is larger than 5 MB")
    eml = mail_agent.eml_provider(user.id)
    message_id = eml.add(data)
    task_id = await mail_agent.process(user.id, eml, RawMessageRef("eml", message_id), source="upload",
                                       use_llm=_use_llm(body.mode))
    if task_id is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "This message was already given to the agent")
    return await mail_agent.task_view(task_id, user.id)


@router.get("/tasks")
async def tasks(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                state: str | None = Query(default=None, max_length=24), user: CurrentUser = Depends(auth.current_user)):
    return await mail_agent.list_tasks(user.id, limit, offset, state)


@router.get("/tasks/{task_id}")
async def task(task_id: str, user: CurrentUser = Depends(auth.current_user)):
    view = await mail_agent.task_view(task_id, user.id)
    if view is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task")
    return view


@router.post("/tasks/{task_id}/steps")
async def add_step(task_id: str, body: StepRequest, user: CurrentUser = Depends(auth.session_user)):
    """Ask your agent to do something with an analysed message (for example forward it). The step is
    policy-checked like any other; outgoing steps only ever reach the simulated outbox."""
    try:
        return await mail_agent.request_step(user.id, task_id, body.task, body.target, user.email)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown task") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.get("/outbox")
async def simulated_outbox(limit: int = Query(50, ge=1, le=200), user: CurrentUser = Depends(auth.current_user)):
    """Everything your agent 'sent': simulated only. Nothing here left FactFlow."""
    return {"simulated": True, "items": await mail_agent.outbox(user.id, limit)}


@router.delete("/outbox")
@router.post("/outbox/clear")
async def clear_outbox(user: CurrentUser = Depends(auth.session_user)):
    """Clear your simulated outbox."""
    return {"simulated": True, "cleared": await mail_agent.clear_outbox(user.id)}
