"""A repeat of a claim reuses an earlier definite verdict, but an earlier UNVERIFIED is checked again: it usually
meant evidence was missing then (a search provider down, a story not yet covered)."""
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

CLAIM = "India won the ICC Men's T20 World Cup in 2024."


@pytest.fixture
def client(tmp_path, monkeypatch):
    from config import settings
    from database import connection
    import main

    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    for target in ("agents.intake_agent.call_nano", "agents.source_tracer.call_nano"):
        monkeypatch.setattr(target, AsyncMock(side_effect=AssertionError("no pipeline runs in this test")))
    monkeypatch.setattr("api.verify.dispatch", lambda rid: "test")
    from api import verify as verify_api
    from api.verify import RateLimiter

    monkeypatch.setattr(verify_api, "limiter", RateLimiter(1000))  # its own budget: shared checks/minute stay intact
    with TestClient(main.app) as c:
        yield c


def _finish(client, request_id: str, verdict: str) -> None:
    from database import connection
    from database.models import Claim

    async def done():
        async with connection.session_factory()() as s:
            c = await s.get(Claim, request_id)
            c.status, c.verdict = "complete", verdict
            await s.commit()

    client.portal.call(done)


def test_an_unverified_claim_is_checked_again_and_a_definite_verdict_is_reused(client):
    first = client.post("/api/verify", json={"text": CLAIM})
    assert first.status_code == 202 and first.json()["cached"] is False
    _finish(client, first.json()["request_id"], "UNVERIFIED")

    again = client.post("/api/verify", json={"text": CLAIM})
    assert again.status_code == 202 and again.json()["cached"] is False  # a fresh check, not the old UNVERIFIED
    assert again.json()["request_id"] != first.json()["request_id"]
    _finish(client, again.json()["request_id"], "TRUE")

    third = client.post("/api/verify", json={"text": CLAIM})
    assert third.status_code == 200 and third.json()["cached"] is True
    assert third.json()["request_id"] == again.json()["request_id"]  # the TRUE verdict is reused
