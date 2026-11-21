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
    account, accuracy, agent, approvals, audit, auth, benchmark, history, inbox, incidents, mail, policy, public_config,
    registry, result, sandbox, stats, stream, verify, whatsapp,
)
from config import settings
from database import connection
from models.gemini_client import vision_available
from services import mail_agent, mail_sender
from services.cache_service import redis_ping

logger.remove()
# diagnose=False: tracebacks must not print local variables (message text, phone numbers)
logger.add(sys.stderr, level="DEBUG" if settings.DEBUG else "INFO", diagnose=False)


async def keep_alive() -> None:
    """Request our own public URL now and then, so free hosting does not put the agent to sleep."""
    import httpx

    while True:
        await asyncio.sleep(settings.KEEP_ALIVE_MINUTES * 60)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                await client.get(settings.KEEP_ALIVE_URL)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - never let the keep-alive crash anything
            logger.warning(f"keep-alive request failed ({type(exc).__name__})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    dialect = await connection.init_db()
    if not settings.GROQ_API_KEY:
        logger.error("GROQ_API_KEY missing — verifications will fail until it is set in backend/.env")
    logger.info(f"FactFlow ready · db={dialect} · nano={settings.NANO_MODEL} · ultra={settings.ULTRA_MODEL}")
    loops = [asyncio.create_task(mail_agent.poll_forever()),  # each user's Gmail: check, act, scan sent, digest
             asyncio.create_task(mail_sender.dispatch_forever())] if settings.MAIL_POLL_ENABLED else []  # undo window
    if settings.KEEP_ALIVE_URL:
        loops.append(asyncio.create_task(keep_alive()))
    yield
    for loop in loops:
        loop.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await loop
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

app.include_router(agent.account_router)
for module in (auth, account, agent, verify, stream, result, history, incidents, stats, registry, public_config, accuracy,
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
