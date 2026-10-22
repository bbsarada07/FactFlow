"""Helpers for Shield tests that need a database: a fresh database per test (SQLite, or PostgreSQL
when FACTFLOW_TEST_DATABASE_URL is set; see tests/conftest.py), all inside one event loop."""
import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database.models import Base


@pytest.fixture
def with_db(db_url):
    """Call with an async function taking a session factory; runs it against a new database."""

    def run(fn):
        async def main():
            engine = create_async_engine(db_url, poolclass=NullPool)
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                return await fn(async_sessionmaker(engine, expire_on_commit=False))
            finally:
                await engine.dispose()

        return asyncio.run(main())

    return run
