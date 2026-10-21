"""Split provider routing: Groq makes every verdict; Gemma 4 only reads screenshots.

Written before the implementation. No network: Gemma, Groq and search are faked, and the app
runs on a throwaway SQLite database. The key below is a dummy.
"""
import asyncio
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from loguru import logger
from PIL import Image

from config import settings

DUMMY_KEY = "test-key-not-a-secret"
GEMMA_SAYS = {
    "text": "RBI will ban all 10 rupee coins from tomorrow",
    "cues": ["no source named", "caption says share now"],
    "verdict": "FALSE",
    "confidence": 0.99,
    "correction": "GEMMA WROTE THIS CORRECTION",
}


def png_b64() -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, "PNG")
    return base64.b64encode(buf.getvalue()).decode()


class FakeModels:
    def __init__(self, text=None, error=None):
        self.calls, self.text, self.error = [], text, error

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, usage_metadata=None)


def install_gemma(monkeypatch, fake, key=DUMMY_KEY):
    import models.gemini_client as gc

    monkeypatch.setattr(settings, "GEMINI_API_KEY", key)
    monkeypatch.setattr(gc, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=fake)))


# ── a. Reasoning always on Groq ───────────────────────────────────────────────


def test_a_reasoning_uses_groq_even_when_gemini_key_is_set(monkeypatch):
    from agents import deep_reasoning
    from models.groq_client import LLMResult

    fake = FakeModels(error=AssertionError("Gemma must not be called for reasoning"))
    install_gemma(monkeypatch, fake)
    monkeypatch.setattr(settings, "REASONING_PROVIDER", "groq")
    called = []

    async def ultra(system, user, **k):
        called.append(True)
        return LLMResult(data={"verdict": "FALSE", "confidence": 0.9, "reasoning_chain": [], "summary": "",
                               "contradictions_found": [], "missing_context": []},
                         model=settings.ULTRA_MODEL, ms=1, tokens=1)

    monkeypatch.setattr(deep_reasoning, "call_ultra", ultra)
    from agents.context import PipelineContext

    ctx = PipelineContext(request_id="x", raw_text="r")
    ctx.claim, ctx.verdict, ctx.confidence = "c", "FALSE", 0.5
    out = asyncio.run(deep_reasoning.run(ctx))
    assert called and out.model == settings.ULTRA_MODEL and not fake.calls


def test_a_reasoning_provider_cannot_be_gemini():
    from pydantic import ValidationError

    from config import Settings

    with pytest.raises(ValidationError):
        Settings(REASONING_PROVIDER="gemini")


# ── b. The vision model never produces a verdict ──────────────────────────────


def test_b_vision_verdict_fields_are_ignored(monkeypatch):
    from services import input_service

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    install_gemma(monkeypatch, FakeModels(text=json.dumps(GEMMA_SAYS)))
    read = asyncio.run(input_service.read_image(png_b64(), "image/png"))
    assert read.text == GEMMA_SAYS["text"]
    assert read.cues == GEMMA_SAYS["cues"]
    assert read.reader == "gemma"
    for leaked in ("FALSE", "0.99", "GEMMA WROTE THIS CORRECTION", "verdict", "confidence"):
        assert leaked not in read.text and all(leaked not in c for c in read.cues)


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """App on a throwaway SQLite DB with Groq intake/harm faked and no search results."""
    from database import connection
    import main
    from models.groq_client import LLMResult

    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 'r.db').as_posix()}")
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    monkeypatch.setattr("api.verify.dispatch", lambda rid: "test")

    prompts: list[str] = []

    async def intake(system, user, **k):
        prompts.append(user)
        return LLMResult(data={"claim": "RBI will ban 10 rupee coins", "language": "en", "claim_type": "FINANCIAL",
                               "urgency": "MEDIUM", "search_queries": ["rbi 10 rupee coin ban fact check"]},
                         model=settings.NANO_MODEL, ms=1, tokens=1)

    async def harm(system, user, **k):
        prompts.append(user)
        return LLMResult(data={"harm_type": "FINANCIAL", "harm_level": "LOW", "severity": 2, "rationale": "r"},
                         model=settings.NANO_MODEL, ms=1, tokens=1)

    monkeypatch.setattr("agents.intake_agent.call_nano", intake)
    monkeypatch.setattr("agents.harm_assessor.call_nano", harm)
    for target in ("search_gdelt", "search_newsapi", "search_duckduckgo", "search_factchecks"):
        monkeypatch.setattr(f"agents.source_tracer.{target}", AsyncMock(return_value=[]))
    with TestClient(main.app) as client:
        yield client, prompts


def _row(client, rid):
    from database import connection
    from database.models import Claim

    async def read():
        async with connection.session_factory()() as s:
            c = await s.get(Claim, rid)
            return {"verdict": c.verdict, "confidence": c.confidence, "correction": c.correction,
                    "image_info": c.image_info, "status": c.status}

    return client.portal.call(read)


def test_b_pipeline_verdict_comes_from_reasoning_not_vision(app_env, monkeypatch):
    client, prompts = app_env
    install_gemma(monkeypatch, FakeModels(text=json.dumps(GEMMA_SAYS)))
    from agents.orchestrator import run_pipeline

    body = client.post("/api/verify", json={"image_base64": "data:image/png;base64," + png_b64()}).json()
    client.portal.call(run_pipeline, body["request_id"])
    row = _row(client, body["request_id"])
    assert row["status"] == "complete"
    assert row["verdict"] == "UNVERIFIED"  # no evidence -> gate, not Gemma's "FALSE"
    assert row["confidence"] != 0.99
    assert "GEMMA WROTE THIS CORRECTION" not in json.dumps(row["correction"])
    assert row["image_info"]["reader"] == "gemma"
    assert row["image_info"]["cues"] == GEMMA_SAYS["cues"]
    # Cues are shown to the user but never sent to a reasoning model.
    assert prompts and all("caption says share now" not in p for p in prompts)


# ── c. The key never leaks ────────────────────────────────────────────────────


def test_c_key_never_in_logs_or_exceptions(monkeypatch):
    from models.gemini_client import read_screenshot

    install_gemma(monkeypatch, FakeModels(error=RuntimeError(f"400 API key not valid: {DUMMY_KEY}")))
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        with pytest.raises(Exception) as exc:
            asyncio.run(read_screenshot(png_b64(), "image/png"))
    finally:
        logger.remove(sink)
    assert DUMMY_KEY not in str(exc.value) and DUMMY_KEY not in repr(exc.value)
    assert DUMMY_KEY not in "\n".join(logs)


# ── Vision unavailable -> Tesseract, labelled ─────────────────────────────────


def test_vision_unavailable_uses_tesseract_and_says_so(monkeypatch):
    from services import input_service

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(input_service, "_tesseract_available", lambda: True)
    monkeypatch.setattr(input_service, "_ocr_sync", lambda b64: "RBI will ban all 10 rupee coins from tomorrow")
    read = asyncio.run(input_service.read_image(png_b64(), "image/png"))
    assert read.reader == "tesseract" and read.label == "Image read without AI" and read.cues == []
