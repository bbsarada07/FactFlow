"""The connected Gmail account: OAuth connect/callback/disconnect, encrypted token storage, and the
token source the read-only Gmail provider uses.

Tokens are Fernet-encrypted in the `mail_accounts` table and never logged or returned by any
route. An expired or revoked token puts the account in "reconnect_required" instead of raising
out of the poller.
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
    """OAuth state values waiting for their callback: single use, 10-minute life, kept in memory."""

    def __init__(self) -> None:
        self._items: dict[str, tuple[str, float]] = {}

    def create(self, verifier: str) -> str:
        now = time.monotonic()
        self._items = {k: v for k, v in self._items.items() if now - v[1] < STATE_TTL_SECONDS}
        state = secrets.token_urlsafe(32)
        self._items[state] = (verifier, now)
        return state

    def pop(self, state: str) -> str | None:
        item = self._items.pop(state or "", None)
        if item is None or time.monotonic() - item[1] >= STATE_TTL_SECONDS:
            return None
        return item[0]


states = _States()


def missing_settings() -> list[str]:
    missing = [name for name in ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REDIRECT_URI")
               if not getattr(settings, name)]
    if fernet() is None:
        missing.append("TOKEN_ENCRYPTION_KEY")
    return missing


def oauth_client() -> OAuthClient:
    missing = missing_settings()
    if missing:
        raise GmailSetupError("Gmail is not set up on the server; missing: " + ", ".join(missing))
    return OAuthClient(settings.GOOGLE_CLIENT_ID, settings.GOOGLE_CLIENT_SECRET, settings.GOOGLE_REDIRECT_URI)


async def _account(session) -> MailAccount | None:
    return await session.scalar(select(MailAccount).where(MailAccount.provider == PROVIDER))


def start_connect() -> str:
    """The Google consent URL (gmail.readonly only), with a fresh state and PKCE challenge."""
    client = oauth_client()
    verifier, challenge = pkce_pair()
    return authorization_url(client, states.create(verifier), challenge)


async def _save_tokens(row: MailAccount, tokens: TokenSet) -> None:
    f = fernet()
    row.access_token_enc = encrypt(f, tokens.access_token)
    row.access_token_expires_at = tokens.expires_at
    if tokens.refresh_token:
        row.refresh_token_enc = encrypt(f, tokens.refresh_token)
    row.scope = tokens.scope


async def finish_connect(state: str, code: str) -> dict:
    """Handle the OAuth callback. Raises ProviderAuthError (bad state or code), ScopeError or GmailSetupError."""
    client = oauth_client()
    verifier = states.pop(state)
    if verifier is None:
        raise ProviderAuthError("the connect request expired or was already used; start again")
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
    async with connection.session_factory()() as s:
        row = await _account(s)
        if row is None:
            row = MailAccount(provider=PROVIDER)
            s.add(row)
        await _save_tokens(row, tokens)
        row.email_address = str(profile.get("emailAddress") or "")[:320] or None
        row.status, row.connected_at, row.last_error, row.sync_cursor = "connected", utcnow(), None, None
        await s.commit()
    await shield_runtime.audit().append("human:operator", "mail_connected", {"provider": PROVIDER, "scope": GMAIL_READONLY_SCOPE})
    return await status()


async def disconnect() -> dict:
    """Revoke the token at Google and delete it here. Local deletion happens even if Google is unreachable."""
    revoked = False
    async with connection.session_factory()() as s:
        row = await _account(s)
        if row is not None:
            f = fernet()
            token = (decrypt(f, row.refresh_token_enc) or decrypt(f, row.access_token_enc)) if f else None
            if token:
                revoked = await revoke(token, transport=HTTP_TRANSPORT)
            row.refresh_token_enc = row.access_token_enc = None
            row.access_token_expires_at = None
            row.status, row.last_error = "disconnected", None
            await s.commit()
    await shield_runtime.audit().append("human:operator", "mail_disconnected", {"provider": PROVIDER, "revoked": revoked})
    return {"revoked": revoked, **await status()}


async def mark(status_: str, error: str | None) -> None:
    """Record a connection problem (never a token) without raising."""
    async with connection.session_factory()() as s:
        row = await _account(s)
        if row is not None:
            row.status, row.last_error = status_, (error or "")[:300] or None
            if status_ == "reconnect_required":
                row.access_token_enc = row.refresh_token_enc = None
            await s.commit()


async def status() -> dict:
    """What the UI shows: never any token."""
    async with connection.session_factory()() as s:
        row = await _account(s)
    configured = not missing_settings()
    if row is None:
        return {"provider": PROVIDER, "configured": configured, "status": "disconnected", "email_address": None,
                "connected_at": None, "last_sync_at": None, "last_error": None, "reconnect_required": False,
                "scope": GMAIL_READONLY_SCOPE}
    return {"provider": PROVIDER, "configured": configured, "status": row.status, "email_address": row.email_address,
            "connected_at": iso(row.connected_at), "last_sync_at": iso(row.last_sync_at), "last_error": row.last_error,
            "reconnect_required": row.status == "reconnect_required", "scope": GMAIL_READONLY_SCOPE}


class _StaticTokens:
    """A single known-good access token (used once, right after the code exchange)."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def access_token(self) -> str:
        return self._token

    async def force_refresh(self) -> str:
        raise ProviderAuthError("the new access token was rejected")


class StoredTokens:
    """Token source backed by the encrypted `mail_accounts` row; refreshes when needed."""

    async def _row_tokens(self) -> tuple[str | None, datetime | None, str | None]:
        f = fernet()
        if f is None:
            raise ProviderAuthError("TOKEN_ENCRYPTION_KEY is missing or changed")
        async with connection.session_factory()() as s:
            row = await _account(s)
            if row is None or row.status != "connected":
                raise ProviderAuthError("Gmail is not connected")
            expires = row.access_token_expires_at
            if expires is not None and expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return decrypt(f, row.access_token_enc), expires, decrypt(f, row.refresh_token_enc)

    async def access_token(self) -> str:
        token, expires, _ = await self._row_tokens()
        if token and expires and expires > datetime.now(timezone.utc):
            return token
        return await self.force_refresh()

    async def force_refresh(self) -> str:
        _, _, refresh_token = await self._row_tokens()
        if not refresh_token:
            await mark("reconnect_required", "no refresh token is stored")
            raise ProviderAuthError("Gmail needs to be reconnected")
        try:
            tokens = await refresh(oauth_client(), refresh_token, transport=HTTP_TRANSPORT)
        except (ProviderAuthError, ScopeError, GmailSetupError) as exc:
            await mark("reconnect_required", str(exc))
            logger.warning("Gmail access expired or was revoked; reconnect required")
            raise ProviderAuthError("Gmail needs to be reconnected") from exc
        except ProviderTemporaryError:
            raise
        async with connection.session_factory()() as s:
            row = await _account(s)
            await _save_tokens(row, tokens)
            await s.commit()
        return tokens.access_token


async def provider() -> GmailApiProvider | None:
    """The read-only Gmail provider when an account is connected."""
    async with connection.session_factory()() as s:
        row = await _account(s)
    if row is None or row.status != "connected":
        return None
    return GmailApiProvider(StoredTokens(), transport=HTTP_TRANSPORT, first_sync=settings.MAIL_FIRST_SYNC,
                            max_per_sync=settings.MAIL_MAX_PER_SYNC)


async def cursor() -> datetime | None:
    async with connection.session_factory()() as s:
        row = await _account(s)
    if row is None or row.sync_cursor is None:
        return None
    return row.sync_cursor if row.sync_cursor.tzinfo else row.sync_cursor.replace(tzinfo=timezone.utc)


async def record_sync(new_cursor: datetime | None, error: str | None) -> None:
    async with connection.session_factory()() as s:
        row = await _account(s)
        if row is None:
            return
        row.last_sync_at = utcnow()
        if new_cursor is not None:
            row.sync_cursor = new_cursor
        if row.status == "connected":
            row.last_error = error
        await s.commit()
