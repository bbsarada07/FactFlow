"""/api/accuracy reads the last complete bench run from disk; /health reports providers and key flags."""
import json

import pytest
from fastapi.testclient import TestClient

import main
from config import settings

DUMMY_KEYS = {
    "GROQ_API_KEY": "gsk_HEALTHTESTKEY0000000000000000",
    "GEMINI_API_KEY": "test-gemini-key-not-a-secret",
    "NEWS_API_KEY": "newsapiHEALTHTESTKEY000000",
    "GOOGLE_FACT_CHECK_API_KEY": "test-factcheck-key-not-a-secret",
}


@pytest.fixture
def client():
    return TestClient(main.app)  # no lifespan: the database is not needed for these endpoints


def test_missing_results_file_says_no_complete_run(client, monkeypatch, tmp_path):
    from api import accuracy

    monkeypatch.setattr(accuracy, "RESULTS_PATH", tmp_path / "latest.json")
    r = client.get("/api/accuracy")
    assert r.status_code == 200
    body = r.json()
    assert body["complete"] is False
    assert body["message"] == "No complete run yet"
    assert "counts" not in body and "rows" not in body


def test_unreadable_results_file_is_not_shown_as_a_run(client, monkeypatch, tmp_path):
    from api import accuracy

    path = tmp_path / "latest.json"
    path.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(accuracy, "RESULTS_PATH", path)
    body = client.get("/api/accuracy").json()
    assert body["complete"] is False and body["message"] == "No complete run yet"


def test_results_file_is_reported_as_written(client, monkeypatch, tmp_path):
    from api import accuracy

    run = {
        "run_at": "2026-10-21T09:00:00+00:00",
        "models": {"nano": "model-a", "ultra": "model-b", "vision": "model-c"},
        "counts": {"total": 2, "matches": 1},
        "rows": [
            {"id": "T01", "claim": "c1", "expected": "TRUE", "got": "TRUE"},
            {"id": "F01", "claim": "c2", "expected": "FALSE", "got": "UNVERIFIED"},
        ],
    }
    path = tmp_path / "latest.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(accuracy, "RESULTS_PATH", path)
    body = client.get("/api/accuracy").json()
    assert body["complete"] is True
    assert body["run_at"] == run["run_at"] and body["models"] == run["models"] and body["counts"] == run["counts"]
    assert [r["id"] for r in body["rows"]] == ["T01", "F01"]
    assert [r["id"] for r in body["known_failures"]] == ["F01"]


def test_health_reports_providers_and_key_flags_without_values(client, monkeypatch):
    for name, value in DUMMY_KEYS.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "BUILD_COMMIT", "abc1234")
    r = client.get("/health")
    body = r.json()
    assert body["build_commit"] == "abc1234"
    assert body["reasoning_provider"] == "groq" and body["vision_provider"] == "gemini"
    assert body["keys_configured"] == {"groq": True, "gemini": True, "news_api": True, "google_fact_check": True}
    for value in DUMMY_KEYS.values():
        assert value not in r.text

    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "NEWS_API_KEY", "")
    flags = client.get("/health").json()["keys_configured"]
    assert flags == {"groq": True, "gemini": False, "news_api": False, "google_fact_check": True}


def test_health_never_reports_a_credentialed_url(client, monkeypatch):
    async def down():
        return False

    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", "postgresql+asyncpg://user:SECRETPASS@db.example:5432/x")
    monkeypatch.setattr(settings, "REDIS_URL", "redis://:SECRETPASS@redis.example:6379/0")
    monkeypatch.setattr(main, "redis_ping", down)
    assert "SECRETPASS" not in client.get("/health").text
