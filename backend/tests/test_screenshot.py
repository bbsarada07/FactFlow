"""Screenshot pipeline: PNG/JPG up to 5 MB, clear rejections, and "No text found" without reasoning.

Written before the implementation. Uses a throwaway SQLite database; no network.
"""
import base64
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from config import settings

CLEAR_MESSAGE = "Only PNG or JPG screenshots up to 5 MB are supported."


def image_b64(fmt="PNG") -> str:
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), "white").save(buf, fmt)
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def env(tmp_path, monkeypatch):
    from database import connection
    import main

    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", f"sqlite+aiosqlite:///{(tmp_path / 's.db').as_posix()}")
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    dispatched: list[str] = []
    from api.verify import RateLimiter

    monkeypatch.setattr("api.verify.limiter", RateLimiter(1000))
    monkeypatch.setattr("api.verify.dispatch", lambda rid: dispatched.append(rid) or "test")
    reasoning = {}
    for target in ("agents.intake_agent.call_nano", "agents.source_tracer.call_nano", "agents.deep_reasoning.call_ultra",
                   "agents.explainer.call_nano", "agents.harm_assessor.call_nano"):
        m = AsyncMock(side_effect=AssertionError(f"{target} must not be called"))
        monkeypatch.setattr(target, m)
        reasoning[target] = m
    with TestClient(main.app) as client:
        yield client, dispatched, reasoning


def test_oversized_image_is_rejected(env):
    client, dispatched, _ = env
    big = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024)).decode()
    r = client.post("/api/verify", json={"image_base64": "data:image/png;base64," + big})
    assert r.status_code == 422
    assert CLEAR_MESSAGE in r.text
    assert dispatched == []


def test_non_image_is_rejected(env):
    client, dispatched, _ = env
    fake_png = base64.b64encode(b"this is plain text, not an image at all").decode()
    r = client.post("/api/verify", json={"image_base64": "data:image/png;base64," + fake_png})
    assert r.status_code == 422 and CLEAR_MESSAGE in r.text
    gif = base64.b64encode(b"GIF89a" + b"0" * 50).decode()
    r = client.post("/api/verify", json={"image_base64": "data:image/gif;base64," + gif})
    assert r.status_code == 422 and CLEAR_MESSAGE in r.text
    assert dispatched == []


def test_png_and_jpg_are_accepted(env):
    client, dispatched, _ = env
    for fmt, mime in (("PNG", "image/png"), ("JPEG", "image/jpeg")):
        r = client.post("/api/verify", json={"image_base64": f"data:{mime};base64," + image_b64(fmt)})
        assert r.status_code == 202, r.text
    assert len(dispatched) == 2


def test_no_readable_text_shows_no_text_found_without_reasoning(env, monkeypatch):
    client, dispatched, reasoning = env
    import models.gemini_client as gc
    from services import input_service

    monkeypatch.setattr(settings, "VISION_PROVIDER", "gemini")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key-not-a-secret")

    class Blank:
        async def generate_content(self, **kwargs):
            return SimpleNamespace(text="TEXT:\n\nCUES:\n- none", usage_metadata=None)

    monkeypatch.setattr(gc, "_client", lambda: SimpleNamespace(aio=SimpleNamespace(models=Blank())))
    monkeypatch.setattr(input_service, "_tesseract_available", lambda: True)
    monkeypatch.setattr(input_service, "_ocr_sync", lambda b64: "")

    r = client.post("/api/verify", json={"image_base64": "data:image/png;base64," + image_b64()})
    assert r.status_code == 202, r.text
    body = r.json()
    from agents.orchestrator import run_pipeline

    client.portal.call(run_pipeline, body["request_id"])
    result = client.get(f"/api/result/{body['request_id']}").json()
    assert result["status"] == "failed"
    assert "No text found" in result["error"]
    for target, m in reasoning.items():
        assert not m.called, f"{target} was called"
