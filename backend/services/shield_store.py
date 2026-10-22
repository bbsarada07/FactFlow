"""Database-backed storage for the Shield audit chain and approvals.

The rules (hashing, token checks, expiry) stay in shield/; this module only persists. Both stores
are safe under concurrent writers: an audit append that loses the race for the next sequence
number retries on the new head, and an approval can only leave 'pending' once (conditional UPDATE).
"""
from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models import AuditLog, ShieldApproval
from shield.approvals import ApprovalError, check_decision, new_approval, sign, validate_secret
from shield.audit import VerifyResult, make_record, verify_chain
from shield.schemas import Approval, AuditRecord

APPEND_RETRIES = 8


def _aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _record(row: AuditLog) -> AuditRecord:
    return AuditRecord(seq=row.seq, ts=row.ts, actor=row.actor, event_type=row.event_type,
                       payload=row.payload_json or {}, prev_hash=row.prev_hash, hash=row.hash)


class SqlAuditLog:
    """Append-only hash chain in the `audit_log` table."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self.sf = session_factory
        self._lock = asyncio.Lock()

    async def head(self, session: AsyncSession) -> AuditRecord | None:
        row = await session.scalar(select(AuditLog).order_by(AuditLog.seq.desc()).limit(1))
        return _record(row) if row else None

    async def append(self, actor: str, event_type: str, payload: dict) -> AuditRecord:
        """Append one event. Payload PII is redacted before hashing and storage."""
        async with self._lock:
            for _ in range(APPEND_RETRIES):
                async with self.sf() as s:
                    rec = make_record(await self.head(s), actor, event_type, payload)
                    s.add(AuditLog(seq=rec.seq, ts=rec.ts, actor=rec.actor, event_type=rec.event_type,
                                   payload_json=rec.payload, prev_hash=rec.prev_hash, hash=rec.hash))
                    try:
                        await s.commit()
                        return rec
                    except IntegrityError:
                        await s.rollback()  # another process appended first; retry on its head
            raise RuntimeError("could not append to the audit log after repeated conflicts")

    async def page(self, offset: int = 0, limit: int = 50) -> tuple[list[AuditRecord], int]:
        async with self.sf() as s:
            total = await s.scalar(select(func.count()).select_from(AuditLog)) or 0
            rows = (await s.scalars(select(AuditLog).order_by(AuditLog.seq).offset(offset).limit(limit))).all()
            return [_record(r) for r in rows], total

    async def head_hash(self) -> str | None:
        async with self.sf() as s:
            head = await self.head(s)
            return head.hash if head else None

    async def verify(self) -> VerifyResult:
        """Recompute the whole chain from the database."""
        async with self.sf() as s:
            rows = (await s.scalars(select(AuditLog).order_by(AuditLog.seq))).all()
            return verify_chain(_record(r) for r in rows)


def _approval(row: ShieldApproval) -> Approval:
    return Approval(id=row.id, email_id=row.email_id, action=row.action, target=row.target, origin=row.origin,
                    rule_id=row.rule_id, reason=row.reason, evidence=row.evidence or {}, status=row.status,
                    created_at=_aware(row.created_at), expires_at=_aware(row.expires_at),
                    decided_by=row.decided_by, decided_at=_aware(row.decided_at))


class SqlApprovals:
    """Approvals in the `approvals` table, with audit events for creation and decisions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], secret: str | bytes,
                 audit: SqlAuditLog | None = None, ttl_seconds: int = 600,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        validate_secret(secret)  # fail fast: no approvals without a signing secret
        self.sf, self.secret, self.audit, self.ttl, self.clock = session_factory, secret, audit, ttl_seconds, clock

    async def create(self, **fields) -> tuple[Approval, str]:
        """Store a pending approval and return it with its single-use token."""
        a = new_approval(now=self.clock(), ttl_seconds=self.ttl, **fields)
        async with self.sf() as s:
            s.add(ShieldApproval(**a.model_dump()))
            await s.commit()
        if self.audit:
            await self.audit.append("system", "approval_created", {
                "approval_id": a.id, "email_id": a.email_id, "action": a.action, "target": a.target,
                "rule_id": a.rule_id})
        return a, sign(self.secret, a)

    async def get(self, approval_id: str) -> Approval | None:
        async with self.sf() as s:
            row = await s.get(ShieldApproval, approval_id)
            return _approval(row) if row else None

    async def list(self, status: str | None = None, limit: int = 100) -> list[Approval]:
        async with self.sf() as s:
            q = select(ShieldApproval).order_by(ShieldApproval.created_at.desc()).limit(limit)
            if status:
                q = q.where(ShieldApproval.status == status)
            return [_approval(r) for r in (await s.scalars(q)).all()]

    async def _set_status(self, approval_id: str, values: dict) -> bool:
        async with self.sf() as s:
            res = await s.execute(update(ShieldApproval)
                                  .where(ShieldApproval.id == approval_id, ShieldApproval.status == "pending")
                                  .values(**values))
            await s.commit()
            return res.rowcount == 1

    async def decide(self, approval_id: str, decision: str, token: str, decided_by: str,
                     triple: tuple[str, str, str | None] | None = None) -> Approval:
        """Apply a human decision. Raises ApprovalError (see shield/approvals.py) when refused."""
        now = self.clock()
        current = await self.get(approval_id)
        try:
            status = check_decision(current, decision, token, self.secret, now, triple)
        except ApprovalError as exc:
            if exc.code == "expired":
                await self._set_status(approval_id, {"status": "expired"})
            if self.audit and current is not None:
                await self.audit.append(f"human:{decided_by}", "approval_refused",
                                        {"approval_id": approval_id, "reason": exc.code})
            raise
        if not await self._set_status(approval_id, {"status": status, "decided_by": decided_by, "decided_at": now}):
            raise ApprovalError("not_pending", "This approval was decided by another request.")
        if self.audit:
            await self.audit.append(f"human:{decided_by}", "approval_decided",
                                    {"approval_id": approval_id, "decision": status, "action": current.action,
                                     "target": current.target})
        return current.model_copy(update={"status": status, "decided_by": decided_by, "decided_at": now})
