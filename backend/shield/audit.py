"""Tamper-evident audit log: a SHA-256 hash chain (master prompt section 8).

hash = SHA-256(prev_hash | canonical_json({actor, event_type, payload}) | ts | seq)

The actor and event type are inside the hashed body (stricter than hashing the payload alone),
so changing who did something, or what kind of event it was, also breaks the chain. Payloads
are PII-redacted before hashing and storage. Pure logic here; the database store is in
services/shield_store.py.
"""
from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

from shield.redact import redact_obj
from shield.schemas import AuditRecord

GENESIS = "0" * 64


def canonical_json(obj) -> str:
    """Stable JSON: sorted keys, no extra whitespace, UTF-8 kept, non-JSON values as strings."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def timestamp(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def compute_hash(prev_hash: str, seq: int, ts: str, actor: str, event_type: str, payload: dict) -> str:
    body = canonical_json({"actor": actor, "event_type": event_type, "payload": payload})
    return hashlib.sha256(f"{prev_hash}|{body}|{ts}|{seq}".encode("utf-8")).hexdigest()


def prepare_payload(payload: dict) -> dict:
    """Redact PII and round-trip through canonical JSON so the stored payload is exactly what was hashed."""
    return json.loads(canonical_json(redact_obj(payload or {})))


def make_record(head: AuditRecord | None, actor: str, event_type: str, payload: dict,
                now: datetime | None = None) -> AuditRecord:
    """The next record after `head` (or the first record when head is None)."""
    seq = (head.seq + 1) if head else 1
    prev = head.hash if head else GENESIS
    ts = timestamp(now)
    clean = prepare_payload(payload)
    return AuditRecord(seq=seq, ts=ts, actor=actor, event_type=event_type, payload=clean, prev_hash=prev,
                       hash=compute_hash(prev, seq, ts, actor, event_type, clean))


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    checked: int
    first_broken_seq: int | None = None
    reason: str = ""


def verify_chain(records: Iterable[AuditRecord]) -> VerifyResult:
    """Recompute every hash in order. Reports the first record that was changed, removed or reordered."""
    prev, expected_seq, checked = GENESIS, 1, 0
    for r in records:
        if r.seq != expected_seq:
            return VerifyResult(False, checked, expected_seq, f"record #{expected_seq} is missing or out of order")
        if r.prev_hash != prev:
            return VerifyResult(False, checked, r.seq, f"record #{r.seq} does not link to the record before it")
        if compute_hash(r.prev_hash, r.seq, r.ts, r.actor, r.event_type, r.payload) != r.hash:
            return VerifyResult(False, checked, r.seq, f"record #{r.seq} was modified after it was written")
        prev, expected_seq, checked = r.hash, expected_seq + 1, checked + 1
    return VerifyResult(True, checked)


class InMemoryAuditLog:
    """Append-only chain in memory (tests and the edge device)."""

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()

    def append(self, actor: str, event_type: str, payload: dict) -> AuditRecord:
        with self._lock:
            rec = make_record(self._records[-1] if self._records else None, actor, event_type, payload)
            self._records.append(rec)
            return rec

    @property
    def head(self) -> AuditRecord | None:
        with self._lock:
            return self._records[-1] if self._records else None

    def records(self) -> list[AuditRecord]:
        with self._lock:
            return list(self._records)

    def verify(self) -> VerifyResult:
        return verify_chain(self.records())
