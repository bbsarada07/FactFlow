"""Sandbox API routes (Phase 4A): simulated email assistant with shield=on / shield=off.

Protected by OPERATOR_TOKEN and rate limited.
"""
import base64
import binascii
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from api.verify import RateLimiter
from config import settings
from database import connection
from database.models import Email
from services.operator_auth import require_operator
from shield import sandbox_agent
from shield.email_parser import MAX_BYTES
from shield.sandbox_agent import VulnerableDemoDisabledError

router = APIRouter(prefix="/api/sandbox", tags=["sandbox"])
sandbox_limiter = RateLimiter(30, noun="Sandbox runs")
outbox_limiter = RateLimiter(60, noun="outbox requests")


class SandboxRunRequest(BaseModel):
    raw: str | None = Field(default=None, max_length=MAX_BYTES + 1)
    eml_base64: str | None = Field(default=None, max_length=(MAX_BYTES // 3 + 1) * 4 + 4)
    email_id: str | None = Field(default=None, max_length=32)
    shield: bool | Literal["on", "off"] = True
    mode: Literal["full", "rules"] = "full"


@router.post("/run")
async def run_sandbox(
    request: Request,
    body: SandboxRunRequest,
    _actor: str = Depends(require_operator),
):
    """Run simulated email assistant on an email with shield=on (protected) or shield=off (vulnerable baseline).

    Vulnerable baseline requires env ALLOW_VULNERABLE_DEMO=true.
    Both modes write only to simulated_outbox.
    """
    sandbox_limiter.check(request.client.host if request.client else "unknown")

    # Resolve email bytes
    email_bytes: bytes | None = None
    email_id = body.email_id

    if body.eml_base64:
        try:
            email_bytes = base64.b64decode(body.eml_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "eml_base64 is not valid base64") from None
    elif body.raw and body.raw.strip():
        email_bytes = body.raw.encode("utf-8")
    else:
        # FactFlow does not store raw messages, so an email_id alone cannot be re-run (it would check the subject only).
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT,
                            "Provide raw or eml_base64 (raw messages are not stored, so email_id alone cannot be run)")

    if email_id:
        async with connection.session_factory()() as s:
            if await s.get(Email, email_id) is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Email {email_id} not found")

    if len(email_bytes) > MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Email is larger than 5 MB")

    # Normalize shield parameter
    shield_on = body.shield in (True, "on", "ON", "true", "True")

    if not shield_on:
        try:
            res = await sandbox_agent.run_vulnerable_assistant(email_bytes, email_id=email_id)
        except VulnerableDemoDisabledError as exc:
            raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
        return res.model_dump()

    use_llm = body.mode == "full" and settings.INBOX_USE_LLM
    res = await sandbox_agent.run_protected_assistant(email_bytes, use_llm=use_llm, email_id=email_id)
    return res.model_dump()


@router.get("/outbox")
async def get_outbox(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _actor: str = Depends(require_operator),
):
    """List simulated outbox entries."""
    outbox_limiter.check(request.client.host if request.client else "unknown")
    items = await sandbox_agent.list_simulated_outbox(limit=limit, offset=offset)
    return {"simulated": True, "count": len(items), "items": items}


@router.delete("/outbox")
@router.post("/outbox/clear")
async def clear_outbox(request: Request, _actor: str = Depends(require_operator)):
    """Clear all simulated outbox entries."""
    outbox_limiter.check(request.client.host if request.client else "unknown")
    cleared = await sandbox_agent.clear_simulated_outbox()
    return {"simulated": True, "cleared": cleared}
