"""The policy mode and the chosen mail provider survive a backend restart, and a restart never loosens anything."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from standins import OP


@pytest.fixture
def app_env(db_url, monkeypatch):
    """Settings for starting the real app (lifespan included) more than once on the same database."""
    import main  # noqa: F401  (imported so the routers exist)
    from config import settings
    from database import connection
    from services import mail_agent, operator_auth, shield_runtime
    from api.verify import RateLimiter

    for name, value in {"ASYNC_DATABASE_URL": db_url, "OPERATOR_TOKEN": OP["X-Operator-Token"],
                        "MAIL_POLL_ENABLED": False}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(operator_auth, "failures", RateLimiter(100, noun="failed attempts"))
    monkeypatch.setattr(shield_runtime, "_policy", None)
    monkeypatch.setitem(mail_agent._active, "provider", "auto")
    return monkeypatch


def start():
    import main

    return TestClient(main.app)


def forget_memory(monkeypatch):
    """What a process restart does to the in-memory settings."""
    from services import mail_agent, shield_runtime

    monkeypatch.setattr(shield_runtime, "_policy", None)
    monkeypatch.setitem(mail_agent._active, "provider", "auto")


def test_policy_mode_and_provider_survive_a_restart(app_env):
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "strict"
        r = client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}, headers=OP)
        assert r.status_code == 200 and r.json()["mode"] == "balanced"
        assert client.put("/api/mail/provider", json={"provider": "eml"}, headers=OP).status_code == 200
    forget_memory(app_env)
    with start() as client:
        from services import mail_agent

        assert client.get("/api/policy").json()["mode"] == "balanced"
        assert mail_agent._active["provider"] == "eml"


def test_tightening_also_survives_a_restart(app_env):
    with start() as client:
        client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}, headers=OP)
        assert client.put("/api/policy/mode", json={"mode": "strict"}, headers=OP).json()["mode"] == "strict"
    forget_memory(app_env)
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "strict"


@pytest.mark.parametrize("stored_mode, stored_provider", [("loose", "bogus"), ("", ""), (None, None)])
def test_missing_or_corrupted_rows_fall_back_to_strict_and_auto(app_env, stored_mode, stored_provider):
    from database import connection
    from database.models import RuntimeSetting
    from services import mail_agent

    async def write_rows():
        async with connection.session_factory()() as s:
            for key, value in (("policy_mode", stored_mode), ("mail_provider", stored_provider)):
                if value is not None:
                    row = await s.get(RuntimeSetting, key)
                    if row is None:
                        s.add(RuntimeSetting(key=key, value=value))
                    else:
                        row.value = value
            await s.commit()

    with start() as client:
        client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}, headers=OP)
        if stored_mode is None:  # simulate a lost row
            async def drop():
                async with connection.session_factory()() as s:
                    for key in ("policy_mode", "mail_provider"):
                        row = await s.get(RuntimeSetting, key)
                        if row is not None:
                            await s.delete(row)
                    await s.commit()
            client.portal.call(drop)
        else:
            client.portal.call(write_rows)
    forget_memory(app_env)
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "strict"
        assert mail_agent._active["provider"] == "auto"


def test_loosening_still_needs_confirmation_and_is_audited(app_env):
    from database import connection
    from database.models import AuditLog

    with start() as client:
        refused = client.put("/api/policy/mode", json={"mode": "balanced"}, headers=OP)
        assert refused.status_code == 409
        assert client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}, headers=OP).status_code == 200

        async def changes():
            async with connection.session_factory()() as s:
                return (await s.scalars(select(AuditLog).where(AuditLog.event_type == "policy_changed"))).all()

        [entry] = client.portal.call(changes)
        assert '"new": "balanced"' in entry.payload_json or entry.payload_json.get("new") == "balanced"


def test_a_failed_save_leaves_the_running_mode_unchanged(app_env):
    from services import runtime_settings

    async def broken_save(*args, **kwargs):
        raise RuntimeError("database unavailable")

    with start() as client:
        app_env.setattr(runtime_settings, "save", broken_save)
        r = client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True}, headers=OP)
        assert r.status_code == 503
        assert client.get("/api/policy").json()["mode"] == "strict"
