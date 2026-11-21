"""Each user's connected Gmail account: OAuth connect/callback/disconnect, encrypted token storage, and the
token source the Gmail provider uses.

Every function takes the owner's user_id; one user can never read or use another user's tokens. Tokens are
Fernet-encrypted in the `user_mail_accounts` table and never logged or returned by any route. An expired or
revoked token puts the account in "reconnect_required" instead of raising out of the poller. One Gmail address
can be connected to only one FactFlow account (two agents on one mailbox would act twice).
"""
from __future__ import annotations

import secrets
import time
from datetime import datetime, timezone

import httpx
from loguru import logger
from sqlalchemy import select

from config import settings
from database import connection
from database.models import MailAccount, iso, utcnow
from services import shield_runtime
from services.token_crypto import decrypt, encrypt, fernet
from shield.providers.base import ProviderAuthError, ProviderTemporaryError
from shield.providers.gmail import (
    GMAIL_READONLY_SCOPE,
    can_label,
    can_send,
    GmailApiProvider,
    OAuthClient,
    ScopeError,
    TokenSet,
    authorization_url,
    exchange_code,
    pkce_pair,
    refresh,
    revoke,
)

PROVIDER = "gmail"
STATE_TTL_SECONDS = 600
# Tests replace this with a transport that replays the recorded Gmail and OAuth fixtures.
HTTP_TRANSPORT: httpx.AsyncBaseTransport | None = None


class GmailSetupError(Exception):
    """Gmail cannot be connected because server configuration is missing."""


class _States:
    """OAuth state values waiting for their callback: single use, 10-minute life, kept in memory, and bound to
    the user who started the connection."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, str, float]] = {}

    def create(self, verifier: str, user_id: str) -> str:
        now = time.monotonic()
        self._items = {k: v for k, v in self._items.items() if now - v[2] < STATE_TTL_SECONDS}
        state = secrets.token_urlsafe(32)
        self._items[state] = (verifier, user_id, now)
        return state

    def pop(self, state: str) -> tuple[str, str] | None:
        """(verifier, user_id) for a fresh state, else None."""
        item = self._items.pop(state or "", None)
        if item is None or time.monotonic() - item[2] >= STATE_TTL_SECONDS:
            return None
        return item[0], item[1]


states = _States()


def redirect_uri() -> str:
    return settings.GOOGLE_REDIRECT_URI or f"{settings.FRONTEND_URL.rstrip('/')}/api/mail/gmail/callback"


class AddressTaken(Exception):
    """This Gmail address is already connected to another FactFlow account."""


def missing_settings() -> list[str]:
    missing = [name for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET") if not getattr(settings, name)]
    if fernet() is None:
        missing.append("TOKEN_ENCRYPTION_KEY")
    return missing


def oauth_client() -> OAuthClient:
    missing = missing_settings()
    if missing:
        raise GmailSetupError("Gmail is not set up on the server; missing: " + ", ".join(missing))
    return OAuthClient(settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, redirect_uri())


async def _account(session, user_id: str) -> MailAccount | None:
    return await session.scalar(select(MailAccount).where(MailAccount.user_id == user_id,
                                                          MailAccount.provider == PROVIDER))


def start_connect(user_id: str, login_hint: str | None = None) -> str:
    """The Google consent URL (gmail.readonly only), with a fresh state bound to this user and a PKCE challenge."""
    client = oauth_client()
    verifier, challenge = pkce_pair()
    return authorization_url(client, states.create(verifier, user_id), challenge, login_hint=login_hint)


async def _save_tokens(row: MailAccount, tokens: TokenSet) -> None:
    f = fernet()
    row.access_token_enc = encrypt(f, tokens.access_token)
    row.access_token_expires_at = tokens.expires_at
    if tokens.refresh_token:
        row.refresh_token_enc = encrypt(f, tokens.refresh_token)
    row.scope = tokens.scope


async def finish_connect(state: str, code: str, user_id: str) -> dict:
    """Handle the OAuth callback for the signed-in `user_id`. Raises ProviderAuthError (bad state or code, or a
    state started by someone else), ScopeError, AddressTaken or GmailSetupError."""
    client = oauth_client()
    saved = states.pop(state)
    if saved is None or saved[1] != user_id:
        raise ProviderAuthError("the connect request expired or was already used; start again")
    verifier = saved[0]
    try:
        tokens = await exchange_code(client, code, verifier, transport=HTTP_TRANSPORT)
    except ScopeError as exc:
        if exc.token:
            await revoke(exc.token, transport=HTTP_TRANSPORT)  # never keep a broader grant
        raise
    if not tokens.refresh_token:
        raise ProviderAuthError("Google did not return a refresh token; remove FactFlow's access in your Google "
                                "account settings and connect again")
    profile = await GmailApiProvider(_StaticTokens(tokens.access_token), transport=HTTP_TRANSPORT).profile()
    address = str(profile.get("emailAddress") or "").strip().lower()[:320] or None
    async with connection.session_factory()() as s:
        if address:
            other = await s.scalar(select(MailAccount.id).where(
                MailAccount.email_address == address, MailAccount.user_id != user_id,
                MailAccount.status != "disconnected"))
            if other is not None:
                await revoke(tokens.refresh_token or tokens.access_token, transport=HTTP_TRANSPORT)
                raise AddressTaken(address)
        row = await _account(s, user_id)
        if row is None:
            row = MailAccount(user_id=user_id, provider=PROVIDER)
            s.add(row)
        await _save_tokens(row, tokens)
        row.email_address = address
        row.status, row.connected_at, row.last_error, row.sync_cursor = "connected", utcnow(), None, None
        await s.commit()
    await shield_runtime.audit().append("agent:mail", "mail_connected", {"provider": PROVIDER, "scope": tokens.scope},
                                        user_id=user_id)
    return await status(user_id)


async def disconnect(user_id: str) -> dict:
    """Revoke the token at Google and delete it here. Local deletion happens even if Google is unreachable."""
    revoked = False
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
        if row is not None:
            f = fernet()
            token = (decrypt(f, row.refresh_token_enc) or decrypt(f, row.access_token_enc)) if f else None
            if token:
                revoked = await revoke(token, transport=HTTP_TRANSPORT)
            row.refresh_token_enc = row.access_token_enc = None
            row.access_token_expires_at = None
            row.status, row.last_error = "disconnected", None
            await s.commit()
    await shield_runtime.audit().append("agent:mail", "mail_disconnected", {"provider": PROVIDER, "revoked": revoked},
                                        user_id=user_id)
    return {"revoked": revoked, **await status(user_id)}


async def mark(user_id: str, status_: str, error: str | None) -> None:
    """Record a connection problem (never a token) without raising."""
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
        if row is not None:
            row.status, row.last_error = status_, (error or "")[:300] or None
            if status_ == "reconnect_required":
                row.access_token_enc = row.refresh_token_enc = None
            await s.commit()


async def status(user_id: str) -> dict:
    """What the UI shows: never any token."""
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
    configured = not missing_settings()
    if row is None:
        return {"provider": PROVIDER, "configured": configured, "status": "disconnected", "email_address": None,
                "connected_at": None, "last_sync_at": None, "last_error": None, "reconnect_required": False,
                "scope": None, "can_send": False, "can_label": False, "needs_upgrade": False}
    connected = row.status == "connected"
    sends, labels = can_send(row.scope), can_label(row.scope)
    return {"provider": PROVIDER, "configured": configured, "status": row.status, "email_address": row.email_address,
            "connected_at": iso(row.connected_at), "last_sync_at": iso(row.last_sync_at), "last_error": row.last_error,
            "reconnect_required": row.status == "reconnect_required", "scope": row.scope,
            "can_send": connected and sends, "can_label": connected and labels,
            # connected before FactFlow could act: reconnect once to allow replies and labels
            "needs_upgrade": connected and not (sends and labels)}


async def scope(user_id: str) -> str | None:
    """The scopes this user's connected Gmail granted (None when not connected)."""
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
    return row.scope if row is not None and row.status == "connected" else None


async def address(user_id: str) -> str | None:
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
    return row.email_address if row is not None else None


class _StaticTokens:
    """A single known-good access token (used once, right after the code exchange)."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def access_token(self) -> str:
        return self._token

    async def force_refresh(self) -> str:
        raise ProviderAuthError("the new access token was rejected")


class StoredTokens:
    """Token source backed by one user's encrypted account row; refreshes when needed."""

    def __init__(self, user_id: str) -> None:
        self.user_id = user_id

    async def _row_tokens(self) -> tuple[str | None, datetime | None, str | None]:
        self.scope = None
        f = fernet()
        if f is None:
            raise ProviderAuthError("TOKEN_ENCRYPTION_KEY is missing or changed")
        async with connection.session_factory()() as s:
            row = await _account(s, self.user_id)
            if row is None or row.status != "connected":
                raise ProviderAuthError("Gmail is not connected")
            expires = row.access_token_expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            self.scope = row.scope
            return decrypt(f, row.access_token_enc), expires, decrypt(f, row.refresh_token_enc)

    async def access_token(self) -> str:
        token, expires, _ = await self._row_tokens()
        if token and expires and expires > datetime.now(timezone.utc):
            return token
        return await self.force_refresh()

    async def force_refresh(self) -> str:
        _, _, refresh_token = await self._row_tokens()
        if not refresh_token:
            await mark(self.user_id, "reconnect_required", "no refresh token is stored")
            raise ProviderAuthError("Gmail needs to be reconnected")
        try:
            tokens = await refresh(oauth_client(), refresh_token, transport=HTTP_TRANSPORT, previous_scope=self.scope)
        except (ProviderAuthError, ScopeError, GmailSetupError) as exc:
            await mark(self.user_id, "reconnect_required", str(exc))
            logger.warning("Gmail access expired or was revoked; reconnect required")
            raise ProviderAuthError("Gmail needs to be reconnected") from exc
        except ProviderTemporaryError:
            raise
        async with connection.session_factory()() as s:
            row = await _account(s, self.user_id)
            await _save_tokens(row, tokens)
            await s.commit()
        return tokens.access_token


async def provider(user_id: str) -> GmailApiProvider | None:
    """This user's Gmail provider when their account is connected."""
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
    if row is None or row.status != "connected":
        return None
    return GmailApiProvider(StoredTokens(user_id), transport=HTTP_TRANSPORT, first_sync=settings.MAIL_FIRST_SYNC,
                            max_per_sync=settings.MAIL_MAX_PER_SYNC)


async def connected_user_ids() -> list[str]:
    """Users whose Gmail is connected (the poller's work list)."""
    async with connection.session_factory()() as s:
        return list((await s.scalars(select(MailAccount.user_id).where(
            MailAccount.provider == PROVIDER, MailAccount.status == "connected"))).all())


async def cursor(user_id: str) -> datetime | None:
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
    if row is None or row.sync_cursor is None:
        return None
    return row.sync_cursor if row.sync_cursor.tzinfo else row.sync_cursor.replace(tzinfo=timezone.utc)


async def record_sync(user_id: str, new_cursor: datetime | None, error: str | None) -> None:
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
        if row is None:
            return
        row.last_sync_at = utcnow()
        if new_cursor is not None:
            row.sync_cursor = new_cursor
        if row.status == "connected":
            row.last_error = error
        await s.commit()


async def sent_cursor(user_id: str) -> datetime | None:
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
    if row is None or row.sent_cursor is None:
        return None
    return row.sent_cursor if row.sent_cursor.tzinfo else row.sent_cursor.replace(tzinfo=timezone.utc)


async def record_sent_scan(user_id: str, new_cursor: datetime) -> None:
    async with connection.session_factory()() as s:
        row = await _account(s, user_id)
        if row is not None:
            row.sent_cursor = new_cursor
            await s.commit()
