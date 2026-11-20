"""Sign in with Google (OpenID Connect, authorization-code flow with PKCE).

Only `openid email profile` is requested here; Gmail access is a separate, later consent (services/gmail_account.py).
The `state`, PKCE verifier and return path travel in a short-lived HMAC-signed cookie, so nothing is kept in
memory and a restart between redirect and callback does not break sign-in.

The ID token comes straight from Google's token endpoint over TLS in exchange for our client secret, so per
OpenID Connect Core 3.1.3.7 the TLS connection authenticates the issuer; we still check iss, aud, exp and that
Google verified the email address.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from urllib.parse import urlencode

import httpx

from config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
SCOPE = "openid email profile"
STATE_COOKIE = "ff_oauth"
STATE_TTL_SECONDS = 600
# Tests replace this with a fake Google.
HTTP_TRANSPORT: httpx.AsyncBaseTransport | None = None


class LoginError(Exception):
    """Sign-in could not complete; `code` is a short reason safe to show in the URL."""

    def __init__(self, code: str, message: str = "") -> None:
        super().__init__(message or code)
        self.code = code


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str | None
    picture: str | None


def configured() -> bool:
    return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET and len(settings.SECRET_KEY or "") >= 32)


def redirect_uri() -> str:
    return f"{settings.FRONTEND_URL.rstrip('/')}/api/auth/google/callback"


def safe_next(path: str | None) -> str:
    """Only same-site relative paths: never '//evil.example' or 'https://...'."""
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path or len(path) > 500:
        return "/"
    return path


# ------------------------------------------------------------------------------------- signed state


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> str:
    return _b64(hmac.new(settings.SECRET_KEY.encode(), b"oauth-state:" + payload, hashlib.sha256).digest())


def pack_state(data: dict) -> str:
    payload = json.dumps(data, separators=(",", ":")).encode()
    return f"{_b64(payload)}.{_sign(payload)}"


def unpack_state(cookie: str | None) -> dict | None:
    if not cookie or "." not in cookie:
        return None
    body, mac = cookie.rsplit(".", 1)
    try:
        payload = _unb64(body)
    except (ValueError, TypeError):
        return None
    if not hmac.compare_digest(mac, _sign(payload)):
        return None
    data = json.loads(payload)
    if data.get("exp", 0) < time.time():
        return None
    return data


# ------------------------------------------------------------------------------------------- flow


def start(next_path: str | None) -> tuple[str, str]:
    """(Google consent URL, signed state cookie value)."""
    if not configured():
        raise LoginError("not_configured", "Google sign-in is not set up on the server")
    state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri(), "response_type": "code",
        "scope": SCOPE, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
        "prompt": "select_account",
    }
    cookie = pack_state({"state": state, "verifier": verifier, "next": safe_next(next_path),
                         "exp": int(time.time()) + STATE_TTL_SECONDS})
    return f"{AUTH_URL}?{urlencode(params)}", cookie


def _claims(id_token: str) -> dict:
    try:
        payload = id_token.split(".")[1]
        return json.loads(_unb64(payload))
    except (IndexError, ValueError):
        raise LoginError("bad_token", "Google returned an unreadable ID token") from None


async def finish(code: str, state: str, cookie: str | None) -> tuple[GoogleIdentity, str]:
    """Exchange the code. Returns (identity, next path). Raises LoginError."""
    saved = unpack_state(cookie)
    if saved is None or not hmac.compare_digest(saved.get("state", ""), state or ""):
        raise LoginError("expired", "The sign-in request expired or came from another browser; try again")
    form = {"code": code, "client_id": settings.GOOGLE_CLIENT_ID, "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri(), "grant_type": "authorization_code", "code_verifier": saved["verifier"]}
    try:
        async with httpx.AsyncClient(transport=HTTP_TRANSPORT, timeout=15) as client:
            resp = await client.post(TOKEN_URL, data=form)
    except httpx.HTTPError:
        raise LoginError("google_unreachable") from None
    if resp.status_code != 200:
        raise LoginError("exchange_failed", f"Google refused the sign-in code ({resp.status_code})")
    id_token = resp.json().get("id_token")
    if not id_token:
        raise LoginError("bad_token", "Google returned no ID token")
    claims = _claims(id_token)
    if claims.get("iss") not in ISSUERS or claims.get("aud") != settings.GOOGLE_CLIENT_ID:
        raise LoginError("bad_token", "The ID token was not issued for FactFlow")
    if int(claims.get("exp", 0)) < time.time():
        raise LoginError("bad_token", "The ID token has expired")
    email = str(claims.get("email") or "").strip().lower()
    if not email or claims.get("email_verified") not in (True, "true"):
        raise LoginError("email_not_verified", "Google has not verified this email address")
    if not claims.get("sub"):
        raise LoginError("bad_token", "The ID token has no subject")
    return GoogleIdentity(str(claims["sub"]), email, claims.get("name"), claims.get("picture")), saved["next"]
