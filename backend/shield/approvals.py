"""Human-in-the-loop approvals (master prompt section 7).

An approval is single use and bound to one exact (email_id, action, target) triple by an HMAC
token. Changing any part of the triple, reusing a decided approval, or deciding after expiry
fails. Approved actions only ever run against the simulated outbox.

The logic here is pure (no I/O). Stores provide an atomic compare-and-set so a token cannot be
used twice even by concurrent requests; services/shield_store.py has the database version.
"""
from __future__ import annotations

import hashlib
import hmac
import threading
import uuid
from datetime import datetime, timedelta, timezone

from shield.redact import redact_obj
from shield.schemas import Approval

MIN_SECRET_BYTES = 32
DECISIONS = {"approve": "approved", "deny": "denied"}


class ApprovalError(Exception):
    """A decision was refused. `code` is one of: no_secret, not_found, not_pending, expired,
    bad_token, mismatch, bad_decision."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def validate_secret(secret: str | bytes | None) -> bytes:
    """The signing key as bytes; raises ApprovalError('no_secret') if missing or shorter than 32 bytes."""
    key = secret.encode() if isinstance(secret, str) else (secret or b"")
    if len(key) < MIN_SECRET_BYTES:
        raise ApprovalError("no_secret", f"The approval signing secret must be at least {MIN_SECRET_BYTES} bytes.")
    return key




def _ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def sign(secret: str | bytes, approval: Approval) -> str:
    """HMAC-SHA256 over the approval id, the exact (email_id, action, target) triple and the expiry."""
    msg = "\x1f".join([approval.id, approval.email_id, approval.action, approval.target or "", _ts(approval.expires_at)])
    return hmac.new(validate_secret(secret), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def new_approval(*, email_id: str, action: str, target: str | None, origin: str, rule_id: str, reason: str,
                 evidence: dict | None, now: datetime, ttl_seconds: int = 600) -> Approval:
    """A pending approval. Evidence is redacted before it is stored or shown."""
    return Approval(
        id=uuid.uuid4().hex, email_id=email_id, action=action, target=target, origin=origin, rule_id=rule_id,
        reason=reason, evidence=redact_obj(evidence or {}), status="pending", created_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )


def check_decision(approval: Approval | None, decision: str, token: str, secret: str | bytes, now: datetime,
                   triple: tuple[str, str, str | None] | None = None) -> str:
    """Validate a decision and return the new status ('approved' / 'denied').

    Raises ApprovalError when the approval is missing, already decided, expired, the token does
    not match, or the caller's (email_id, action, target) differs from the approved one.
    """
    if decision not in DECISIONS:
        raise ApprovalError("bad_decision", "Decision must be 'approve' or 'deny'.")
    key = validate_secret(secret)
    if approval is None:
        raise ApprovalError("not_found", "No such approval.")
    if approval.status != "pending":
        raise ApprovalError("not_pending", f"This approval was already {approval.status}.")
    if now >= approval.expires_at:
        raise ApprovalError("expired", "This approval has expired. Run the check again to get a new one.")
    if not hmac.compare_digest(sign(key, approval), token or ""):
        raise ApprovalError("bad_token", "The approval token is not valid for this request.")
    if triple is not None and (triple[0], triple[1], triple[2] or None) != (approval.email_id, approval.action,
                                                                           approval.target or None):
        raise ApprovalError("mismatch", "The action or target differs from what was approved.")
    return DECISIONS[decision]


def decided(approval: Approval, status: str, decided_by: str, now: datetime) -> Approval:
    return approval.model_copy(update={"status": status, "decided_by": decided_by, "decided_at": now})


class InMemoryApprovalStore:
    """Thread-safe store used by tests and the edge device."""

    def __init__(self) -> None:
        self._items: dict[str, Approval] = {}
        self._lock = threading.Lock()

    def add(self, approval: Approval) -> None:
        with self._lock:
            self._items[approval.id] = approval

    def get(self, approval_id: str) -> Approval | None:
        with self._lock:
            return self._items.get(approval_id)

    def compare_and_set(self, approval_id: str, expected_status: str, new: Approval) -> bool:
        """Replace the approval only if its status is still `expected_status`."""
        with self._lock:
            cur = self._items.get(approval_id)
            if cur is None or cur.status != expected_status:
                return False
            self._items[approval_id] = new
            return True

    def list(self, status: str | None = None) -> list[Approval]:
        with self._lock:
            return [a for a in self._items.values() if status is None or a.status == status]


class ApprovalService:
    """Create and decide approvals against a synchronous store."""

    def __init__(self, store: InMemoryApprovalStore, secret: str | bytes, ttl_seconds: int = 600,
                 clock=lambda: datetime.now(timezone.utc)) -> None:
        validate_secret(secret)
        self.store, self.secret, self.ttl, self.clock = store, secret, ttl_seconds, clock

    def create(self, **fields) -> tuple[Approval, str]:
        """Store a new pending approval; returns it with its single-use token."""
        approval = new_approval(now=self.clock(), ttl_seconds=self.ttl, **fields)
        self.store.add(approval)
        return approval, sign(self.secret, approval)

    def decide(self, approval_id: str, decision: str, token: str, decided_by: str,
               triple: tuple[str, str, str | None] | None = None) -> Approval:
        now = self.clock()
        current = self.store.get(approval_id)
        try:
            status = check_decision(current, decision, token, self.secret, now, triple)
        except ApprovalError as exc:
            if exc.code == "expired" and current is not None:
                self.store.compare_and_set(approval_id, "pending", current.model_copy(update={"status": "expired"}))
            raise
        updated = decided(current, status, decided_by, now)
        if not self.store.compare_and_set(approval_id, "pending", updated):
            raise ApprovalError("not_pending", "This approval was decided by another request.")
        return updated
