"""Encryption at rest for OAuth tokens (Fernet; key from TOKEN_ENCRYPTION_KEY).

Generate a key with:
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
Without a valid key, Gmail cannot be connected (fail closed). Token values are never logged.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from config import settings


def fernet() -> Fernet | None:
    """The configured cipher, or None when TOKEN_ENCRYPTION_KEY is missing or not a Fernet key."""
    key = settings.TOKEN_ENCRYPTION_KEY
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError):
        return None


def encrypt(f: Fernet, value: str | None) -> str | None:
    return f.encrypt(value.encode("utf-8")).decode("ascii") if value else None


def decrypt(f: Fernet, value: str | None) -> str | None:
    """Plain token, or None when there is none or it cannot be decrypted (key changed)."""
    if not value:
        return None
    try:
        return f.decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken:
        return None
