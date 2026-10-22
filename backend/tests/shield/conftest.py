"""Helpers for Shield tests that need a database: a fresh SQLite file per test, all inside one event loop."""
import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.models import Base


@pytest.fixture
def with_db(tmp_path):
    """Call with an async function taking a session factory; runs it against a new SQLite database."""

    def run(fn):
        async def main():
            engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'shield.db').as_posix()}")
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                return await fn(async_sessionmaker(engine, expire_on_commit=False))
            finally:
                await engine.dispose()

        return asyncio.run(main())

    return run
