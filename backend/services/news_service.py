"""News and web evidence: NewsAPI + DuckDuckGo (text and news verticals)."""
import asyncio
from urllib.parse import urlparse

import httpx
from loguru import logger

from config import settings

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    DDGS = None

NEWSAPI_URL = "https://newsapi.org/v2/everything"


def domain_of(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


async def search_newsapi(query: str, limit: int = 6) -> list[dict]:
    if not settings.NEWS_API_KEY:
        return []
    params = {
        "q": query,
        "language": "en",
        "sortBy": "relevancy",
        "pageSize": limit,
        "apiKey": settings.NEWS_API_KEY,
    }
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(NEWSAPI_URL, params=params)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"NewsAPI search failed for {query!r}: {exc}")
        return []
    return [
        {
            "origin": "newsapi",
            "name": (a.get("source") or {}).get("name") or domain_of(a.get("url", "")),
            "url": a.get("url", ""),
            "title": a.get("title"),
            "snippet": a.get("description") or "",
            "published_at": a.get("publishedAt"),
        }
        for a in articles
        if a.get("url") and "[Removed]" not in (a.get("title") or "")
    ]


def _ddg_sync(query: str, limit: int) -> list[dict]:
    out: list[dict] = []
    with DDGS(timeout=8) as ddg:
        try:
            for r in ddg.text(query, region="in-en", max_results=limit) or []:
                out.append(
                    {
                        "origin": "duckduckgo",
                        "name": domain_of(r.get("href", "")),
                        "url": r.get("href", ""),
                        "title": r.get("title"),
                        "snippet": r.get("body", ""),
                        "published_at": None,
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"DuckDuckGo text search failed for {query!r}: {exc}")
        try:
            for r in ddg.news(query, region="in-en", max_results=max(3, limit // 2)) or []:
                out.append(
                    {
                        "origin": "duckduckgo",
                        "name": r.get("source") or domain_of(r.get("url", "")),
                        "url": r.get("url", ""),
                        "title": r.get("title"),
                        "snippet": r.get("body", ""),
                        "published_at": r.get("date"),
                    }
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"DuckDuckGo news search failed for {query!r}: {exc}")
    return [r for r in out if r["url"]]


async def search_duckduckgo(query: str, limit: int = 6) -> list[dict]:
    if DDGS is None:
        return []
    try:
        return await asyncio.wait_for(asyncio.to_thread(_ddg_sync, query, limit), timeout=20)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"DuckDuckGo search failed for {query!r}: {exc}")
        return []
