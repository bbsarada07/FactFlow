"""/api/account: the signed-in user's connections: browser extension tokens and the linked WhatsApp number."""
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select

from database import connection
from database.models import WhatsAppLink, WhatsAppLinkCode, utcnow
from services import auth, shield_runtime
from services.auth import CurrentUser

router = APIRouter(prefix="/api/account", tags=["account"])
LINK_CODE_MINUTES = 10


class ExtensionTokenRequest(BaseModel):
    label: str = Field(default="Browser extension", max_length=100)


@router.get("/extension-tokens")
async def extension_tokens(user: CurrentUser = Depends(auth.session_user)):
    return {"items": await auth.list_extension_tokens(user.id)}


@router.post("/extension-tokens", status_code=status.HTTP_201_CREATED)
async def new_extension_token(body: ExtensionTokenRequest | None = None, user: CurrentUser = Depends(auth.session_user)):
    """A personal token for the FactFlow browser extension. The value is shown once; the website hands it to the
    extension directly (no copy and paste)."""
    row, token = await auth.create_extension_token(user.id, (body or ExtensionTokenRequest()).label)
    await shield_runtime.audit().append(user.actor, "extension_connected", {"token_id": row.id}, user_id=user.id)
    return {**row.to_dict(), "token": token}


@router.delete("/extension-tokens/{token_id}")
async def revoke_extension_token(token_id: str, user: CurrentUser = Depends(auth.session_user)):
    if not await auth.revoke_extension_token(user.id, token_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown token")
    await shield_runtime.audit().append(user.actor, "extension_disconnected", {"token_id": token_id}, user_id=user.id)
    return {"revoked": True}


# ------------------------------------------------------------------------------------------- WhatsApp


@router.get("/whatsapp")
async def whatsapp_link(user: CurrentUser = Depends(auth.current_user)):
    async with connection.session_factory()() as s:
        linked = await s.scalar(select(func.count()).select_from(WhatsAppLink).where(WhatsAppLink.user_id == user.id))
    return {"linked_numbers": linked or 0}


@router.post("/whatsapp/link-code")
async def whatsapp_link_code(user: CurrentUser = Depends(auth.session_user)):
    """A 6-digit code, valid for 10 minutes. Send "LINK <code>" to the FactFlow WhatsApp number to link it."""
    async with connection.session_factory()() as s:
        await s.execute(delete(WhatsAppLinkCode).where(
            (WhatsAppLinkCode.user_id == user.id) | (WhatsAppLinkCode.expires_at < utcnow())))
        for _ in range(10):
            code = f"{secrets.randbelow(1_000_000):06d}"
            if await s.get(WhatsAppLinkCode, code) is None:
                break
        else:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not create a code; try again")
        s.add(WhatsAppLinkCode(code=code, user_id=user.id, expires_at=utcnow() + timedelta(minutes=LINK_CODE_MINUTES)))
        await s.commit()
    return {"code": code, "message": f"LINK {code}", "expires_in": LINK_CODE_MINUTES * 60}


@router.delete("/whatsapp")
async def whatsapp_unlink(user: CurrentUser = Depends(auth.session_user)):
    async with connection.session_factory()() as s:
        res = await s.execute(delete(WhatsAppLink).where(WhatsAppLink.user_id == user.id))
        await s.commit()
    await shield_runtime.audit().append(user.actor, "whatsapp_unlinked", {"numbers": res.rowcount}, user_id=user.id)
    return {"unlinked": res.rowcount}
