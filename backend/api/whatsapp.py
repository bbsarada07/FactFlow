"""/api/whatsapp: the WhatsApp webhook (Phase 5A). Public, but every request must carry a valid provider
signature, checked in constant time before anything else is read from it.

- Twilio (default): X-Twilio-Signature over PUBLIC_BASE_URL + this path (+ query) and the sorted form params.
- Meta Cloud API (WHATSAPP_PROVIDER=meta): X-Hub-Signature-256 over the raw body with META_APP_SECRET.

Missing settings: the webhook answers 503 and logs which setting names are missing; the app still starts.
There is no signature bypass. The check runs in the background and replies only to the sender.
"""
import json
from urllib.parse import parse_qs

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, status
from fastapi.responses import Response
from loguru import logger

from config import settings
from services import whatsapp_service
from shield.providers.whatsapp import meta_signature_valid, parse_meta, parse_twilio, twilio_signature_valid

router = APIRouter(prefix="/api/whatsapp", tags=["whatsapp"])
MAX_WEBHOOK_BYTES = 64 * 1024  # a text message is at most 4096 characters; media arrive as URLs
EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'
_warned: set[str] = set()


def _refuse_if_unconfigured() -> None:
    missing = whatsapp_service.missing_settings()
    if missing:
        key = ",".join(missing)
        if key not in _warned:  # one clear line per missing set, not one per request
            _warned.add(key)
            logger.warning(f"WhatsApp webhook refused: missing setting(s) {', '.join(missing)} (see docs/WHATSAPP_SETUP.md)")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "WhatsApp checks are not configured on this server")


def _public_url(request: Request) -> str:
    """The URL the provider called, as it sees it (behind a tunnel the local URL differs)."""
    query = request.url.query
    return settings.PUBLIC_BASE_URL.rstrip("/") + request.url.path + (f"?{query}" if query else "")


@router.post("/webhook")
async def webhook(request: Request, background: BackgroundTasks):
    _refuse_if_unconfigured()
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request too large")
    body = await request.body()
    if len(body) > MAX_WEBHOOK_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Request too large")

    if settings.WHATSAPP_PROVIDER == "meta":
        if not meta_signature_valid(settings.META_APP_SECRET, body, request.headers.get("x-hub-signature-256")):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
        try:
            messages = parse_meta(json.loads(body or b"{}"))
        except (ValueError, AttributeError, TypeError):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unreadable webhook body") from None
        for msg in messages:
            background.add_task(whatsapp_service.handle, msg)
        return {"received": len(messages)}

    params = parse_qs(body.decode("utf-8", errors="replace"), keep_blank_values=True)
    if not twilio_signature_valid(settings.TWILIO_AUTH_TOKEN, _public_url(request), params,
                                  request.headers.get("x-twilio-signature")):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid signature")
    msg = parse_twilio(params)
    if msg.sender:
        background.add_task(whatsapp_service.handle, msg)
    return Response(EMPTY_TWIML, media_type="application/xml")
