"""/api/policy: the signed-in user's strict / balanced mode and trusted recipient domains.

Each change is written to the audit log first and only then saved. Loosening (strict -> balanced, adding a
domain) also needs confirm=true.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from services import auth, runtime_settings, shield_runtime
from services.auth import CurrentUser

router = APIRouter(prefix="/api/policy", tags=["policy"])


class ModeRequest(BaseModel):
    mode: Literal["strict", "balanced"]
    confirm: bool = False


class DomainsRequest(BaseModel):
    domains: list[str] = Field(max_length=200)
    confirm: bool = False


def _view(cfg) -> dict:
    return {"mode": cfg.mode, "allowed_domains": list(cfg.allowed_domains),
            "approval_ttl_seconds": cfg.approval_ttl_seconds, "approvals_enabled": shield_runtime.approvals_enabled()}


@router.get("")
async def get_policy(user: CurrentUser = Depends(auth.current_user)):
    return _view(await runtime_settings.policy_for(user.id))


async def _change(user: CurrentUser, **kwargs) -> dict:
    try:
        cfg = await runtime_settings.change_policy(user.id, user.actor, **kwargs)
    except PermissionError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    return _view(cfg)


@router.put("/mode")
async def set_mode(body: ModeRequest, user: CurrentUser = Depends(auth.session_user)):
    return await _change(user, mode=body.mode, confirm=body.confirm)


@router.put("/allowed-domains")
async def set_allowed_domains(body: DomainsRequest, user: CurrentUser = Depends(auth.session_user)):
    return await _change(user, domains=body.domains, confirm=body.confirm)
