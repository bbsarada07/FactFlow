"""/health reports the build commit and a plain Redis status."""
import pytest
from fastapi.testclient import TestClient

import main
from config import settings


@pytest.fixture
def client():
    return TestClient(main.app)  # no lifespan: the database is not needed for these fields


def test_health_has_build_commit(client, monkeypatch):
    monkeypatch.setattr(settings, "BUILD_COMMIT", "91b4198")
    body = client.get("/health").json()
    assert body["build_commit"] == "91b4198"


def test_health_build_commit_says_when_unset(client, monkeypatch):
    monkeypatch.setattr(settings, "BUILD_COMMIT", "")
    assert "not set" in client.get("/health").json()["build_commit"]


def test_health_says_plainly_when_redis_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(main, "redis_configured", lambda: False)
    redis = client.get("/health").json()["redis"]
    assert redis["configured"] is False and redis["reachable"] is False
    assert "not configured" in redis["status"] and "runs without Redis" in redis["status"]


def test_health_reports_unreachable_redis(client, monkeypatch):
    async def down():
        return False

    monkeypatch.setattr(main, "redis_configured", lambda: True)
    monkeypatch.setattr(main, "redis_ping", down)
    redis = client.get("/health").json()["redis"]
    assert redis["configured"] is True and redis["reachable"] is False
    assert "unreachable" in redis["status"]
