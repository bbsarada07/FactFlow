"""/api/audit: the tamper-evident audit log.

Each user reads only their own records. The hash chain itself is global (one chain for the whole system, so
removing anyone's record breaks it); verification reports whether the chain is intact without revealing other
users' records. Admins can read every record.
"""
from fastapi import APIRouter, Depends, Query

from services import auth, shield_runtime
from services.auth import CurrentUser

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def audit_log(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), email_id: str | None = None,
                    everyone: bool = False, user: CurrentUser = Depends(auth.current_user)):
    """The user's audit records in order (admins: everyone=true for all). Payloads are PII-redacted."""
    records, total = await shield_runtime.audit().page(offset, limit, email_id, user_id=user.id,
                                                       everyone=everyone and user.is_admin)
    return {"total": total, "items": [r.model_dump() for r in records]}


@router.get("/verify")
async def verify_chain(user: CurrentUser = Depends(auth.current_user)):
    """Recompute the whole hash chain. ok=false says it was changed; the broken record's number is shown only
    if it is the user's own record (or to an admin)."""
    log = shield_runtime.audit()
    result = await log.verify()
    broken = result.first_broken_seq
    if broken is not None and not user.is_admin and await log.owner_of(broken) != user.id:
        broken = None
    _, yours = await log.page(0, 1, user_id=user.id)
    return {"ok": result.ok, "checked": result.checked if user.is_admin else yours, "first_broken_seq": broken,
            "reason": result.reason, "head_hash": await log.head_hash()}
