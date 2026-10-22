"""Mail providers: where messages come from. Read-only by design (Addendum v2, A2).

A provider can list new messages and fetch one message's raw RFC 822 bytes. There is no method
to send, delete, modify, label, move or draft anything, so even a fooled agent has no way to
touch the mailbox (tests/test_mail_readonly.py checks this).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class RawMessageRef:
    """A message the provider can fetch. `message_id` is the provider's own id (Gmail message id,
    or the file name for the demo inbox)."""

    provider: str
    message_id: str
    received_at: datetime | None = None
    thread_id: str | None = None


class ProviderAuthError(Exception):
    """The provider's credentials expired or were revoked: the user must reconnect."""


class ProviderTemporaryError(Exception):
    """A temporary failure (rate limit, network, server error): try again on the next poll."""


@runtime_checkable
class MailProvider(Protocol):
    """Read-only access to one mailbox."""

    name: str

    async def list_new(self, since: datetime | None) -> list[RawMessageRef]:
        """Messages received after `since` (or the most recent few when `since` is None), oldest first."""
        ...

    async def fetch_raw(self, message_id: str) -> bytes:
        """The message as RFC 822 bytes, exactly as the provider stores it."""
        ...
