"""Per-user agent settings that survive a restart: policy mode (strict / balanced), trusted recipient domains,
and which inbox the agent reads (auto / gmail / eml).

Stored in the `user_settings` table. A user with no row, or a stored value that is not valid, gets the safe
defaults: strict mode, the trusted domains from shield/config/policy.yml, and "auto" for the inbox. So a missing
or damaged row can never loosen anyone's policy. Changes go through PolicyStore's planning rules (loosening needs
confirm=true), are written to the audit log, and only then saved.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace

from database import connection
from database.models import UserSettings
from services import shield_runtime
from shield.policy import PolicyConfig, PolicyStore

MODES = ("strict", "balanced")
PROVIDERS = ("auto", "gmail", "eml")
_locks: dict[str, asyncio.Lock] = {}


def lock(user_id: str) -> asyncio.Lock:
    """One settings change at a time per user."""
    return _locks.setdefault(user_id, asyncio.Lock())


async def _row(user_id: str) -> UserSettings | None:
    async with connection.session_factory()() as s:
        return await s.get(UserSettings, user_id)


async def policy_for(user_id: str | None) -> PolicyConfig:
    """The policy this user's agent runs under (the system defaults when user_id is None)."""
    base = shield_runtime.policy_store().get()
    if user_id is None:
        return base
    row = await _row(user_id)
    if row is None:
        return replace(base, mode="strict")
    mode = row.policy_mode if row.policy_mode in MODES else "strict"
    domains = base.allowed_domains if row.allowed_domains is None else tuple(sorted(set(row.allowed_domains)))
    return replace(base, mode=mode, allowed_domains=domains)


async def mail_provider(user_id: str) -> str:
    row = await _row(user_id)
    return row.mail_provider if row is not None and row.mail_provider in PROVIDERS else "auto"


async def _save(user_id: str, **values) -> None:
    async with connection.session_factory()() as s:
        row = await s.get(UserSettings, user_id)
        if row is None:
            row = UserSettings(user_id=user_id)
            s.add(row)
        for k, v in values.items():
            setattr(row, k, v)
        await s.commit()


async def change_policy(user_id: str, actor: str, *, mode: str | None = None, domains: list[str] | None = None,
                        confirm: bool = False) -> PolicyConfig:
    """Plan, audit, then save one policy change. Raises PermissionError (needs confirm) or ValueError."""
    async with lock(user_id):
        current = await policy_for(user_id)
        store = PolicyStore(current)
        if mode is not None:
            new, change = store.plan_mode(mode, confirm=confirm, actor=actor)
        else:
            new, change = store.plan_domains(domains or [], confirm=confirm, actor=actor)
        if change is None:
            return current
        await shield_runtime.audit().append(actor, "policy_changed", change, user_id=user_id)
        if change["field"] == "policy_mode":
            await _save(user_id, policy_mode=new.mode)
        else:
            await _save(user_id, allowed_domains=list(new.allowed_domains))
        return new


async def set_mail_provider(user_id: str, provider: str, actor: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError("provider must be auto, gmail or eml")
    async with lock(user_id):
        await _save(user_id, mail_provider=provider)
    await shield_runtime.audit().append(actor, "mail_provider_changed", {"provider": provider}, user_id=user_id)


AUTONOMY = ("auto", "drafts", "off")


async def agent_settings(user_id: str) -> dict:
    """How much the mail agent does on its own (default auto) and whether it sends a daily digest (default on)."""
    row = await _row(user_id)
    autonomy = row.autonomy if row is not None and row.autonomy in AUTONOMY else "auto"
    digest = True if row is None or row.digest_enabled is None else bool(row.digest_enabled)
    return {"autonomy": autonomy, "digest_enabled": digest,
            "last_digest_at": row.last_digest_at.isoformat() if row is not None and row.last_digest_at else None}


async def set_agent_settings(user_id: str, actor: str, autonomy: str | None = None, digest_enabled: bool | None = None) -> dict:
    values = {}
    if autonomy is not None:
        if autonomy not in AUTONOMY:
            raise ValueError("autonomy must be auto, drafts or off")
        values["autonomy"] = autonomy
    if digest_enabled is not None:
        values["digest_enabled"] = bool(digest_enabled)
    if values:
        async with lock(user_id):
            await _save(user_id, **values)
        await shield_runtime.audit().append(actor, "agent_settings_changed", values, user_id=user_id)
    return await agent_settings(user_id)


async def mark_digest(user_id: str, at) -> None:
    async with lock(user_id):
        await _save(user_id, last_digest_at=at)
