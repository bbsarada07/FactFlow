"""/api/audit: the tamper-evident audit log (operator token required)."""
from fastapi import APIRouter, Depends, Query

from services import shield_runtime
from services.operator_auth import require_operator

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("")
async def audit_log(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200), email_id: str | None = None,
                    _actor: str = Depends(require_operator)):
    """Audit records in order. Payloads are PII-redacted."""
    records, total = await shield_runtime.audit().page(offset, limit, email_id)
    return {"total": total, "items": [r.model_dump() for r in records]}


@router.get("/verify")
async def verify_chain(_actor: str = Depends(require_operator)):
    """Recompute the whole hash chain. ok=false names the first record that was changed or removed."""
    log = shield_runtime.audit()
    result = await log.verify()
    return {"ok": result.ok, "checked": result.checked, "first_broken_seq": result.first_broken_seq,
            "reason": result.reason, "head_hash": await log.head_hash()}
