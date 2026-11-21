"""Outgoing mail: a queue with an undo window, and the only place FactFlow sends real email.

Every message (an automatic reply, an approved step, or one the user wrote in FactFlow) is queued with
send_at = now + MAIL_SEND_DELAY_SECONDS. Until then the user can cancel it ("undo") or send it now. The
dispatcher sends due messages through that user's own Gmail (gmail.send) and records the result. Attachments
come only from the same user's My files. Each send adds the recipient to the user's known contacts.
"""
from __future__ import annotations

import asyncio
import email.utils
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from loguru import logger
from sqlalchemy import select

from config import settings
from database import connection
from database.models import AgentAlert, KnownContact, OutgoingMail, User, UserFile, utcnow
from services import gmail_account, shield_runtime
from shield.providers.base import ProviderAuthError, ProviderTemporaryError
from shield.providers.gmail import can_send

AGENT_FOOTER = "\n\n--\nSent by {name}'s FactFlow agent."


class SendError(Exception):
    pass


def _aware(dt: datetime | None) -> datetime | None:
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


async def enqueue(user_id: str, *, to: str, subject: str, body: str, origin: str = "agent", file_ids: list[str] = (),
                  thread_id: str | None = None, in_reply_to: str | None = None, task_id: str | None = None,
                  step_id: str | None = None, delay_seconds: int | None = None) -> OutgoingMail:
    delay = settings.MAIL_SEND_DELAY_SECONDS if delay_seconds is None else delay_seconds
    async with connection.session_factory()() as s:
        if step_id and (existing := await s.scalar(select(OutgoingMail).where(OutgoingMail.step_id == step_id))):
            return existing  # a step sends at most once
        row = OutgoingMail(user_id=user_id, origin=origin, to_addr=to.strip()[:320], subject=subject[:500],
                           body=body[:20000], file_ids=list(file_ids), thread_id=thread_id,
                           in_reply_to=(in_reply_to or None) and in_reply_to[:500], task_id=task_id, step_id=step_id,
                           status="scheduled", send_at=utcnow() + timedelta(seconds=max(0, delay)))
        s.add(row)
        await s.commit()
        await s.refresh(row)
    await shield_runtime.audit().append(f"agent:mail" if origin != "user" else "user", "mail_queued", {
        "outgoing_id": row.id, "to": row.to_addr, "files": len(row.file_ids or []), "origin": origin,
        "send_at": row.send_at.isoformat()}, user_id=user_id)
    return row


async def list_outgoing(user_id: str, limit: int = 50) -> list[dict]:
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(OutgoingMail).where(OutgoingMail.user_id == user_id)
                                .order_by(OutgoingMail.created_at.desc()).limit(limit))).all()
        return [r.to_dict() for r in rows]


async def cancel(user_id: str, outgoing_id: str) -> dict | None:
    """Undo: only while the message is still scheduled."""
    async with connection.session_factory()() as s:
        row = await s.get(OutgoingMail, outgoing_id)
        if row is None or row.user_id != user_id:
            return None
        if row.status != "scheduled":
            raise SendError(f"It is already {row.status}.")
        row.status = "cancelled"
        await s.commit()
        out = row.to_dict()
    await shield_runtime.audit().append("user", "mail_cancelled", {"outgoing_id": outgoing_id}, user_id=user_id)
    return out


async def send_now(user_id: str, outgoing_id: str) -> dict | None:
    async with connection.session_factory()() as s:
        row = await s.get(OutgoingMail, outgoing_id)
        if row is None or row.user_id != user_id:
            return None
        if row.status != "scheduled":
            raise SendError(f"It is already {row.status}.")
        row.send_at = utcnow()
        await s.commit()
    await dispatch_due(user_id)
    async with connection.session_factory()() as s:
        return (await s.get(OutgoingMail, outgoing_id)).to_dict()


async def add_contact(user_id: str, address: str, source: str = "sent") -> None:
    address = (address or "").strip().lower()
    if "@" not in address or len(address) > 320:
        return
    async with connection.session_factory()() as s:
        row = await s.scalar(select(KnownContact).where(KnownContact.user_id == user_id, KnownContact.address == address))
        if row is None:
            s.add(KnownContact(user_id=user_id, address=address, source=source))
        else:
            row.last_seen_at = utcnow()
        await s.commit()


async def known_contacts(user_id: str) -> set[str]:
    async with connection.session_factory()() as s:
        return set((await s.scalars(select(KnownContact.address).where(KnownContact.user_id == user_id))).all())


def _subject(subject: str) -> str:
    subject = (subject or "").strip()
    return subject if subject.lower().startswith("re:") or not subject else subject


async def build_message(row: OutgoingMail, from_addr: str, user_name: str | None) -> bytes:
    msg = EmailMessage()
    msg["From"] = email.utils.formataddr((user_name or "", from_addr))
    msg["To"] = row.to_addr
    msg["Subject"] = _subject(row.subject)
    msg["Date"] = email.utils.formatdate(localtime=False)
    msg["Message-ID"] = email.utils.make_msgid(domain=from_addr.rpartition("@")[2] or "factflow.local")
    if row.in_reply_to:
        msg["In-Reply-To"] = row.in_reply_to
        msg["References"] = row.in_reply_to
    body = row.body
    if row.origin == "agent":
        body += AGENT_FOOTER.format(name=(user_name or from_addr.split("@")[0]).split()[0])
    msg.set_content(body)
    for file_id in row.file_ids or []:
        async with connection.session_factory()() as s:
            f = await s.get(UserFile, file_id)
        if f is None or f.user_id != row.user_id:
            raise SendError("an attached file is no longer in My files")
        maintype, _, subtype = (f.content_type or "application/octet-stream").partition("/")
        msg.add_attachment(f.data, maintype=maintype or "application", subtype=subtype or "octet-stream",
                           filename=f.filename)
    return bytes(msg)


async def _send_one(row: OutgoingMail) -> None:
    async with connection.session_factory()() as s:
        user = await s.get(User, row.user_id)
    provider = await gmail_account.provider(row.user_id)
    scope = await gmail_account.scope(row.user_id)
    if provider is None or not can_send(scope):
        raise SendError("Gmail is not connected with permission to send. Reconnect Gmail in Settings.")
    from_addr = await gmail_account.address(row.user_id) or (user.email if user else "")
    raw = await build_message(row, from_addr, user.name if user else None)
    result = await provider.send(raw, thread_id=row.thread_id)
    row.provider_message_id = str(result.get("id") or "")[:128] or None


async def dispatch_due(user_id: str | None = None) -> int:
    """Send every scheduled message whose undo window has passed (one user's, or everyone's). Returns how many."""
    now = utcnow()
    async with connection.session_factory()() as s:
        q = select(OutgoingMail.id).where(OutgoingMail.status == "scheduled", OutgoingMail.send_at <= now)
        if user_id:
            q = q.where(OutgoingMail.user_id == user_id)
        ids = list((await s.scalars(q.order_by(OutgoingMail.send_at).limit(50))).all())
    sent = 0
    for oid in ids:
        async with connection.session_factory()() as s:
            row = await s.get(OutgoingMail, oid)
            if row is None or row.status != "scheduled" or _aware(row.send_at) > utcnow():
                continue  # cancelled or rescheduled meanwhile
            row.status = "sending"
            await s.commit()
            try:
                await _send_one(row)
                row.status, row.sent_at, row.error = "sent", utcnow(), None
                sent += 1
            except (SendError, ProviderAuthError, ProviderTemporaryError, ValueError) as exc:
                row.status, row.error = "failed", str(exc)[:300]
                s.add(AgentAlert(user_id=row.user_id, kind="send_failed", title=f"Could not send to {row.to_addr}",
                                 detail={"outgoing_id": row.id, "error": row.error}))
            await s.commit()
            user, to, status, error = row.user_id, row.to_addr, row.status, row.error
        await shield_runtime.audit().append("agent:mail", "mail_sent" if status == "sent" else "mail_send_failed",
                                            {"outgoing_id": oid, "to": to, "error": error}, user_id=user)
        if status == "sent":
            await add_contact(user, to, "approved")
    return sent


async def dispatch_forever(every_seconds: float = 10.0) -> None:
    """Background loop for the undo-window queue. Never raises."""
    while True:
        await asyncio.sleep(every_seconds)
        try:
            await dispatch_due()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the dispatcher must never die
            logger.warning(f"mail dispatcher iteration failed ({type(exc).__name__})")
