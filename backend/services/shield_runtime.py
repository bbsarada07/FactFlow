"""Process-wide Shield objects: the audit log, the approval store and the policy settings."""
from __future__ import annotations

import asyncio

from config import settings
from database import connection
from services.shield_store import SqlApprovals, SqlAuditLog
from shield.approvals import ApprovalError, validate_secret
from shield.policy import PolicyStore, load_config

_audit: dict[int, SqlAuditLog] = {}
_policy: PolicyStore | None = None
policy_lock = asyncio.Lock()


def audit() -> SqlAuditLog:
    """The audit log for the current database (one instance, so appends share one lock)."""
    sf = connection.session_factory()
    key = id(sf)
    if key not in _audit:
        _audit.clear()
        _audit[key] = SqlAuditLog(sf)
    return _audit[key]


def approvals_enabled() -> bool:
    try:
        validate_secret(settings.APPROVAL_SECRET)
        return True
    except ApprovalError:
        return False


def approvals() -> SqlApprovals | None:
    """The approval store, or None when APPROVAL_SECRET is missing or too short (approvals off)."""
    if not approvals_enabled():
        return None
    cfg = policy_store().get()
    return SqlApprovals(connection.session_factory(), settings.APPROVAL_SECRET, audit=audit(),
                        ttl_seconds=cfg.approval_ttl_seconds)


def policy_store() -> PolicyStore:
    """Runtime policy settings, starting from shield/config/policy.yml. Changes are kept in memory
    (and in the audit log); a restart goes back to policy.yml."""
    global _policy
    if _policy is None:
        _policy = PolicyStore(load_config())
    return _policy
