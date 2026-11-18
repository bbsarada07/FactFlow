"""/api/policy: strict / balanced mode and trusted recipient domains.

Changes need the operator token, are written to the audit log first and only then applied.
Loosening (strict -> balanced, adding a domain) also needs confirm=true.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services import runtime_settings, shield_runtime
from services.operator_auth import require_operator

router = APIRouter(prefix="/api/policy", tags=["policy"])


class ModeRequest(BaseModel):
    mode: Literal["strict", "balanced"]
    confirm: bool = False


class DomainsRequest(BaseModel):
    domains: list[str] = Field(max_length=200)
    confirm: bool = False


def _view() -> dict:
    cfg = shield_runtime.policy_store().get()
    return {"mode": cfg.mode, "allowed_domains": list(cfg.allowed_domains),
            "approval_ttl_seconds": cfg.approval_ttl_seconds, "approvals_enabled": shield_runtime.approvals_enabled()}


@router.get("")
async def get_policy():
    return _view()


async def _change(plan, actor: str) -> dict:
    store = shield_runtime.policy_store()
    async with shield_runtime.policy_lock:
        before = store.get()
        try:
            new, change = plan(store, actor)
        except PermissionError as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        if change is not None:
            await shield_runtime.audit().append(f"human:{actor}", "policy_changed", change)
            if change["field"] == "policy_mode":
                # Saved before it is applied, so a restart never comes back looser than what is running.
                try:
                    await runtime_settings.save(runtime_settings.POLICY_MODE, new.mode, f"human:{actor}")
                except Exception as exc:  # noqa: BLE001
                    await shield_runtime.audit().append(f"human:{actor}", "policy_change_not_saved",
                                                        {**change, "error": type(exc).__name__})
                    raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                                        "The policy mode could not be saved, so it was not changed. Try again.") from None
            store.apply(new, before)
    return _view()


@router.put("/mode")
async def set_mode(body: ModeRequest, actor: str = Depends(require_operator)):
    return await _change(lambda s, a: s.plan_mode(body.mode, confirm=body.confirm, actor=f"human:{a}"), actor)


@router.put("/allowed-domains")
async def set_allowed_domains(body: DomainsRequest, actor: str = Depends(require_operator)):
    return await _change(lambda s, a: s.plan_domains(body.domains, confirm=body.confirm, actor=f"human:{a}"), actor)
