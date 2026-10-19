"""GET /api/config — public, non-secret configuration for the frontend and extension."""
from fastapi import APIRouter

from config import settings

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/config")
async def public_config():
    """Model names, inference provider and evidence sources actually in use, plus public URLs."""
    sources = ["DuckDuckGo"]
    if settings.GOOGLE_FACT_CHECK_API_KEY:
        sources.insert(0, "Google Fact Check")
    if settings.NEWS_API_KEY:
        sources.insert(0, "NewsAPI")
    return {
        "provider": settings.INFERENCE_PROVIDER,
        "models": {"nano": settings.NANO_MODEL, "ultra": settings.ULTRA_MODEL},
        "evidence_sources": sources,
        "frontend_url": settings.FRONTEND_URL.rstrip("/"),
        "max_claim_chars": settings.MAX_CLAIM_CHARS,
        "repeat_window_days": settings.REPEAT_WINDOW_DAYS,
    }
