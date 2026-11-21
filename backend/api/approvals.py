"""/api/approvals: the signed-in user's human-in-the-loop decisions. Nobody can see or decide another user's."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from services import auth, mail_agent, shield_runtime
from services.auth import CurrentUser
from shield.approvals import ApprovalError, sign

router = APIRouter(prefix="/api/approvals", tags=["approvals"])

ERROR_STATUS = {
    "not_found": status.HTTP_404_NOT_FOUND, "not_pending": status.HTTP_409_CONFLICT, "expired": status.HTTP_410_GONE,
    "bad_token": status.HTTP_403_FORBIDDEN, "mismatch": status.HTTP_403_FORBIDDEN,
    "bad_decision": status.HTTP_422_UNPROCESSABLE_CONTENT, "no_secret": status.HTTP_503_SERVICE_UNAVAILABLE,
}


class DecisionRequest(BaseModel):
    decision: Literal["approve", "deny"]
    token: str = Field(min_length=64, max_length=64)
    edited_text: str | None = Field(default=None, max_length=5000,
                                    description="for a reply: the text as the user edited it before approving")


def _store():
    store = shield_runtime.approvals()
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Approvals are off: APPROVAL_SECRET (at least 32 characters) is not set on the server.")
    return store


@router.get("")
async def list_approvals(status_: Literal["pending", "approved", "denied", "expired"] | None = Query(None, alias="status"),
                         limit: int = Query(100, ge=1, le=200), user: CurrentUser = Depends(auth.current_user)):
    """The user's approvals, newest first. Pending ones carry the single-use token needed to decide them."""
    store = shield_runtime.approvals()
    if store is None:
        return {"enabled": False, "items": []}
    items = []
    for a in await store.list(status_, limit, user_id=user.id):
        row = a.model_dump(mode="json")
        row["token"] = sign(store.secret, a) if a.status == "pending" else None
        items.append(row)
    return {"enabled": True, "items": items}


@router.post("/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionRequest, user: CurrentUser = Depends(auth.session_user)):
    """Approve once or deny. The token binds the decision to one (email, action, target). The mail
    agent's task then resumes: an approved step runs (outgoing steps only reach the simulated
    outbox), a denied or expired one ends."""
    store = _store()
    if await store.owner(approval_id) != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown approval")
    actor = user.email
    edited = body.edited_text if body.decision == "approve" and body.edited_text and body.edited_text.strip() else None
    try:
        approval = await store.decide(approval_id, body.decision, body.token, actor)
    except ApprovalError as exc:
        if exc.code == "expired":
            expired = await store.get(approval_id)
            if expired is not None:
                await mail_agent.on_approval_decided(expired)
        raise HTTPException(ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST), str(exc)) from None
    await mail_agent.on_approval_decided(approval, edited_text=edited)
    task = await mail_agent.task_for_approval(approval, user.id)
    step = next((s for s in (task or {}).get("steps", []) if s.get("approval_id") == approval.id), None)
    return {
        "approval": approval.model_dump(mode="json"),
        "executed": bool(step and step.get("status") == "executed"),
        "step": step,
        "task_state": task["state"] if task else None,
        "note": "An approved reply is queued in your Gmail outbox and can be undone until it is sent "
                "(demo inbox: simulated only).",
    }
