"""Make the backend package importable from tests (run `pytest` inside backend/).

Database tests use a throwaway SQLite file by default. To run them on PostgreSQL instead, point
FACTFLOW_TEST_DATABASE_URL at a dedicated, disposable test database, e.g.
    postgresql+asyncpg://postgres:<password>@localhost:5432/factflow_test
Its tables are dropped and recreated before every test, so never point it at real data.
"""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ["MAIL_POLL_ENABLED"] = "false"  # no background Gmail poller during tests
# Never let a test reach the developer's real database from backend/.env: anything that does not set its own
# database (db_url, mail_env) lands in a throwaway SQLite file instead.
import tempfile  # noqa: E402

os.environ["ASYNC_DATABASE_URL"] = "sqlite+aiosqlite:///" + (Path(tempfile.gettempdir()) / "factflow-tests-default.db").as_posix()

from standins import OP, TEST_USER_EMAIL, TEST_USER_ID  # noqa: E402,F401  (after the line above: loads app config)

TEST_PG_URL = os.environ.get("FACTFLOW_TEST_DATABASE_URL", "")


def pytest_configure(config):
    config.addinivalue_line("markers", "real_auth: run with real sign-in checks (no default signed-in test user)")


async def ensure_user(user_id: str, email: str, role: str = "user") -> None:
    """Create the users row for a test identity if it is missing (owner columns and settings refer to it)."""
    from sqlalchemy import select

    from database import connection
    from database.models import User

    if connection.SessionLocal is None:  # app started without a database (validation-only tests)
        return
    async with connection.session_factory()() as s:
        if await s.get(User, user_id) is None and await s.scalar(select(User.id).where(User.email == email)) is None:
            s.add(User(id=user_id, google_sub=f"sub-{user_id}", email=email, role=role))
            await s.commit()


@pytest.fixture(autouse=True)
def no_live_news_search(monkeypatch):
    """The Source Tracer's Bing News and Google News searches find nothing unless a test sets them, so no test
    reaches the internet (the older providers are stubbed by the tests that use them)."""
    from unittest.mock import AsyncMock

    for name in ("search_bing_news", "search_google_news"):
        monkeypatch.setattr(f"agents.source_tracer.{name}", AsyncMock(return_value=[]))


@pytest.fixture(autouse=True)
def signed_in(request, monkeypatch):
    """Every API test runs as one signed-in test user (an admin), unless marked `real_auth`. Features are tested
    as that user; sign-in, CSRF and isolation between users are tested with real_auth (tests/test_accounts.py)."""
    if request.node.get_closest_marker("real_auth"):
        yield None
        return
    import main
    from services import auth

    user = auth.CurrentUser(id=TEST_USER_ID, email=TEST_USER_EMAIL, name="Tester", role="admin", via="session",
                            session_id=None, csrf_token="test-csrf")

    async def as_test_user():
        await ensure_user(user.id, user.email, "admin")
        return user

    async def optional_test_user(_request):
        return await as_test_user()

    for dep in (auth.current_user, auth.session_user, auth.require_admin):
        main.app.dependency_overrides[dep] = as_test_user
    monkeypatch.setattr(auth, "optional_user", optional_test_user)
    yield user
    for dep in (auth.current_user, auth.session_user, auth.require_admin):
        main.app.dependency_overrides.pop(dep, None)


def _reset_postgres(url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from database.models import Base

    async def reset():
        engine = create_async_engine(url, poolclass=NullPool)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
        finally:
            await engine.dispose()

    asyncio.run(reset())


@pytest.fixture
def db_url(tmp_path) -> str:
    """Database URL for one test: a fresh SQLite file, or the reset PostgreSQL test database."""
    if TEST_PG_URL:
        _reset_postgres(TEST_PG_URL)
        return TEST_PG_URL
    return f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"



@pytest.fixture
def mail_env(db_url, monkeypatch):
    """The app with the mail agent wired to a fake Google (recorded Gmail fixtures), stand-in
    models, a fresh database and fresh limits. Yields an object with client, google, models."""
    from types import SimpleNamespace

    from cryptography.fernet import Fernet
    from fastapi.testclient import TestClient

    import main
    from api import inbox
    from api import mail as mail_api
    from api.verify import RateLimiter
    from config import settings
    from database import connection
    from gmail_fake import FakeGoogle
    from services import gmail_account, llm_status, mail_agent, shield_runtime
    from standins import StandIns

    for name, value in {
        "ASYNC_DATABASE_URL": db_url, "APPROVAL_SECRET": "a" * 40,
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(), "GOOGLE_CLIENT_ID": "fake-client.apps.example",
        "GOOGLE_CLIENT_SECRET": "FAKE-client-secret", "INBOX_USE_LLM": True, "MAIL_AGENT_MAX_PER_MINUTE": 100,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(inbox, "limiter", RateLimiter(1000))
    monkeypatch.setattr(mail_api, "callback_limiter", RateLimiter(1000))
    monkeypatch.setattr(shield_runtime, "_policy", None)
    monkeypatch.setattr(mail_agent, "_recent", {})
    monkeypatch.setattr(mail_agent, "_eml", {})
    monkeypatch.setattr(gmail_account, "states", gmail_account._States())
    llm_status.breaker.reset()
    google = FakeGoogle()
    monkeypatch.setattr(gmail_account, "HTTP_TRANSPORT", google.transport)
    models = StandIns()
    models.install(monkeypatch)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, google=google, models=models, settings=settings, user_id=TEST_USER_ID)
    llm_status.breaker.reset()
