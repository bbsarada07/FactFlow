"""Gemma 4 via the Gemini API: screenshot reading only (updated for split provider routing).

No network: the google-genai client is replaced with a fake. The key used here is a dummy.
"""
import asyncio
import base64
import json
from types import SimpleNamespace

import pytest
from loguru import logger

from config import settings

DUMMY_KEY = "test-key-not-a-secret"
REASONING_JSON = {
    "sub_claims": [{"text": "Schools closed on 25 September", "assessment": "supported"}],
    "reasoning_chain": ["Times of India reports the 25 September holiday [S1]."],
    "contradictions_found": [],
    "missing_context": [],
    "evidence_gaps": [],
    "manipulation_markers": [],
    "verdict": "TRUE",
    "confidence": 0.9,
    "summary": "Times of India reported the closure [S1].",
    "fact": "Schools were closed on 25 September [S1].",
    "key_source": "Times of India",
}


class FakeModels:
    """Stands in for client.aio.models; records calls and returns or raises as configured."""

    def __init__(self, text=None, error=None):
        self.calls = []
        self.text, self.error = text, error

    async def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return SimpleNamespace(text=self.text, usage_metadata=None)


def install_fake(monkeypatch, fake):
    import models.gemini_client as gc

    monkeypatch.setattr(settings, "GEMINI_API_KEY", DUMMY_KEY)
    monkeypatch.setattr(gc, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=fake)))


def test_client_sends_gemma_model(monkeypatch):
    from models.gemini_client import read_screenshot

    fake = FakeModels(text="TEXT:\nRBI will ban 10 rupee coins\nCUES:\n- no source named")
    install_fake(monkeypatch, fake)
    result = asyncio.run(read_screenshot(PNG, "image/png"))
    assert fake.calls[0]["model"] == settings.GEMMA_MODEL
    assert result.text == "RBI will ban 10 rupee coins" and result.cues == ["no source named"]


def test_key_never_appears_in_exceptions_or_logs(monkeypatch):
    from models.gemini_client import read_screenshot

    fake = FakeModels(error=RuntimeError(f"400 API key not valid: key={DUMMY_KEY}"))
    install_fake(monkeypatch, fake)
    logs: list[str] = []
    sink = logger.add(lambda m: logs.append(str(m)), level="DEBUG")
    try:
        with pytest.raises(Exception) as exc:
            asyncio.run(read_screenshot(PNG, "image/png"))
    finally:
        logger.remove(sink)
    assert DUMMY_KEY not in str(exc.value) and DUMMY_KEY not in repr(exc.value)
    assert exc.value.__cause__ is None or DUMMY_KEY not in str(exc.value.__cause__)
    assert DUMMY_KEY not in "\n".join(logs)


def test_vision_uses_gemma_only_when_provider_gemini_and_key_set(monkeypatch):
    from models.gemini_client import vision_available

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert vision_available() is False
    monkeypatch.setattr(settings, "GEMINI_API_KEY", DUMMY_KEY)
    assert vision_available() is True
    monkeypatch.setattr(settings, "VISION_PROVIDER", "none")
    assert vision_available() is False


def _ctx():
    from agents.context import PipelineContext

    ctx = PipelineContext(request_id="x", raw_text="Schools were closed for Ganesh immersion")
    ctx.claim, ctx.verdict, ctx.confidence = "Schools were closed for Ganesh immersion", "TRUE", 0.7
    ctx.evidence = [
        {"name": "Times of India", "url": "https://timesofindia.indiatimes.com/x", "tier": 2, "ref": "S1",
         "origin": "gdelt", "stance": "SUPPORTS", "credibility": 0.8},
        {"name": "Siasat", "url": "https://www.siasat.com/x", "tier": 2, "ref": "S2",
         "origin": "duckduckgo", "stance": "SUPPORTS", "credibility": 0.8},
    ]
    return ctx


def test_deep_reasoning_never_uses_gemma(monkeypatch):
    """Split routing: verdicts come only from Groq, even with a Gemini key and VISION_PROVIDER=gemini."""
    from agents import deep_reasoning
    from agents.orchestrator import decide_verdict
    from models.groq_client import LLMResult

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    fake = FakeModels(error=AssertionError("Gemma called for reasoning"))
    install_fake(monkeypatch, fake)

    async def ultra(system, user, **k):
        return LLMResult(data=REASONING_JSON, model=settings.ULTRA_MODEL, ms=1, tokens=1)

    monkeypatch.setattr(deep_reasoning, "call_ultra", ultra)
    ctx = _ctx()
    out = asyncio.run(deep_reasoning.run(ctx))
    assert out.model == settings.ULTRA_MODEL and not fake.calls
    decision = decide_verdict(ctx.evidence, {
        "verdict": ctx.verdict, "confidence": ctx.confidence,
        "contradictions_found": ctx.contradictions, "missing_context": ctx.missing_context,
    })
    assert decision["verdict"] == "TRUE"


def test_groq_path_unchanged_when_provider_groq(monkeypatch):
    from agents import deep_reasoning
    from models.groq_client import LLMResult

    fake = FakeModels(error=AssertionError("Gemma called while provider is groq"))
    install_fake(monkeypatch, fake)

    async def ultra(system, user, **k):
        return LLMResult(data=REASONING_JSON, model=settings.ULTRA_MODEL, ms=1, tokens=1)

    monkeypatch.setattr(deep_reasoning, "call_ultra", ultra)
    out = asyncio.run(deep_reasoning.run(_ctx()))
    assert out.model == settings.ULTRA_MODEL and not fake.calls


PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * 100).decode()


def test_screenshot_goes_to_gemma_first(monkeypatch):
    from services import input_service

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    fake = FakeModels(text="RBI will ban all 10 rupee coins from tomorrow")
    install_fake(monkeypatch, fake)
    monkeypatch.setattr(input_service, "_ocr_sync", lambda b64: (_ for _ in ()).throw(AssertionError("tesseract first")))
    text, method = asyncio.run(input_service.image_to_text(PNG, "image/png"))
    assert method == "gemma" and "10 rupee coins" in text
    assert fake.calls[0]["model"] == settings.GEMMA_MODEL


def test_screenshot_falls_back_to_tesseract_when_gemma_fails(monkeypatch):
    from services import input_service

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    install_fake(monkeypatch, FakeModels(error=RuntimeError("503 UNAVAILABLE")))
    monkeypatch.setattr(input_service, "_tesseract_available", lambda: True)
    monkeypatch.setattr(input_service, "_ocr_sync", lambda b64: "RBI will ban all 10 rupee coins from tomorrow")
    text, method = asyncio.run(input_service.image_to_text(PNG, "image/png"))
    assert method == "tesseract"


def test_screenshot_over_5mb_or_wrong_type_skips_gemma(monkeypatch):
    from services import input_service

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    fake = FakeModels(text="should not be used")
    install_fake(monkeypatch, fake)
    monkeypatch.setattr(input_service, "_tesseract_available", lambda: True)
    monkeypatch.setattr(input_service, "_ocr_sync", lambda b64: "text read by tesseract for this image")
    big = base64.b64encode(b"0" * (5 * 1024 * 1024 + 10)).decode()
    _, method = asyncio.run(input_service.image_to_text(big, "image/png"))
    assert method == "tesseract"
    _, method = asyncio.run(input_service.image_to_text(PNG, "image/gif"))
    assert method == "tesseract"
    assert not fake.calls


def test_public_config_and_health_name_the_model_in_use(monkeypatch):
    from fastapi.testclient import TestClient

    import main

    client = TestClient(main.app)
    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", DUMMY_KEY)
    cfg = client.get("/api/config").json()
    assert cfg["models"]["ultra"] == settings.ULTRA_MODEL
    assert cfg["vision"] == {"model": settings.GEMMA_MODEL, "provider": "Gemini API"}
    health = client.get("/health").json()
    assert health["reasoning_provider"] == "groq" and health["models"]["reasoning"] == settings.ULTRA_MODEL
    assert health["models"]["vision"] == settings.GEMMA_MODEL
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert client.get("/api/config").json()["vision"] is None
