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

from standins import OP  # noqa: E402  (import after the line above: it loads the app config)

TEST_PG_URL = os.environ.get("FACTFLOW_TEST_DATABASE_URL", "")


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
    from collections import deque
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
    from services import gmail_account, llm_status, mail_agent, operator_auth, shield_runtime
    from shield.providers.eml import EmlProvider
    from standins import StandIns

    for name, value in {
        "ASYNC_DATABASE_URL": db_url, "OPERATOR_TOKEN": OP["X-Operator-Token"], "APPROVAL_SECRET": "a" * 40,
        "TOKEN_ENCRYPTION_KEY": Fernet.generate_key().decode(), "GOOGLE_CLIENT_ID": "fake-client.apps.example",
        "GOOGLE_CLIENT_SECRET": "FAKE-client-secret", "INBOX_USE_LLM": True, "MAIL_AGENT_MAX_PER_MINUTE": 100,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)
    monkeypatch.setattr(inbox, "limiter", RateLimiter(1000))
    monkeypatch.setattr(mail_api, "callback_limiter", RateLimiter(1000))
    monkeypatch.setattr(operator_auth, "failures", RateLimiter(5, noun="failed attempts"))
    monkeypatch.setattr(shield_runtime, "_policy", None)
    monkeypatch.setitem(mail_agent._active, "provider", "auto")
    monkeypatch.setattr(mail_agent, "_recent", deque())
    monkeypatch.setattr(mail_agent, "_eml", EmlProvider(mail_agent.BASE_DIR / "data" / "demo_emails"))
    monkeypatch.setattr(gmail_account, "states", gmail_account._States())
    llm_status.breaker.reset()
    google = FakeGoogle()
    monkeypatch.setattr(gmail_account, "HTTP_TRANSPORT", google.transport)
    models = StandIns()
    models.install(monkeypatch)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, google=google, models=models, settings=settings)
    llm_status.breaker.reset()
