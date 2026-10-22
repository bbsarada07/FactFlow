"""News and web evidence: GDELT (default, no key), NewsAPI and DuckDuckGo.

Every search function accepts an optional `errors` list. A provider failure (timeout,
HTTP error, throttling) is appended there as a short human-readable string so the
pipeline can record it as an evidence gap instead of silently returning nothing.
"""
import asyncio
import time

import httpx
from loguru import logger

from config import settings
from services.tiers import domain_of

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    DDGS = None

NEWSAPI_URL = "https://newsapi.org/v2/everything"
GDELT_MIN_INTERVAL = 5.5  # GDELT asks for at most one request every 5 seconds
GDELT_THROTTLE_PREFIX = "Please limit requests"

_gdelt_lock = asyncio.Lock()
_gdelt_last = 0.0


def record_failure(errors: list[str] | None, provider: str, reason: str) -> None:
    """Record a provider failure for the evidence-gap list and the log."""
    logger.warning(f"{provider} failed: {reason}")
    if errors is not None:
        errors.append(f"{provider} search unavailable ({reason})")


def failure_reason(exc: Exception) -> str:
    """Short reason string for a provider exception."""
    text = str(exc).lower()
    if "timed out" in text or "timeout" in text or isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError)):
        return "timed out"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return exc.__class__.__name__


async def search_newsapi(query: str, limit: int = 6, errors: list[str] | None = None) -> list[dict]:
    """NewsAPI /everything. No date filter is sent: the free plan's own window (~30 days) applies."""
    if not settings.NEWS_API_KEY:
        return []
    params = {"q": query, "language": "en", "sortBy": "relevancy", "pageSize": limit, "apiKey": settings.NEWS_API_KEY}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(NEWSAPI_URL, params=params)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
    except Exception as exc:  # noqa: BLE001
        record_failure(errors, "NewsAPI", failure_reason(exc))
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


async def search_gdelt(query: str, date_params: dict, limit: int = 15, errors: list[str] | None = None) -> list[dict]:
    """GDELT DOC 2.0 article search. `date_params` is {"timespan": "90d"} or
    {"startdatetime": ..., "enddatetime": ...}; with neither, GDELT searches only ~3 months.

    Requests are spaced at least GDELT_MIN_INTERVAL apart within this process; a throttling
    reply is retried once after waiting.
    """
    global _gdelt_last
    if not settings.GDELT_ENABLED:
        return []
    params = {"query": query, "mode": "artlist", "format": "json", "maxrecords": limit, "sort": "hybridrel"}
    params.update(date_params or {})

    async with _gdelt_lock:
        for attempt in range(2):
            wait = GDELT_MIN_INTERVAL - (time.monotonic() - _gdelt_last)
            if wait > 0:
                await asyncio.sleep(wait)
            _gdelt_last = time.monotonic()
            try:
                async with httpx.AsyncClient(timeout=20, headers={"User-Agent": "FactFlow/1.0"}) as http:
                    resp = await http.get(settings.GDELT_URL, params=params)
                if resp.status_code != 429:
                    resp.raise_for_status()
            except Exception as exc:  # noqa: BLE001
                record_failure(errors, "GDELT", failure_reason(exc))
                return []
            body = resp.text.strip()
            if resp.status_code == 429 or body.startswith(GDELT_THROTTLE_PREFIX):
                if attempt == 0:
                    continue
                record_failure(errors, "GDELT", "rate limited")
                return []
            if not body:
                return []
            try:
                articles = resp.json().get("articles", [])
            except ValueError:
                record_failure(errors, "GDELT", f"unexpected response: {body[:60]}")
                return []
            break

    out = []
    for a in articles:
        url = a.get("url")
        if not url:
            continue
        seen = a.get("seendate") or ""
        out.append(
            {
                "origin": "gdelt",
                "name": a.get("domain") or domain_of(url),
                "url": url,
                "title": a.get("title"),
                "snippet": "",
                "published_at": f"{seen[:4]}-{seen[4:6]}-{seen[6:8]}" if len(seen) >= 8 else None,
            }
        )
    return out


def _ddg_sync(query: str, limit: int) -> tuple[list[dict], list[str]]:
    out: list[dict] = []
    failures: list[str] = []
    with DDGS(timeout=8) as ddg:
        for vertical in ("text", "news"):
            try:
                if vertical == "text":
                    rows = ddg.text(query, region="in-en", max_results=limit) or []
                    out += [
                        {"origin": "duckduckgo", "name": domain_of(r.get("href", "")), "url": r.get("href", ""),
                         "title": r.get("title"), "snippet": r.get("body", ""), "published_at": None}
                        for r in rows
                    ]
                else:
                    rows = ddg.news(query, region="in-en", max_results=max(3, limit // 2)) or []
                    out += [
                        {"origin": "duckduckgo", "name": r.get("source") or domain_of(r.get("url", "")),
                         "url": r.get("url", ""), "title": r.get("title"), "snippet": r.get("body", ""),
                         "published_at": r.get("date")}
                        for r in rows
                    ]
            except Exception as exc:  # noqa: BLE001
                if "no results found" not in str(exc).lower():
                    failures.append(failure_reason(exc))
    return [r for r in out if r["url"]], failures


async def search_duckduckgo(query: str, limit: int = 6, errors: list[str] | None = None) -> list[dict]:
    """DuckDuckGo text + news verticals. 'No results' is an empty answer, not a failure."""
    if DDGS is None:
        return []
    try:
        rows, failures = await asyncio.wait_for(asyncio.to_thread(_ddg_sync, query, limit), timeout=20)
    except Exception as exc:  # noqa: BLE001
        record_failure(errors, "DuckDuckGo", failure_reason(exc))
        return []
    if failures and not rows:
        record_failure(errors, "DuckDuckGo", failures[0])
    return rows
