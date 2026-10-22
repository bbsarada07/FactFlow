"""Parse an RFC 822 email (an .eml upload, pasted raw source or Gmail 'raw' bytes) or plain pasted
text into a ParsedEmail (master prompt section 4.1).

Attachments are never executed, opened or rendered. Only .txt and .pdf attachments have their text
extracted for scanning; everything else is metadata only.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

MAX_BYTES = 5 * 1024 * 1024
MAX_ATTACHMENTS = 20
MAX_BODY_CHARS = 200_000
MAX_ATTACHMENT_TEXT = 50_000
MAX_PDF_PAGES = 20

_HEADER_LINE = re.compile(rb"^[A-Za-z0-9-]{2,40}:[ \t]", re.MULTILINE)
_KNOWN_HEADERS = (b"from:", b"to:", b"subject:", b"date:", b"received:", b"message-id:", b"mime-version:",
                  b"return-path:", b"delivered-to:", b"content-type:")


class EmailInputError(ValueError):
    """Input rejected: too large, too many attachments, or not parseable. Maps to HTTP 4xx."""


@dataclass
class Attachment:
    filename: str
    content_type: str
    size: int
    sha256: str
    inline: bool = False
    text: str | None = None  # extracted text (.txt / .pdf only)
    metadata: dict[str, str] = field(default_factory=dict)  # PDF document info
    data: bytes = field(default=b"", repr=False)  # kept in memory for QR decoding; never persisted
    scan_note: str | None = None  # set when text that should have been scanned was not (fully) read

    def summary(self) -> dict:
        return {"filename": self.filename, "content_type": self.content_type, "size": self.size,
                "sha256": self.sha256, "inline": self.inline, "text_extracted": self.text is not None,
                "scan_note": self.scan_note}


@dataclass
class ParsedEmail:
    source: str
    has_headers: bool
    from_addr: str = ""
    from_display: str = ""
    reply_to: str = ""
    return_path: str = ""
    to: list[str] = field(default_factory=list)
    subject: str = ""
    date: str = ""
    message_id: str = ""
    received: list[str] = field(default_factory=list)
    authentication_results: list[str] = field(default_factory=list)
    received_spf: list[str] = field(default_factory=list)
    dkim_signature_present: bool = False
    text_plain: str | None = None
    text_html: str | None = None
    has_alternative: bool = False
    attachments: list[Attachment] = field(default_factory=list)
    body_truncated: bool = False
    sha256: str = ""

    @property
    def from_domain(self) -> str:
        return self.from_addr.rpartition("@")[2].lower() if "@" in self.from_addr else ""


def looks_like_rfc822(data: bytes) -> bool:
    """True when the input starts with a header block (at least two header lines, one well known)."""
    head = data.lstrip()[:4096].split(b"\r\n\r\n", 1)[0].split(b"\n\n", 1)[0]
    lines = _HEADER_LINE.findall(head)
    return len(lines) >= 2 and any(head.lower().startswith(h) or b"\n" + h in head.lower() for h in _KNOWN_HEADERS)


def _decode_part(part: EmailMessage) -> str:
    try:
        content = part.get_content()
        if isinstance(content, str):
            return content
    except (LookupError, KeyError, ValueError, AssertionError):
        pass
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _pdf_text(data: bytes) -> tuple[str | None, dict[str, str], str | None]:
    """(text, metadata, scan_note). scan_note is set when the PDF could not be fully read."""
    if not data.startswith(b"%PDF"):
        return None, {}, "file is named .pdf but is not a PDF, so its text was not scanned"
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        meta = {}
        if reader.metadata:
            for key, value in reader.metadata.items():
                if value is not None:
                    meta[str(key).lstrip("/")] = str(value)[:2000]
        parts, note = [], None
        pages = reader.pages
        for i, page in enumerate(pages):
            if i >= MAX_PDF_PAGES:
                note = f"only the first {MAX_PDF_PAGES} of {len(pages)} pages were scanned"
                break
            parts.append(page.extract_text() or "")
            if sum(len(p) for p in parts) > MAX_ATTACHMENT_TEXT:
                note = f"only the first {MAX_ATTACHMENT_TEXT:,} characters were scanned"
                break
        return "\n".join(parts)[:MAX_ATTACHMENT_TEXT], meta, note
    except Exception:  # noqa: BLE001 - malformed PDFs are reported, never treated as clean
        return None, {}, "the PDF could not be read, so its text was not scanned"


def _attachment(part: EmailMessage) -> Attachment:
    data = part.get_payload(decode=True) or b""
    filename = part.get_filename() or "(unnamed)"
    ctype = part.get_content_type()
    att = Attachment(
        filename=filename, content_type=ctype, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        inline=(part.get_content_disposition() == "inline"), data=data,
    )
    lower = filename.lower()
    if lower.endswith(".txt") or ctype == "text/plain":
        att.text = data[:MAX_ATTACHMENT_TEXT].decode("utf-8", errors="replace")
        if len(data) > MAX_ATTACHMENT_TEXT:
            att.scan_note = f"only the first {MAX_ATTACHMENT_TEXT:,} bytes were scanned"
    elif lower.endswith(".pdf") or ctype == "application/pdf":
        att.text, att.metadata, att.scan_note = _pdf_text(data)
    return att


def _cap(text: str | None) -> tuple[str | None, bool]:
    if text is None or len(text) <= MAX_BODY_CHARS:
        return text, False
    return text[:MAX_BODY_CHARS], True


def parse_email(data: bytes, source: str = "upload") -> ParsedEmail:
    """Parse raw RFC 822 bytes. Raises EmailInputError when limits are exceeded."""
    if len(data) > MAX_BYTES:
        raise EmailInputError(f"Email is larger than {MAX_BYTES // (1024 * 1024)} MB")
    msg: EmailMessage = message_from_bytes(data, policy=policy.default)  # type: ignore[assignment]
    pe = ParsedEmail(source=source, has_headers=True, sha256=hashlib.sha256(data).hexdigest())

    def header(name: str) -> str:
        try:
            value = msg.get(name)
            return str(value) if value is not None else ""
        except Exception:  # noqa: BLE001 - malformed header: keep it raw
            raw = msg.get_all(name, failobj=[])
            return str(raw[0]) if raw else ""

    pe.from_display, pe.from_addr = parseaddr(header("From"))
    pe.from_addr = pe.from_addr.lower()
    pe.reply_to = parseaddr(header("Reply-To"))[1].lower()
    pe.return_path = parseaddr(header("Return-Path"))[1].lower()
    pe.to = [a.lower() for _, a in getaddresses([header("To")]) if a]
    pe.subject = header("Subject")
    pe.date = header("Date")
    pe.message_id = header("Message-ID")
    pe.received = [str(h) for h in msg.get_all("Received", failobj=[])]
    pe.authentication_results = [str(h) for h in msg.get_all("Authentication-Results", failobj=[])]
    pe.received_spf = [str(h) for h in msg.get_all("Received-SPF", failobj=[])]
    pe.dkim_signature_present = bool(msg.get_all("DKIM-Signature", failobj=[]))

    attachments = 0
    for part in msg.walk():
        if part.is_multipart():
            if part.get_content_subtype() == "alternative":
                pe.has_alternative = True
            continue
        disposition = part.get_content_disposition()
        ctype = part.get_content_type()
        if disposition == "attachment" or (disposition == "inline" and not ctype.startswith("text/")) \
                or (part.get_filename() and not ctype.startswith("text/")):
            attachments += 1
            if attachments > MAX_ATTACHMENTS:
                raise EmailInputError(f"Email has more than {MAX_ATTACHMENTS} attachments")
            pe.attachments.append(_attachment(part))
        elif ctype == "text/plain" and pe.text_plain is None:
            pe.text_plain = _decode_part(part)
        elif ctype == "text/html" and pe.text_html is None:
            pe.text_html = _decode_part(part)
        elif ctype.startswith("text/"):
            attachments += 1
            if attachments > MAX_ATTACHMENTS:
                raise EmailInputError(f"Email has more than {MAX_ATTACHMENTS} attachments")
            pe.attachments.append(_attachment(part))

    pe.text_plain, cut_plain = _cap(pe.text_plain)
    pe.text_html, cut_html = _cap(pe.text_html)
    pe.body_truncated = cut_plain or cut_html
    return pe


def parse_plain_text(text: str, source: str = "paste") -> ParsedEmail:
    """A pasted message without headers: body only."""
    data = (text or "").encode("utf-8")
    if len(data) > MAX_BYTES:
        raise EmailInputError(f"Text is larger than {MAX_BYTES // (1024 * 1024)} MB")
    body, cut = _cap(text or "")
    return ParsedEmail(source=source, has_headers=False, text_plain=body, body_truncated=cut,
                       sha256=hashlib.sha256(data).hexdigest())


def parse_input(data: bytes | str, source: str = "paste") -> ParsedEmail:
    """Parse raw email source if the input starts with headers, otherwise treat it as plain text."""
    raw = data.encode("utf-8") if isinstance(data, str) else data
    if len(raw) > MAX_BYTES:
        raise EmailInputError(f"Input is larger than {MAX_BYTES // (1024 * 1024)} MB")
    if looks_like_rfc822(raw):
        return parse_email(raw, source)
    return parse_plain_text(raw.decode("utf-8", errors="replace"), source)
