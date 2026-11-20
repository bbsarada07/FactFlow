"""Each user's policy mode and mail provider survive a backend restart, and nothing can loosen them by accident."""
import pytest
from fastapi.testclient import TestClient

from standins import TEST_USER_ID


@pytest.fixture
def app_env(db_url, monkeypatch):
    """Settings for starting the real app (lifespan included) more than once on the same database."""
    import main  # noqa: F401  (imported so the routers exist)
    from config import settings
    from database import connection
    from services import shield_runtime

    for name, value in {"ASYNC_DATABASE_URL": db_url, "MAIL_POLL_ENABLED": False}.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(shield_runtime, "_policy", None)
    return monkeypatch


def start():
    import main

    return TestClient(main.app)


def restart(monkeypatch):
    """What a process restart does: a new engine and no in-memory policy."""
    from database import connection
    from services import shield_runtime

    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(shield_runtime, "_policy", None)


def test_policy_mode_and_provider_survive_a_restart(app_env):
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "strict"
        r = client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True})
        assert r.status_code == 200 and r.json()["mode"] == "balanced"
        assert client.put("/api/mail/provider", json={"provider": "eml"}).status_code == 200
    restart(app_env)
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "balanced"
        assert client.get("/api/mail/status").json()["provider_setting"] == "eml"


def test_tightening_also_survives_a_restart(app_env):
    with start() as client:
        client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True})
        assert client.put("/api/policy/mode", json={"mode": "strict"}).json()["mode"] == "strict"
    restart(app_env)
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "strict"


@pytest.mark.parametrize("stored_mode, stored_provider", [("loose", "bogus"), ("", ""), (None, None)])
def test_missing_or_corrupted_rows_fall_back_to_strict_and_auto(app_env, stored_mode, stored_provider):
    from database import connection
    from database.models import UserSettings

    async def write_row():
        async with connection.session_factory()() as s:
            if stored_mode is None:
                return
            s.add(UserSettings(user_id=TEST_USER_ID, policy_mode=stored_mode, mail_provider=stored_provider))
            await s.commit()

    with start() as client:
        client.get("/api/policy")  # creates the test user
        client.portal.call(write_row)
        assert client.get("/api/policy").json()["mode"] == "strict"
        status = client.get("/api/mail/status").json()
        assert status["provider_setting"] == "auto"


def test_loosening_still_needs_confirmation_and_is_audited(app_env):
    with start() as client:
        assert client.put("/api/policy/mode", json={"mode": "balanced"}).status_code == 409
        assert client.get("/api/policy").json()["mode"] == "strict"
        assert client.put("/api/policy/allowed-domains", json={"domains": ["new.example"]}).status_code == 409
        client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True})
        events = [i["event_type"] for i in client.get("/api/audit?limit=200").json()["items"]]
        assert events.count("policy_changed") == 1


def test_a_failed_save_leaves_the_mode_unchanged(app_env):
    from services import runtime_settings

    async def broken_save(*_a, **_k):
        raise RuntimeError("database is down")

    real_save = runtime_settings._save
    with start() as client:
        runtime_settings._save = broken_save
        try:
            with pytest.raises(RuntimeError):
                client.put("/api/policy/mode", json={"mode": "balanced", "confirm": True})
        finally:
            runtime_settings._save = real_save
    restart(app_env)
    with start() as client:
        assert client.get("/api/policy").json()["mode"] == "strict"
