"""GmailApiProvider: read-only Gmail access over the Gmail REST API (Addendum v2, A2.1).

* The only OAuth scope is gmail.readonly. A token that comes back with any other scope is
  refused. Even a fully fooled agent therefore cannot send, delete or change mail.
* Every Gmail API call is a GET. Messages are fetched with format=raw and handed to the same
  RFC 822 parser as uploaded mail.
* OAuth uses the authorization-code flow with a state value and PKCE (S256). The client secret
  and tokens are passed in by the caller; this module never logs or stores them.

Uses httpx directly rather than google-api-python-client, so every request (and the recorded test
fixtures) is explicit and async (docs/DECISIONS.md).
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Protocol
from urllib.parse import urlencode

import httpx

from shield.providers.base import ProviderAuthError, ProviderTemporaryError, RawMessageRef

GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
FIRST_SYNC_COUNT = 20
MAX_PER_SYNC = 50
TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class ScopeError(Exception):
    """Google granted a scope other than gmail.readonly; the token is not accepted. `token` is
    the token that was issued, so the caller can revoke it (it is never stored)."""

    def __init__(self, message: str, token: str | None = None) -> None:
        super().__init__(message)
        self.token = token


@dataclass(frozen=True)
class OAuthClient:
    client_id: str
    client_secret: str
    redirect_uri: str


@dataclass(frozen=True)
class TokenSet:
    access_token: str
    expires_at: datetime
    refresh_token: str | None
    scope: str


def pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) for PKCE with S256."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    return verifier, challenge


def authorization_url(client: OAuthClient, state: str, code_challenge: str, login_hint: str | None = None) -> str:
    """Google consent screen URL asking for gmail.readonly only, with offline access."""
    params = {
        "client_id": client.client_id, "redirect_uri": client.redirect_uri, "response_type": "code",
        "scope": GMAIL_READONLY_SCOPE, "access_type": "offline", "prompt": "consent", "state": state,
        "code_challenge": code_challenge, "code_challenge_method": "S256",
    }
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_ENDPOINT}?{urlencode(params)}"


def _token_set(data: dict, previous_refresh: str | None = None) -> TokenSet:
    granted = set((data.get("scope") or "").split())
    if granted != {GMAIL_READONLY_SCOPE}:
        raise ScopeError("Google granted scopes other than gmail.readonly; FactFlow only accepts read-only access.",
                         token=data.get("refresh_token") or data.get("access_token"))
    return TokenSet(
        access_token=data["access_token"],
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)) - 60),
        refresh_token=data.get("refresh_token") or previous_refresh,
        scope=GMAIL_READONLY_SCOPE,
    )


async def _post_form(url: str, form: dict, transport: httpx.AsyncBaseTransport | None) -> httpx.Response:
    try:
        async with httpx.AsyncClient(transport=transport, timeout=TIMEOUT, trust_env=False) as http:
            return await http.post(url, data=form)
    except httpx.HTTPError as exc:
        raise ProviderTemporaryError(f"could not reach Google ({type(exc).__name__})") from exc


async def exchange_code(client: OAuthClient, code: str, code_verifier: str,
                        transport: httpx.AsyncBaseTransport | None = None) -> TokenSet:
    """Swap the authorization code for tokens (PKCE verifier included)."""
    resp = await _post_form(TOKEN_ENDPOINT, {
        "code": code, "client_id": client.client_id, "client_secret": client.client_secret,
        "redirect_uri": client.redirect_uri, "grant_type": "authorization_code", "code_verifier": code_verifier,
    }, transport)
    if resp.status_code != 200:
        raise ProviderAuthError(f"Google refused the authorization code ({_error_code(resp)})")
    return _token_set(resp.json())


async def refresh(client: OAuthClient, refresh_token: str, transport: httpx.AsyncBaseTransport | None = None) -> TokenSet:
    """New access token. An expired or revoked refresh token raises ProviderAuthError (reconnect)."""
    resp = await _post_form(TOKEN_ENDPOINT, {
        "client_id": client.client_id, "client_secret": client.client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token",
    }, transport)
    if resp.status_code in (400, 401):
        raise ProviderAuthError(f"Gmail access expired or was revoked ({_error_code(resp)})")
    if resp.status_code != 200:
        raise ProviderTemporaryError(f"Google token endpoint answered {resp.status_code}")
    data = resp.json()
    data.setdefault("scope", GMAIL_READONLY_SCOPE)
    return _token_set(data, previous_refresh=refresh_token)


async def revoke(token: str, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Ask Google to revoke a token. True if Google confirmed (or the token was already invalid)."""
    try:
        resp = await _post_form(REVOKE_ENDPOINT, {"token": token}, transport)
    except ProviderTemporaryError:
        return False
    return resp.status_code in (200, 400)


def _error_code(resp: httpx.Response) -> str:
    try:
        data = resp.json()
    except ValueError:
        return f"HTTP {resp.status_code}"
    err = data.get("error")
    if isinstance(err, dict):
        return str(err.get("status") or err.get("code") or resp.status_code)
    return str(err or resp.status_code)


class TokenSource(Protocol):
    async def access_token(self) -> str:
        """A currently valid access token (refreshing it if needed)."""
        ...

    async def force_refresh(self) -> str:
        """Refresh now, after the API rejected the current token."""
        ...


class GmailApiProvider:
    """Read-only Gmail provider. All requests are GETs to the Gmail API."""

    name = "gmail"

    def __init__(self, tokens: TokenSource, transport: httpx.AsyncBaseTransport | None = None,
                 first_sync: int = FIRST_SYNC_COUNT, max_per_sync: int = MAX_PER_SYNC) -> None:
        self.tokens, self.transport = tokens, transport
        self.first_sync, self.max_per_sync = first_sync, max_per_sync

    async def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in range(2):
            token = await (self.tokens.access_token() if attempt == 0 else self.tokens.force_refresh())
            try:
                async with httpx.AsyncClient(transport=self.transport, timeout=TIMEOUT, trust_env=False) as http:
                    resp = await http.get(f"{GMAIL_API}{path}", params=params or {},
                                          headers={"Authorization": f"Bearer {token}"})
            except httpx.HTTPError as exc:
                raise ProviderTemporaryError(f"could not reach Gmail ({type(exc).__name__})") from exc
            if resp.status_code == 401 and attempt == 0:
                continue
            if resp.status_code in (401, 403):
                raise ProviderAuthError(f"Gmail refused access ({_error_code(resp)})")
            if resp.status_code == 429 or resp.status_code >= 500:
                raise ProviderTemporaryError(f"Gmail answered {resp.status_code}")
            if resp.status_code != 200:
                raise ProviderTemporaryError(f"Gmail answered {resp.status_code} ({_error_code(resp)})")
            return resp.json()
        raise ProviderAuthError("Gmail refused access after a token refresh")

    async def profile(self) -> dict:
        """The connected address and mailbox counters."""
        return await self._get("/profile")

    async def list_new(self, since: datetime | None) -> list[RawMessageRef]:
        """Inbox messages after `since` (Gmail `after:` search, at most max_per_sync), or the last
        `first_sync` messages on first connect. Oldest first; the caller dedupes by message id."""
        if since is None:
            params = {"maxResults": self.first_sync, "labelIds": "INBOX"}
        else:
            params = {"maxResults": self.max_per_sync, "labelIds": "INBOX", "q": f"after:{int(since.timestamp())}"}
        data = await self._get("/messages", params)
        items = data.get("messages") or []
        return [RawMessageRef(self.name, m["id"], None, m.get("threadId")) for m in reversed(items) if m.get("id")]

    async def fetch_raw(self, message_id: str) -> bytes:
        """RFC 822 bytes of one message (users.messages.get with format=raw)."""
        if not message_id.replace("-", "").replace("_", "").isalnum():
            raise ValueError("invalid Gmail message id")
        data = await self._get(f"/messages/{message_id}", {"format": "raw"})
        raw = data.get("raw") or ""
        try:
            return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        except (binascii.Error, ValueError) as exc:
            raise ProviderTemporaryError("Gmail returned a message that could not be decoded") from exc
