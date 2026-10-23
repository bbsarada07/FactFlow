"""WhatsApp providers (Phase 5A): Twilio (the sandbox by default) and a generic interface for the Meta Cloud API.

Inbound: webhook signatures are checked with a constant-time compare, then the form or JSON is parsed
into an InboundMessage. Outbound: exactly one kind of request exists, a text reply to the sender of an
inbound message through the provider's REST API (services/whatsapp_service.py decides when). Nothing
else is ever sent. Pure apart from httpx: credentials are passed in, no config or database imports.

The sender's phone number lives only in memory (InboundMessage.sender is hidden from repr); callers
store and log a salted hash of it instead.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit

import httpx

TWILIO_API = "https://api.twilio.com/2010-04-01"
TWILIO_MEDIA_HOSTS = ("api.twilio.com",)
TWILIO_MEDIA_REDIRECT_SUFFIXES = (".twilio.com", ".twiliocdn.com")  # media URLs redirect to Twilio's CDN
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
DEFAULT_PORTS = {"https": 443, "http": 80}


class WhatsAppSendError(Exception):
    """The provider refused or could not take the reply (the caller records delivery=failed)."""


class MediaError(Exception):
    """The media could not be fetched safely (wrong host, too large, or a network error)."""


# ------------------------------------------------------------------------------ signatures


def _values(params: Mapping[str, str | Sequence[str]], name: str) -> list[str]:
    value = params[name]
    return [value] if isinstance(value, str) else list(value)


def twilio_signature(auth_token: str, url: str, params: Mapping[str, str | Sequence[str]]) -> str:
    """X-Twilio-Signature: base64(HMAC-SHA1(auth token, full URL + every param name and value)), with
    names sorted and, for a repeated name, its values sorted (duplicates once), as Twilio's own validator."""
    s = url
    for name in sorted(set(params)):
        for value in sorted(set(_values(params, name))):
            s += name + value
    return base64.b64encode(hmac.new(auth_token.encode(), s.encode("utf-8"), hashlib.sha1).digest()).decode()


def _with_and_without_port(url: str) -> list[str]:
    parts = urlsplit(url)
    default = DEFAULT_PORTS.get(parts.scheme)
    host = parts.hostname or ""
    bare = urlunsplit((parts.scheme, host, parts.path, parts.query, parts.fragment))
    ported = urlunsplit((parts.scheme, f"{host}:{parts.port or default}", parts.path, parts.query, parts.fragment))
    return [url, bare, ported] if default or parts.port else [url]


def twilio_signature_valid(auth_token: str, url: str, params: Mapping[str, str | Sequence[str]],
                           header: str | None) -> bool:
    """Constant-time check of X-Twilio-Signature. Like Twilio's validator, the URL is tried as given,
    without its port and with the default port. A missing header or token is never valid."""
    if not header or not auth_token:
        return False
    ok = False
    for candidate in dict.fromkeys(_with_and_without_port(url)):
        ok |= hmac.compare_digest(twilio_signature(auth_token, candidate, params).encode(), header.strip().encode())
    return ok


def meta_signature_valid(app_secret: str, body: bytes, header: str | None) -> bool:
    """Constant-time check of Meta's X-Hub-Signature-256: "sha256=" + hex HMAC-SHA256(app secret, raw body)."""
    if not header or not app_secret or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected.encode(), header.strip().encode())


# --------------------------------------------------------------------------------- parsing


@dataclass(frozen=True)
class InboundMedia:
    url: str = field(repr=False)
    content_type: str


@dataclass(frozen=True)
class InboundMessage:
    """One message a person sent to the FactFlow WhatsApp number. `sender` and `text` are hidden from
    repr so a stray log line cannot leak them."""

    provider: str
    message_id: str
    sender: str = field(repr=False)  # E.164, e.g. +919876543210; memory only
    text: str = field(default="", repr=False)
    media: tuple[InboundMedia, ...] = ()


def _strip_channel(address: str) -> str:
    return address.split(":", 1)[1] if address.lower().startswith("whatsapp:") else address


def parse_twilio(params: Mapping[str, str | Sequence[str]]) -> InboundMessage:
    """Twilio's webhook form (MessageSid, From=whatsapp:+91..., Body, NumMedia, MediaUrlN, MediaContentTypeN)."""
    def first(name: str) -> str:
        return _values(params, name)[0] if name in params and _values(params, name) else ""

    try:
        count = max(0, min(int(first("NumMedia") or 0), 10))
    except ValueError:
        count = 0
    media = tuple(InboundMedia(first(f"MediaUrl{i}"), first(f"MediaContentType{i}").lower())
                  for i in range(count) if first(f"MediaUrl{i}"))
    return InboundMessage(provider="twilio", message_id=first("MessageSid") or first("SmsMessageSid"),
                          sender=_strip_channel(first("From")), text=first("Body"), media=media)


def parse_meta(payload: dict) -> list[InboundMessage]:
    """Meta Cloud API webhook JSON (entry[].changes[].value.messages[]). Media arrive as ids, not URLs;
    `url` holds the media id for a future Meta media download (not implemented)."""
    out = []
    for entry in payload.get("entry") or []:
        for change in entry.get("changes") or []:
            for m in (change.get("value") or {}).get("messages") or []:
                kind = m.get("type", "")
                media: tuple[InboundMedia, ...] = ()
                if kind in ("image", "audio", "video", "document"):
                    obj = m.get(kind) or {}
                    media = (InboundMedia(str(obj.get("id", "")), str(obj.get("mime_type", kind)).lower()),)
                sender = str(m.get("from", ""))
                out.append(InboundMessage(provider="meta", message_id=str(m.get("id", "")),
                                          sender=sender if sender.startswith("+") else f"+{sender}",
                                          text=str((m.get("text") or {}).get("body", "")), media=media))
    return out


# ------------------------------------------------------------------------------- providers


@dataclass(frozen=True)
class SendResult:
    provider_message_id: str | None


class WhatsAppProvider(ABC):
    """Replies to the person who wrote, and fetches the media they sent. Nothing else."""

    name: str

    @abstractmethod
    async def send_text(self, to: str, body: str) -> SendResult:
        """Send one text message to `to` (the sender of the message being answered)."""

    @abstractmethod
    async def fetch_media(self, url: str, max_bytes: int) -> bytes:
        """The bytes of one inbound media item, refusing anything over `max_bytes`."""


async def _read_limited(resp: httpx.Response, max_bytes: int) -> bytes:
    declared = resp.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise MediaError("media is larger than the limit")
    data = bytearray()
    async for chunk in resp.aiter_bytes():
        data += chunk
        if len(data) > max_bytes:
            raise MediaError("media is larger than the limit")
    return bytes(data)


class TwilioWhatsAppProvider(WhatsAppProvider):
    name = "twilio"

    def __init__(self, account_sid: str, auth_token: str, from_number: str,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.account_sid, self.auth_token = account_sid, auth_token
        self.from_number = _strip_channel(from_number)
        self.transport = transport

    async def send_text(self, to: str, body: str) -> SendResult:
        url = f"{TWILIO_API}/Accounts/{self.account_sid}/Messages.json"
        form = {"From": f"whatsapp:{self.from_number}", "To": f"whatsapp:{_strip_channel(to)}", "Body": body}
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT, trust_env=False) as http:
                resp = await http.post(url, data=form, auth=(self.account_sid, self.auth_token))
        except httpx.HTTPError as exc:
            raise WhatsAppSendError(f"network error: {type(exc).__name__}") from None
        if resp.status_code >= 400:
            raise WhatsAppSendError(f"Twilio answered {resp.status_code}")
        return SendResult((resp.json() or {}).get("sid"))

    async def fetch_media(self, url: str, max_bytes: int) -> bytes:
        """Twilio media URLs need the account credentials and redirect to Twilio's CDN. Only https URLs on
        api.twilio.com are fetched, and a redirect is followed only to another Twilio host (no SSRF)."""
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in TWILIO_MEDIA_HOSTS:
            raise MediaError("media URL is not a Twilio media URL")
        try:
            async with httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT, trust_env=False) as http:
                for hop in range(3):
                    auth = (self.account_sid, self.auth_token) if hop == 0 else None
                    async with http.stream("GET", url, auth=auth) as resp:
                        if resp.is_redirect:
                            nxt = urlsplit(str(resp.next_request.url) if resp.next_request else resp.headers.get("location", ""))
                            host = nxt.hostname or ""
                            if nxt.scheme != "https" or not (host in TWILIO_MEDIA_HOSTS or host.endswith(TWILIO_MEDIA_REDIRECT_SUFFIXES)):
                                raise MediaError("media redirect leaves Twilio")
                            url = urlunsplit(nxt)
                            continue
                        if resp.status_code >= 400:
                            raise MediaError(f"Twilio answered {resp.status_code}")
                        return await _read_limited(resp, max_bytes)
        except httpx.HTTPError as exc:
            raise MediaError(f"network error: {type(exc).__name__}") from None
        raise MediaError("too many redirects")


class MetaCloudProvider(WhatsAppProvider):
    """The Meta Cloud API behind the same interface. Signature checks and parsing work (above); sending and
    media download are not implemented yet, so replies for Meta are recorded as DRY RUN."""

    name = "meta"

    async def send_text(self, to: str, body: str) -> SendResult:
        raise NotImplementedError("Meta Cloud API sending is not implemented yet")

    async def fetch_media(self, url: str, max_bytes: int) -> bytes:
        raise NotImplementedError("Meta Cloud API media download is not implemented yet")
