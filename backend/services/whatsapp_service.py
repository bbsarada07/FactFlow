"""WhatsApp checks (Phase 5B/5C): one inbound message -> the inbox pipeline -> one reply to its sender.

Privacy: the sender's number exists only in memory while the reply is sent. The database and the audit
log get a salted SHA-256 of it (WHATSAPP_HASH_SALT) and the result; log lines use the 12-character hash
prefix. Message text is never stored: the analysis row keeps a verdict with the text stripped out
(InboxOptions.store_message_text=False). PII is redacted before any model call (the quarantined reader
and the claim checks redact; images go only to the configured vision reader, as for screenshots).

Abuse: STOP / START (opt-out table), a per-sender limit (WHATSAPP_MAX_PER_HOUR, sliding hour), maximum
text and media sizes, and retried webhooks are recognised by the provider's message id.
"""
from __future__ import annotations

import base64
import shutil

import httpx
from loguru import logger
from sqlalchemy import delete, func, select

from agents import inbox_pipeline
from agents.inbox_pipeline import InboxOptions
from api.verify import RateLimiter
from config import settings
from database import connection
from database.models import Email, WhatsAppCheck, WhatsAppOptOut
from services import input_service, shield_runtime, view_tokens
from shield import qr
from shield.email_parser import EmailInputError, parse_input
from shield.providers.whatsapp import (
    InboundMessage, MediaError, MetaCloudProvider, TwilioWhatsAppProvider, WhatsAppProvider, WhatsAppSendError,
)
from shield.scan import PIPELINE_VERSION
from shield.whatsapp_reply import actor, build_reply, detect_language, hash_sender, simple_reply, templates

HTTP_TRANSPORT: httpx.AsyncBaseTransport | None = None  # tests plug a fake Twilio in here
MIN_SALT_CHARS = 16
STOP_WORDS = {"STOP", "UNSUBSCRIBE"}
START_WORDS = {"START", "UNSTOP"}
INDIC_OCR = {"hi": "hin", "te": "tel"}

sender_limiter = RateLimiter(settings.WHATSAPP_MAX_PER_HOUR, noun="WhatsApp checks", window=3600)


def missing_settings() -> list[str]:
    """Names (never values) of the settings the webhook needs before it may accept anything."""
    need = {"twilio": ("TWILIO_AUTH_TOKEN", "PUBLIC_BASE_URL"), "meta": ("META_APP_SECRET",)}[settings.WHATSAPP_PROVIDER]
    missing = [name for name in need if not getattr(settings, name)]
    if len(settings.WHATSAPP_HASH_SALT or "") < MIN_SALT_CHARS:
        missing.append("WHATSAPP_HASH_SALT")
    return missing


def reply_provider() -> WhatsAppProvider | None:
    """The provider that may send replies, or None when its credentials are missing (replies become DRY RUN)."""
    if settings.WHATSAPP_PROVIDER == "meta":
        return None  # MetaCloudProvider cannot send yet
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN and settings.TWILIO_WHATSAPP_FROM:
        return TwilioWhatsAppProvider(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN,
                                      settings.TWILIO_WHATSAPP_FROM, transport=HTTP_TRANSPORT)
    return None


def media_provider(provider: str) -> WhatsAppProvider:
    if provider == "twilio":
        return TwilioWhatsAppProvider(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN,
                                      settings.TWILIO_WHATSAPP_FROM, transport=HTTP_TRANSPORT)
    return MetaCloudProvider()


def ocr_languages() -> set[str]:
    """Tesseract language packs on this server (empty when Tesseract is not installed)."""
    if not (settings.TESSERACT_CMD or shutil.which("tesseract")):
        return set()
    try:
        import pytesseract

        if settings.TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD
        return set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001
        return set()


# ------------------------------------------------------------------------------- storage


async def _seen(message_id: str) -> bool:
    async with connection.session_factory()() as s:
        return await s.scalar(select(WhatsAppCheck.id).where(WhatsAppCheck.message_id == message_id)) is not None


async def _opted_out(sender_hash: str) -> bool:
    async with connection.session_factory()() as s:
        return await s.get(WhatsAppOptOut, sender_hash) is not None


async def _first_contact(sender_hash: str) -> bool:
    async with connection.session_factory()() as s:
        n = await s.scalar(select(func.count()).select_from(WhatsAppCheck).where(WhatsAppCheck.sender_hash == sender_hash))
        return not n


async def _set_opt_out(sender_hash: str, out: bool) -> None:
    async with connection.session_factory()() as s:
        if out and await s.get(WhatsAppOptOut, sender_hash) is None:
            s.add(WhatsAppOptOut(sender_hash=sender_hash))
        elif not out:
            await s.execute(delete(WhatsAppOptOut).where(WhatsAppOptOut.sender_hash == sender_hash))
        await s.commit()


async def _record(sender_hash: str, msg: InboundMessage, input_type: str, language: str, delivery: str,
                  reply: str, email_id: str | None = None, label: str | None = None, score: int | None = None,
                  llm_state: str | None = None) -> None:
    async with connection.session_factory()() as s:
        s.add(WhatsAppCheck(sender_hash=sender_hash, message_id=(msg.message_id or None), input_type=input_type,
                            language=language, label=label, score=score, llm_state=llm_state, email_id=email_id,
                            reply_chars=len(reply), delivery=delivery))
        await s.commit()


# ------------------------------------------------------------------------------- replies


async def deliver(msg: InboundMessage, sender_hash: str, reply: str, language: str) -> str:
    """Send `reply` to the sender of `msg` only. Without credentials: a DRY RUN audit entry, never a fake send."""
    who = actor(sender_hash)
    audit = shield_runtime.audit()
    provider = reply_provider() if msg.provider == settings.WHATSAPP_PROVIDER else None
    if provider is None:
        await audit.append(who, "whatsapp_reply", {"delivery": "dry_run", "chars": len(reply), "language": language,
                                                   "reply": reply, "note": "DRY RUN: no provider credentials, nothing was sent"})
        logger.info(f"[{who}] WhatsApp reply not sent (DRY RUN, no provider credentials)")
        return "dry_run"
    try:
        result = await provider.send_text(msg.sender, reply)
    except WhatsAppSendError as exc:
        await audit.append(who, "whatsapp_reply", {"delivery": "failed", "chars": len(reply), "error": str(exc)})
        logger.warning(f"[{who}] WhatsApp reply failed: {exc}")
        return "failed"
    await audit.append(who, "whatsapp_reply", {"delivery": "sent", "chars": len(reply), "language": language,
                                               "provider_message_id": result.provider_message_id})
    return "sent"


def _report_url(email_id: str) -> str | None:
    """Link to the full analysis (the frontend page is built separately). Only a public https origin is linked."""
    base = (settings.FRONTEND_URL or "").rstrip("/")
    if not base.startswith("https://"):
        return None
    return f"{base}/inbox/{email_id}?view_token={view_tokens.view_token(email_id)}"


# ------------------------------------------------------------------------------- media


async def _image_text(msg: InboundMessage, media_url: str, mime: str, caption: str) -> tuple[str, list[str], str]:
    """(text to analyse, notices, language). Raises MediaError when the image cannot be fetched."""
    data = await media_provider(msg.provider).fetch_media(media_url, settings.WHATSAPP_MAX_MEDIA_BYTES)
    text, reader = "", ""
    try:
        read = await input_service.read_image(base64.b64encode(data).decode(), mime)
        text, reader = read.text, read.reader
    except input_service.InputError:
        pass
    codes = qr.decode(data)
    parts = [p for p in (caption, text, *(f"QR code: {c}" for c in codes)) if p]
    combined = "\n".join(parts)
    language = detect_language(combined)
    notices = []
    if reader in ("", "tesseract"):
        installed = ocr_languages()
        missing = [lang for lang, pack in INDIC_OCR.items() if pack not in installed]
        if missing and (language in missing or not text):
            notices.append("ocr_missing")
    return combined, notices, language


# --------------------------------------------------------------------------------- main


async def handle(msg: InboundMessage) -> None:
    """Check one inbound message and reply to its sender. Never raises; never logs the number or text."""
    sender_hash = hash_sender(settings.WHATSAPP_HASH_SALT, msg.sender)
    who = actor(sender_hash)
    try:
        await _handle(msg, sender_hash, who)
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[{who}] WhatsApp check failed: {type(exc).__name__}")


async def _handle(msg: InboundMessage, sender_hash: str, who: str) -> None:
    audit = shield_runtime.audit()
    text = (msg.text or "").strip()
    language = detect_language(text)
    if msg.message_id and await _seen(msg.message_id):
        logger.info(f"[{who}] repeated webhook for a message already handled; ignored")
        return

    word = text.upper()
    if word in STOP_WORDS | START_WORDS and not msg.media:
        out = word in STOP_WORDS
        await _set_opt_out(sender_hash, out)
        await audit.append(who, "whatsapp_opt_out" if out else "whatsapp_opt_in", {})
        reply = simple_reply("stopped" if out else "started", language)
        await _record(sender_hash, msg, "command", language, await deliver(msg, sender_hash, reply, language), reply)
        return
    if await _opted_out(sender_hash):
        await audit.append(who, "whatsapp_ignored", {"reason": "opted out (STOP)"})
        return
    if sender_limiter.blocked(sender_hash):
        await audit.append(who, "whatsapp_rate_limited", {"limit_per_hour": sender_limiter.per_minute})
        logger.info(f"[{who}] WhatsApp sender over the hourly limit; no reply")
        return
    sender_limiter.check(sender_hash)
    consent = await _first_contact(sender_hash)
    media = msg.media[0] if msg.media else None
    await audit.append(who, "whatsapp_received", {"message_id": msg.message_id, "chars": len(text),
                                                  "media": media.content_type if media else None})

    async def fixed(key: str, input_type: str) -> None:
        reply = simple_reply(key, language, consent)
        await _record(sender_hash, msg, input_type, language, await deliver(msg, sender_hash, reply, language), reply)

    if len(text) > settings.WHATSAPP_MAX_TEXT_CHARS:
        return await fixed("too_large", "too_large")
    notices: list[str] = []
    input_type = "text"
    if media is not None:
        if media.content_type.startswith("audio/"):
            return await fixed("voice", "voice")
        if not media.content_type.startswith("image/"):
            return await fixed("unsupported", "unsupported")
        input_type = "image"
        try:
            text, notices, language = await _image_text(msg, media.url, media.content_type, text)
        except MediaError as exc:
            logger.info(f"[{who}] WhatsApp image not fetched: {exc}")
            too_large = "larger" in str(exc)
            return await fixed("too_large" if too_large else "failed", "too_large" if too_large else "image")
        if not text:
            reply = simple_reply("no_text", language, consent)
            if notices:
                reply += "\n" + templates(language)["ocr_missing"]
            await _record(sender_hash, msg, "image", language, await deliver(msg, sender_hash, reply, language), reply)
            return
    elif not text:
        return await fixed("empty", "text")

    data = text.encode("utf-8")
    try:
        pe = parse_input(data, "whatsapp")
    except EmailInputError:
        return await fixed("too_large", "too_large")
    async with connection.session_factory()() as s:
        row = Email(source="whatsapp", sha256=pe.sha256, pipeline_version=PIPELINE_VERSION,
                    mode="full" if settings.INBOX_USE_LLM else "rules", language=language, status="processing")
        s.add(row)
        await s.commit()
        email_id = row.id
    opts = InboxOptions(source="whatsapp", language=language, use_llm=settings.INBOX_USE_LLM,
                        llm_disabled_by_server=not settings.INBOX_USE_LLM, store_message_text=False)
    verdict = await inbox_pipeline.analyze(email_id, data, opts)
    if verdict is None:
        return await fixed("failed", input_type)
    limited = verdict.llm_status.state != "ok"
    reply = build_reply(verdict, language, _report_url(email_id), limited=limited, consent=consent,
                        notices=tuple(notices))
    delivery = await deliver(msg, sender_hash, reply, language)
    await _record(sender_hash, msg, input_type, language, delivery, reply, email_id=email_id,
                  label=verdict.overall.label, score=verdict.overall.score, llm_state=verdict.llm_status.state)
