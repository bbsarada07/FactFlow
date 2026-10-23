"""FactFlow API — multi-agent misinformation forensics.

Run:  uvicorn main:app --reload --port 8000
"""
import asyncio
import contextlib
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger
from sqlalchemy import text

from api import (
    accuracy, approvals, audit, benchmark, history, inbox, incidents, mail, policy, public_config, registry, result,
    sandbox, stats, stream, verify, whatsapp,
)
from config import settings
from database import connection
from models.gemini_client import vision_available
from services import mail_agent
from services.cache_service import redis_ping

logger.remove()
# diagnose=False: tracebacks must not print local variables (message text, phone numbers)
logger.add(sys.stderr, level="DEBUG" if settings.DEBUG else "INFO", diagnose=False)


@asynccontextmanager
async def lifespan(app: FastAPI):
    dialect = await connection.init_db()
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY missing — verifications will fail until it is set in backend/.env")
    logger.info(f"FactFlow ready · db={dialect} · nano={settings.NANO_MODEL} · ultra={settings.ULTRA_MODEL}")
    poller = asyncio.create_task(mail_agent.poll_forever()) if settings.MAIL_POLL_ENABLED else None
    yield
    if poller is not None:
        poller.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await poller
    await connection.close_db()


app = FastAPI(
    title="FactFlow",
    description="Multi-agent misinformation detection: intake, source tracing, deep reasoning, explanation and harm assessment.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "http://localhost:3000", "http://127.0.0.1:3000"],
    allow_origin_regex=r"chrome-extension://.*",
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

for module in (verify, stream, result, history, incidents, stats, registry, public_config, accuracy,
               inbox, approvals, audit, policy, mail, sandbox, benchmark, whatsapp):
    app.include_router(module.router)


def redis_configured() -> bool:
    """True only if REDIS_URL was explicitly set (environment or .env), not just defaulted."""
    return "REDIS_URL" in settings.model_fields_set


async def redis_status() -> dict:
    """Plain-language Redis status. Redis is only required for the Celery queue (USE_CELERY);
    the default in-process pipeline runs without it. The URL itself is never reported."""
    required = settings.USE_CELERY
    note = "required by USE_CELERY" if required else "not required; the pipeline runs without Redis"
    if not redis_configured():
        return {"configured": False, "reachable": False, "required": required,
                "status": f"not configured (REDIS_URL not set) - {note}"}
    reachable = await redis_ping()
    return {"configured": True, "reachable": reachable, "required": required,
            "status": "connected" if reachable else f"configured but unreachable - {note}"}


@app.get("/health", tags=["health"])
async def health():
    """Service health: database, Redis, models, evidence sources and the running build commit."""
    db_ok = True
    try:
        async with connection.session_factory()() as s:
            await s.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "build_commit": settings.BUILD_COMMIT or "unknown (BUILD_COMMIT not set)",
        "database": connection.engine.dialect.name if connection.engine else None,
        "database_ok": db_ok,
        "redis": await redis_status(),
        "llm_configured": bool(settings.GROQ_API_KEY),
        "keys_configured": {  # true/false only; key values are never reported
            "groq": bool(settings.GROQ_API_KEY),
            "gemini": bool(settings.GEMINI_API_KEY),
            "news_api": bool(settings.NEWS_API_KEY),
            "google_fact_check": bool(settings.GOOGLE_FACT_CHECK_API_KEY),
        },
        "reasoning_provider": settings.REASONING_PROVIDER,
        "vision_provider": settings.VISION_PROVIDER if vision_available() or settings.VISION_PROVIDER != "gemini" else "tesseract (no GEMINI_API_KEY)",
        "models": {
            "nano": settings.NANO_MODEL,
            "reasoning": settings.ULTRA_MODEL,
            "ultra": settings.ULTRA_MODEL,  # read by the About page
            "vision": settings.GEMMA_MODEL if vision_available() else (
                settings.VISION_MODEL if settings.VISION_PROVIDER == "groq" else "tesseract"),
        },
        "queue": "celery" if settings.USE_CELERY else "inprocess",
        "evidence_sources": {
            "newsapi": bool(settings.NEWS_API_KEY),
            "google_fact_check": bool(settings.GOOGLE_FACT_CHECK_API_KEY),
            "duckduckgo": True,
        },
    }
