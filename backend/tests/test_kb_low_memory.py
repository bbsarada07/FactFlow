"""KB retrieval must not load the embedding model (PyTorch) when it has nothing to search.

On a 512 MB host, importing sentence-transformers kills the process mid-verification.
"""
import asyncio

from config import settings
from database import connection
from shield.kb import retrieve as retrieve_mod


def _fresh_db(db_url, monkeypatch):
    monkeypatch.setattr(settings, "ASYNC_DATABASE_URL", db_url)
    monkeypatch.setattr(connection, "engine", None)
    monkeypatch.setattr(connection, "SessionLocal", None)


def _fail_embed(_text):
    raise AssertionError("embedding model must not be loaded")


def test_empty_kb_does_not_load_model(db_url, monkeypatch):
    _fresh_db(db_url, monkeypatch)
    monkeypatch.setattr(retrieve_mod, "embed_text", _fail_embed)

    async def body():
        await connection.init_db()
        async with connection.session_factory()() as session:
            return await retrieve_mod.retrieve("RBI bans UPI payments above Rs 500", session)

    assert asyncio.run(body()) == []


def test_kb_disabled_skips_retrieval(db_url, monkeypatch):
    _fresh_db(db_url, monkeypatch)
    monkeypatch.setattr(settings, "KB_ENABLED", False)
    monkeypatch.setattr(retrieve_mod, "embed_text", _fail_embed)

    async def body():
        await connection.init_db()
        async with connection.session_factory()() as session:
            return await retrieve_mod.retrieve("any claim", session)

    assert asyncio.run(body()) == []
