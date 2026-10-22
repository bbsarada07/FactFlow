"""View tokens: let whoever submitted a message read its analysis without the operator token.

The token is an HMAC of the email id under SECRET_KEY, so it is never stored and a repeat
submission gets the same token. Messages fetched by the mail agent (Gmail, demo inbox) never get
one: only the operator can read those. Without a SECRET_KEY a random per-process key is used, so
tokens stop working after a restart.
"""
import hashlib
import hmac
import secrets

from config import settings

_fallback_key = secrets.token_bytes(32)


def _key() -> bytes:
    return settings.SECRET_KEY.encode() if len(settings.SECRET_KEY or "") >= 32 else _fallback_key


def view_token(email_id: str) -> str:
    return hmac.new(_key(), f"view:{email_id}".encode(), hashlib.sha256).hexdigest()[:40]


def valid(email_id: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(view_token(email_id), token)
