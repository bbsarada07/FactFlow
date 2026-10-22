"""Async engine/session management with an automatic SQLite fallback for local dev."""
from collections.abc import AsyncIterator

from loguru import logger
from sqlalchemy import inspect, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from config import BASE_DIR, settings
from database.models import Base

SQLITE_URL = f"sqlite+aiosqlite:///{(BASE_DIR / 'factflow.db').as_posix()}"

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
        await conn.run_sync(_add_missing_columns)

    from database.seed_data import seed

    async with SessionLocal() as session:
        await _backfill(session)
        await seed(session)

    logger.info(f"Database ready ({engine.dialect.name})")
    return engine.dialect.name


# Server-side defaults for columns added to existing tables (NOT NULL-safe for old rows).
_ADDED_DEFAULTS = {
    "is_public": "TRUE",
    "view_count": "0",
    "repeat_count": "0",
    "version": "1",
    "source_confirmed": "FALSE",
}
_INDEXES = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ix_claims_slug ON claims (slug)",
    "CREATE INDEX IF NOT EXISTS ix_claims_is_public ON claims (is_public)",
)


def _add_missing_columns(sync_conn) -> None:
    """Lightweight forward-only migration: add model columns that an existing table lacks.

    create_all() only creates missing tables, so databases created by v1 need the v2
    registry/uncertainty columns added in place. Idempotent; safe to run on every start.
    """
    insp = inspect(sync_conn)
    dialect = sync_conn.dialect
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        existing = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in existing:
                continue
            ddl_type = col.type.compile(dialect=dialect)
            default = _ADDED_DEFAULTS.get(col.name)
            if default and dialect.name == "sqlite":
                default = {"TRUE": "1", "FALSE": "0"}.get(default, default)
            clause = f" DEFAULT {default}" if default else ""
            sync_conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {col.name} {ddl_type}{clause}"))
            logger.info(f"Schema upgrade: added {table.name}.{col.name}")
    for ddl in _INDEXES:
        sync_conn.execute(text(ddl))


async def _backfill(session: AsyncSession) -> None:
    """Give pre-v2 claims a slug, normalised text, v2 hash and confidence band.

    Pre-v2 live verdicts were produced without the honest-uncertainty gate or a correction,
    so they are kept but made private: they never appear in the registry or answer repeats.
    """
    from database.models import Claim, confidence_band, new_slug
    from services.text_utils import input_hash, normalize

    rows = (await session.scalars(select(Claim).where(Claim.normalized_text.is_(None)))).all()
    for c in rows:
        c.slug = c.slug or new_slug()
        c.normalized_text = normalize(c.raw_input)
        c.input_hash = input_hash(c.raw_input)
        c.confidence_band = c.confidence_band or confidence_band(c.confidence)
        c.is_public = bool(c.is_seed)
    legacy = (
        await session.scalars(
            select(Claim).where(
                Claim.is_seed.is_(False), Claim.is_public.is_(True), Claim.status == "complete",
                Claim.model_verdict.is_(None),
            )
        )
    ).all()
    for c in legacy:
        c.is_public = False
    if rows or legacy:
        await session.commit()
        logger.info(f"Backfilled {len(rows)} claims; {len(legacy)} pre-v2 verdicts set to private")


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
