"""Private-person and self-harm rule (written before the implementation).

All tests go through the HTTP API with a temporary SQLite database, so nothing
touches the configured database or any external service. The person below is fictional.
"""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from loguru import logger

EXPECTED_MESSAGE = (
    "This story involves a private individual. We do not publish verdicts on these. "
    "If you are struggling, contact Tele-MANAS at 14416."
)
SENSITIVE = "19-year-old student Kavya Reddy died by suicide in her hostel room in Kukatpally, Hyderabad"
IDENTIFYING = ["Kavya", "Reddy", "19-year-old", "Kukatpally", "Hyderabad", "hostel"]
PUBLIC_FIGURE = "Union Finance Minister Nirmala Sitharaman said the GST Council will meet next week in New Delhi"

MODEL_TARGETS = [
    "agents.intake_agent.call_nano",
    "agents.source_tracer.call_nano",
    "agents.deep_reasoning.call_ultra",
    "agents.explainer.call_nano",
    "agents.harm_assessor.call_nano",
    "services.input_service.call_vision",
]
SEARCH_TARGETS = [
    "agents.source_tracer.search_gdelt",
    "agents.source_tracer.search_newsapi",
    "agents.source_tracer.search_duckduckgo",
    "agents.source_tracer.search_factchecks",
]


@pytest.fixture
def env(tmp_path, monkeypatch):
    """App on a throwaway SQLite DB, with every search/model client and the dispatcher mocked."""
    from config import settings
    from database import connection
    import main

    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 't.db').as_posix()}")
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)

    mocks = {}
    for target in MODEL_TARGETS + SEARCH_TARGETS:
        m = AsyncMock(side_effect=AssertionError(f"{target} must not be called"))
        monkeypatch.setattr(target, m)
        mocks[target] = m
    dispatched: list[str] = []
    monkeypatch.setattr("api.verify.dispatch", lambda rid: dispatched.append(rid) or "test")

    logs: list[str] = []
    sink = logger.add(lambda msg: logs.append(str(msg)), level="DEBUG")
    with TestClient(main.app) as client:
        yield client, mocks, dispatched, logs
    logger.remove(sink)


def _stored_row(client, request_id: str) -> dict:
    """Read the stored claim straight from the app's database (inside the app's event loop)."""
    from database import connection
    from database.models import Claim

    async def read():
        async with connection.session_factory()() as s:
            c = await s.get(Claim, request_id)
            return {
                "is_public": c.is_public,
                "status": c.status,
                "raw_input": c.raw_input or "",
                "claim_text": c.claim_text or "",
                "normalized_text": c.normalized_text or "",
            }

    return client.portal.call(read)


def _verify(client, text):
    r = client.post("/api/verify", json={"text": text})
    assert r.status_code in (200, 202), r.text
    return r


def test_a_returns_exact_fixed_message_without_identifying_details(env):
    client, *_ = env
    body = _verify(client, SENSITIVE).json()
    assert body.get("message") == EXPECTED_MESSAGE
    text = json.dumps(body)
    for detail in IDENTIFYING:
        assert detail not in text


def test_b_creates_a_private_row(env):
    client, *_ = env
    body = _verify(client, SENSITIVE).json()
    assert _stored_row(client, body["request_id"])["is_public"] is False


def test_c_no_search_or_model_call(env):
    client, mocks, dispatched, _ = env
    _verify(client, SENSITIVE)
    assert dispatched == []
    for target, m in mocks.items():
        assert not m.called, f"{target} was called"


def test_d_identifying_details_absent_from_response_logs_and_storage(env):
    client, _, _, logs = env
    body = _verify(client, SENSITIVE).json()
    row = _stored_row(client, body["request_id"])
    haystacks = {
        "response": json.dumps(body),
        "stored claim_text": row["claim_text"],
        "stored raw_input": row["raw_input"],
        "stored normalized_text": row["normalized_text"],
        "logs": "\n".join(logs),
    }
    for where, text in haystacks.items():
        for detail in IDENTIFYING:
            assert detail not in text, f"{detail!r} found in {where}"


def test_e_public_figure_statement_is_not_triggered(env):
    client, _, dispatched, _ = env
    body = _verify(client, PUBLIC_FIGURE).json()
    assert body.get("message") != EXPECTED_MESSAGE
    assert body["status"] == "queued"
    assert dispatched == [body["request_id"]]
    assert body["registry_url"] is not None
    assert _stored_row(client, body["request_id"])["is_public"] is True


def test_f_record_is_hidden_from_public_pages_registry_and_tracker(env):
    client, *_ = env
    body = _verify(client, SENSITIVE).json()
    slug = body["slug"]
    row = _stored_row(client, body["request_id"])
    assert row["is_public"] is False and row["status"] == "withheld"
    assert client.get(f"/api/v/{slug}").status_code == 404
    assert slug not in {i["slug"] for i in client.get("/api/registry?limit=50").json()["items"]}
    assert slug not in {i["slug"] for i in client.get("/api/history?limit=100").json()["items"]}


# ── Additional coverage added with the implementation ─────────────────────────


def test_trigger_cases():
    from services.safety import check_sensitive

    assert check_sensitive("A man in our colony committed suicide yesterday") == "self_harm"
    assert check_sensitive("छात्रा ने आत्महत्या कर ली") == "self_harm"
    assert check_sensitive("Girl was raped near the bus stand, share") == "sexual_violence"
    assert check_sensitive("21-year-old student died after falling from the college terrace") == "private_individual"
    assert check_sensitive("Rahul Verma was arrested for theft in our area") == "private_individual"
    assert check_sensitive("Chief Minister Ravi Kumar was attacked during a rally") is None  # public role
    assert check_sensitive("RBI will ban all 10 rupee coins from tomorrow") is None


def test_bench_claims_are_not_withheld():
    from pathlib import Path

    from services.safety import check_sensitive

    bench = json.loads((Path(__file__).parent / "bench" / "claims.json").read_text(encoding="utf-8"))["claims"]
    triggered = [c["id"] for c in bench if check_sensitive(c["claim"])]
    assert triggered == []


def test_url_text_is_checked_before_intake_and_search(env, monkeypatch):
    client, mocks, dispatched, logs = env

    async def fake_fetch(url):
        return SENSITIVE

    monkeypatch.setattr("services.input_service.fetch_url_text", fake_fetch)
    body = client.post("/api/verify", json={"url": "https://example.com/story"}).json()
    assert body["status"] == "queued" and dispatched == [body["request_id"]]

    from agents.orchestrator import run_pipeline

    client.portal.call(run_pipeline, body["request_id"])
    row = _stored_row(client, body["request_id"])
    assert row["status"] == "withheld" and row["is_public"] is False
    for target, m in mocks.items():
        assert not m.called, f"{target} was called"
    stored = " ".join([row["raw_input"], row["claim_text"], row["normalized_text"], "\n".join(logs)])
    for detail in IDENTIFYING:
        assert detail not in stored
