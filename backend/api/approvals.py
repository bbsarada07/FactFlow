"""/api/approvals: human-in-the-loop decisions (operator token required)."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from services import shield_runtime
from services.operator_auth import require_operator
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


def _store():
    store = shield_runtime.approvals()
    if store is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Approvals are off: APPROVAL_SECRET (at least 32 characters) is not set on the server.")
    return store


@router.get("")
async def list_approvals(status_: Literal["pending", "approved", "denied", "expired"] | None = Query(None, alias="status"),
                         limit: int = Query(100, ge=1, le=200), _actor: str = Depends(require_operator)):
    """Approvals, newest first. Pending ones carry the single-use token needed to decide them."""
    store = shield_runtime.approvals()
    if store is None:
        return {"enabled": False, "items": []}
    items = []
    for a in await store.list(status_, limit):
        row = a.model_dump(mode="json")
        row["token"] = sign(store.secret, a) if a.status == "pending" else None
        items.append(row)
    return {"enabled": True, "items": items}


@router.post("/{approval_id}/decision")
async def decide(approval_id: str, body: DecisionRequest, actor: str = Depends(require_operator)):
    """Approve once or deny. The token binds the decision to one (email, action, target)."""
    store = _store()
    try:
        approval = await store.decide(approval_id, body.decision, body.token, actor)
    except ApprovalError as exc:
        raise HTTPException(ERROR_STATUS.get(exc.code, status.HTTP_400_BAD_REQUEST), str(exc)) from None
    return {
        "approval": approval.model_dump(mode="json"),
        "executed": False,
        "note": "Nothing is sent anywhere. Approved actions will run against the simulated outbox (Phase 4).",
    }
