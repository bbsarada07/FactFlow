"""News and web evidence: Bing News and Google News (RSS, no key), GDELT (no key), NewsAPI and DuckDuckGo.

DuckDuckGo and GDELT often refuse requests from cloud hosts (shared IP addresses); the two news
RSS feeds answer them, so a deployed server still finds news coverage.

Every search function accepts an optional `errors` list. A provider failure (timeout,
HTTP error, throttling) is appended there as a short human-readable string so the
pipeline can record it as an evidence gap instead of silently returning nothing.
"""
import asyncio
import re
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import parse_qs, urlparse

import httpx
from loguru import logger

from config import settings
from services.tiers import domain_of

try:
    from ddgs import DDGS
except ImportError:  # pragma: no cover
    DDGS = None

NEWSAPI_URL = "https://newsapi.org/v2/everything"
BING_NEWS_URL = "https://www.bing.com/news/search"
GOOGLE_NEWS_URL = "https://news.google.com/rss/search"
RSS_MAX_BYTES = 2_000_000
_TAGS = re.compile(r"<[^>]+>")
GDELT_MIN_INTERVAL = 5.5  # GDELT asks for at most one request every 5 seconds
GDELT_THROTTLE_PREFIX = "Please limit requests"

_gdelt_lock = asyncio.Lock()
_gdelt_last = 0.0

# A provider that just timed out or refused us is skipped for a while: on a cloud host DuckDuckGo and GDELT
# fail for every check, and waiting out their timeouts made each check ~20 seconds slower for nothing.
PAUSE_SECONDS = 600
_paused_until: dict[str, float] = {}


def _paused(provider: str, errors: list[str] | None) -> bool:
    if time.monotonic() < _paused_until.get(provider, 0.0):
        if errors is not None:
            errors.append(f"{provider} search unavailable (paused after a recent failure)")
        return True
    return False


def _pause(provider: str) -> None:
    _paused_until[provider] = time.monotonic() + PAUSE_SECONDS


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
    if not settings.GDELT_ENABLED or _paused("GDELT", errors):
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
                _pause("GDELT")
                return []
            body = resp.text.strip()
            if resp.status_code == 429 or body.startswith(GDELT_THROTTLE_PREFIX):
                if attempt == 0:
                    continue
                record_failure(errors, "GDELT", "rate limited")
                _pause("GDELT")
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
    if DDGS is None or _paused("DuckDuckGo", errors):
        return []
    try:
        rows, failures = await asyncio.wait_for(asyncio.to_thread(_ddg_sync, query, limit), timeout=20)
    except Exception as exc:  # noqa: BLE001
        record_failure(errors, "DuckDuckGo", failure_reason(exc))
        _pause("DuckDuckGo")
        return []
    if failures and not rows:
        record_failure(errors, "DuckDuckGo", failures[0])
        _pause("DuckDuckGo")
    return rows


def _rss_items(body: bytes) -> list[ET.Element]:
    if len(body) > RSS_MAX_BYTES:
        raise ValueError("RSS response too large")
    return ET.fromstring(body).findall(".//item")


def _rss_date(text: str | None) -> str | None:
    try:
        return parsedate_to_datetime(text).date().isoformat() if text else None
    except (TypeError, ValueError):
        return None


def _plain(text: str | None) -> str:
    return " ".join(unescape(_TAGS.sub(" ", text or "")).split())


async def _get_rss(provider: str, url: str, params: dict, errors: list[str] | None) -> list[ET.Element] | None:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True,
                                     headers={"User-Agent": "Mozilla/5.0 (compatible; FactFlow/1.0)"}) as http:
            resp = await http.get(url, params=params)
        resp.raise_for_status()
        return _rss_items(resp.content)
    except Exception as exc:  # noqa: BLE001
        record_failure(errors, provider, failure_reason(exc))
        return None


async def search_bing_news(query: str, limit: int = 8, errors: list[str] | None = None) -> list[dict]:
    """Bing News search as RSS. Each link carries the article's own address in its `url` parameter."""
    items = await _get_rss("Bing News", BING_NEWS_URL, {"q": query, "format": "rss", "cc": "IN"}, errors)
    out = []
    for it in items or []:
        link = it.findtext("link") or ""
        url = (parse_qs(urlparse(link).query).get("url") or [link])[0]
        if not url.startswith(("http://", "https://")) or domain_of(url).endswith("bing.com"):
            continue
        out.append({"origin": "bingnews", "name": domain_of(url), "url": url, "title": _plain(it.findtext("title")),
                    "snippet": _plain(it.findtext("description"))[:400], "published_at": _rss_date(it.findtext("pubDate"))})
        if len(out) >= limit:
            break
    return out


async def search_google_news(query: str, limit: int = 8, errors: list[str] | None = None) -> list[dict]:
    """Google News search as RSS. Links open the article through news.google.com, so the credibility tier
    comes from the publisher's own address (`tier_url`), which the feed names for every item."""
    items = await _get_rss("Google News", GOOGLE_NEWS_URL, {"q": query, "hl": "en-IN", "gl": "IN", "ceid": "IN:en"}, errors)
    out = []
    for it in items or []:
        link, source = it.findtext("link") or "", it.find("source")
        publisher_url = source.get("url", "") if source is not None else ""
        if not link.startswith("https://") or not publisher_url.startswith(("http://", "https://")):
            continue
        publisher = (source.text or "").strip() or domain_of(publisher_url)
        title = _plain(it.findtext("title"))
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        out.append({"origin": "googlenews", "name": publisher, "url": link, "tier_url": publisher_url, "title": title,
                    "snippet": "", "published_at": _rss_date(it.findtext("pubDate"))})
        if len(out) >= limit:
            break
    return out
