"""Google Fact Check Tools API (claims:search)."""
import httpx
from loguru import logger

from config import settings

FACTCHECK_URL = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


async def search_factchecks(query: str, limit: int = 8, language: str | None = None) -> list[dict]:
    if not settings.GOOGLE_FACT_CHECK_API_KEY:
        return []
    params = {"query": query, "pageSize": limit, "key": settings.GOOGLE_FACT_CHECK_API_KEY}
    if language and language not in ("auto", "unknown"):
        params["languageCode"] = language
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(FACTCHECK_URL, params=params)
        resp.raise_for_status()
        claims = resp.json().get("claims", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"Fact Check API failed for {query!r}: {exc}")
        return []

    results = []
    for c in claims:
        for review in c.get("claimReview", [])[:1]:
            if not review.get("url"):
                continue
            publisher = review.get("publisher") or {}
            results.append(
                {
                    "origin": "factcheck",
                    "name": publisher.get("name") or publisher.get("site") or "Fact-checker",
                    "url": review["url"],
                    "title": review.get("title") or c.get("text"),
                    "snippet": f"Claim reviewed: {c.get('text', '')}"[:400],
                    "rating": review.get("textualRating"),
                    "published_at": review.get("reviewDate"),
                }
            )
    return results
