"""Async engine/session management with an automatic SQLite fallback for local dev."""
from collections.abc import AsyncIterator

from loguru import logger
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import BASE_DIR, settings
from database.models import Base

SQLITE_URL = f"sqlite+aiosqlite:///{(BASE_DIR / 'nemesisai.db').as_posix()}"

engine: AsyncEngine | None = None
SessionLocal: async_sessionmaker[AsyncSession] | None = None
active_url: str = ""


def _make_engine(url: str, null_pool: bool) -> AsyncEngine:
    kwargs: dict = {"pool_pre_ping": True}
    if null_pool:
        kwargs["poolclass"] = NullPool
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"timeout": 30}}
        if null_pool:
            kwargs["poolclass"] = NullPool
    return create_async_engine(url, **kwargs)


async def init_db(null_pool: bool = False) -> str:
    """Connect, create tables and seed. Returns the dialect actually in use."""
    global engine, SessionLocal, active_url
    if engine is not None:
        return engine.dialect.name

    url = settings.ASYNC_DATABASE_URL
    candidate = _make_engine(url, null_pool)
    try:
        async with candidate.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - any connection failure triggers fallback
        await candidate.dispose()
        if not settings.SQLITE_FALLBACK or url.startswith("sqlite"):
            raise
        logger.warning(f"Database at {url.split('@')[-1]} unreachable ({exc!r}); falling back to SQLite")
        url = SQLITE_URL
        candidate = _make_engine(url, null_pool)

    engine = candidate
    active_url = url
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from database.seed_data import seed

    async with SessionLocal() as session:
        await seed(session)

    logger.info(f"Database ready ({engine.dialect.name})")
    return engine.dialect.name


async def close_db() -> None:
    global engine, SessionLocal
    if engine is not None:
        await engine.dispose()
    engine = None
    SessionLocal = None


def session_factory() -> async_sessionmaker[AsyncSession]:
    if SessionLocal is None:
        raise RuntimeError("Database not initialised; call init_db() first")
    return SessionLocal


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with session_factory()() as session:
        yield session
