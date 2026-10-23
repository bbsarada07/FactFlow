"""Operator settings that survive a restart: the policy mode (strict / balanced) and the chosen mail provider.

Stored in the `runtime_settings` table (SQLite and PostgreSQL). At startup `restore()` loads them; a missing or
invalid policy mode means "strict" and a missing or invalid provider means "auto", so a restart can never loosen
the policy. Changes are saved before they are applied in memory (api/policy.py, api/mail.py), so the stored value
is never looser than the running one.
"""
from __future__ import annotations

from dataclasses import replace

from loguru import logger

from database import connection
from database.models import RuntimeSetting
from services import mail_agent, shield_runtime

POLICY_MODE = "policy_mode"
MAIL_PROVIDER = "mail_provider"
ALLOWED = {POLICY_MODE: ("strict", "balanced"), MAIL_PROVIDER: ("auto", "gmail", "eml")}
DEFAULTS = {POLICY_MODE: "strict", MAIL_PROVIDER: "auto"}


async def read(key: str) -> tuple[str, bool]:
    """(value, stored): the stored value when it is valid, otherwise the safe default and False."""
    async with connection.session_factory()() as s:
        row = await s.get(RuntimeSetting, key)
    value = row.value if row is not None else None
    if value in ALLOWED[key]:
        return value, True
    return DEFAULTS[key], False


async def save(key: str, value: str, actor: str) -> None:
    if value not in ALLOWED[key]:
        raise ValueError(f"invalid value for {key}")
    async with connection.session_factory()() as s:
        row = await s.get(RuntimeSetting, key)
        if row is None:
            s.add(RuntimeSetting(key=key, value=value, updated_by=actor))
        else:
            row.value, row.updated_by = value, actor
        await s.commit()


async def restore() -> dict:
    """Apply the stored settings to the running process (called once at startup)."""
    mode, mode_stored = await read(POLICY_MODE)
    provider, provider_stored = await read(MAIL_PROVIDER)
    store = shield_runtime.policy_store()
    async with shield_runtime.policy_lock:
        current = store.get()
        if current.mode != mode:
            store.apply(replace(current, mode=mode), current)
    mail_agent.set_active(provider)
    result = {"policy_mode": mode, "policy_mode_stored": mode_stored,
              "mail_provider": provider, "mail_provider_stored": provider_stored}
    await shield_runtime.audit().append("system", "settings_restored", result)
    if not mode_stored:
        logger.info("No valid stored policy mode; starting in strict mode")
    return result
