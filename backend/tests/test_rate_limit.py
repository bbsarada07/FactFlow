"""Rate limiting and input-size limits on POST /api/verify."""
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from api.verify import RateLimiter
from config import settings


class FakeClock:
    """Controllable monotonic clock."""

    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def test_tenth_request_allowed_eleventh_blocked():
    clock = FakeClock()
    rl = RateLimiter(10, clock=clock)
    for _ in range(10):
        rl.check("1.2.3.4")
    with pytest.raises(HTTPException) as exc:
        rl.check("1.2.3.4")
    assert exc.value.status_code == 429
    assert int(exc.value.headers["Retry-After"]) > 0


def test_window_slides_after_a_minute():
    clock = FakeClock()
    rl = RateLimiter(10, clock=clock)
    for _ in range(10):
        rl.check("ip")
    clock.t += 60
    rl.check("ip")  # does not raise


def test_limits_are_per_client():
    rl = RateLimiter(10, clock=FakeClock())
    for _ in range(10):
        rl.check("a")
    rl.check("b")  # another client is unaffected


@pytest.fixture
def client():
    """App client with the database dependency stubbed out (validation runs before any DB use)."""
    from database.connection import get_session
    from main import app

    async def no_db():
        yield None

    app.dependency_overrides[get_session] = no_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_overlong_claim_rejected_with_422(client):
    r = client.post("/api/verify", json={"text": "x" * (settings.MAX_CLAIM_CHARS + 1)})
    assert r.status_code == 422


def test_invalid_visibility_rejected_with_422(client):
    r = client.post("/api/verify", json={"text": "a valid looking claim", "visibility": "secret"})
    assert r.status_code == 422
