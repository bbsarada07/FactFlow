"""Evidence that still works on a cloud host: the Bing News and Google News RSS providers, the tiering of
certified fact-checkers, and the switch to the larger model when the fast one is rate limited."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from services import news_service
from services.tiers import tier_for

BING_RSS = b"""<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel>
<item><title>Chandrayaan-3 lands near the Moon&#39;s south pole</title>
<link>http://www.bing.com/news/apiclick.aspx?ref=FexRss&amp;aid=&amp;tid=1&amp;url=https%3a%2f%2fwww.ndtv.com%2findia-news%2fchandrayaan-3-lands-123&amp;c=1</link>
<description>India became the &lt;b&gt;first&lt;/b&gt; country to land near the south pole.</description>
<pubDate>Wed, 23 Aug 2023 12:34:00 GMT</pubDate></item>
<item><title>Bing's own page</title><link>http://www.bing.com/news/apiclick.aspx?url=https%3a%2f%2fwww.bing.com%2fnews</link></item>
<item><title>No link</title></item>
</channel></rss>"""

GOOGLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>
<item><title>No, UNESCO did not declare Jana Gana Mana the best anthem - Vishvas News</title>
<link>https://news.google.com/rss/articles/CBMiabc?oc=5</link>
<pubDate>Thu, 14 Mar 2024 07:00:00 GMT</pubDate>
<source url="https://www.vishvasnews.com">Vishvas News</source></item>
<item><title>Without a publisher</title><link>https://news.google.com/rss/articles/x</link></item>
</channel></rss>"""


def _serve(monkeypatch, body: bytes, status: int = 200):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, content=body, headers={"content-type": "application/rss+xml"})

    real = httpx.AsyncClient

    def client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(*args, **kwargs)

    monkeypatch.setattr(news_service.httpx, "AsyncClient", client)
    return seen


def test_bing_news_returns_the_real_article_address(monkeypatch):
    seen = _serve(monkeypatch, BING_RSS)
    rows = asyncio.run(news_service.search_bing_news("chandrayaan 3 landing"))
    assert seen[0].url.params["format"] == "rss" and seen[0].url.params["q"] == "chandrayaan 3 landing"
    assert rows == [{
        "origin": "bingnews", "name": "ndtv.com", "url": "https://www.ndtv.com/india-news/chandrayaan-3-lands-123",
        "title": "Chandrayaan-3 lands near the Moon's south pole",
        "snippet": "India became the first country to land near the south pole.", "published_at": "2023-08-23",
    }]
    assert tier_for(rows[0]["url"]) == 2


def test_google_news_tiers_by_the_publisher_not_the_google_link(monkeypatch):
    _serve(monkeypatch, GOOGLE_RSS)
    rows = asyncio.run(news_service.search_google_news("unesco jana gana mana"))
    assert len(rows) == 1
    row = rows[0]
    assert row["url"].startswith("https://news.google.com/") and row["tier_url"] == "https://www.vishvasnews.com"
    assert row["title"] == "No, UNESCO did not declare Jana Gana Mana the best anthem" and row["name"] == "Vishvas News"
    assert tier_for(row["url"]) == 3 and tier_for(row["tier_url"]) == 2


@pytest.mark.parametrize("body,status,reason", [(b"", 429, "HTTP 429"), (b"<html>blocked</html", 200, "ParseError")])
def test_a_failing_news_feed_is_an_evidence_gap_not_a_crash(monkeypatch, body, status, reason):
    _serve(monkeypatch, body, status)
    errors = []
    assert asyncio.run(news_service.search_bing_news("x", errors=errors)) == []
    assert errors == [f"Bing News search unavailable ({reason})"]


@pytest.mark.parametrize("url", ["https://www.vishvasnews.com/x", "https://english.factcrescendo.com/x",
                                 "https://www.indiatoday.in/fact-check/x", "https://newsmeter.in/x",
                                 "https://www.hindustantimes.com/x", "https://www.livemint.com/x"])
def test_certified_fact_checkers_and_national_newsrooms_are_tier_2(url):
    assert tier_for(url) == 2


def test_news_search_results_are_tiered_by_publisher_and_deduplicated(monkeypatch):
    from agents import source_tracer
    from agents.context import PipelineContext

    google = [{"origin": "googlenews", "name": "Vishvas News", "url": "https://news.google.com/rss/articles/a",
               "tier_url": "https://www.vishvasnews.com", "title": "UNESCO did not rank anthems", "snippet": "",
               "published_at": None},
              {"origin": "googlenews", "name": "Vishvas News", "url": "https://news.google.com/rss/articles/b",
               "tier_url": "https://www.vishvasnews.com", "title": "UNESCO did not rank anthems!", "snippet": "",
               "published_at": None}]
    monkeypatch.setattr(source_tracer, "search_google_news", AsyncMock(return_value=google))
    for name in ("search_internal_kb", "search_gdelt", "search_factchecks", "search_newsapi", "search_duckduckgo",
                 "search_bing_news"):
        monkeypatch.setattr(source_tracer, name, AsyncMock(return_value=[]))
    ctx = PipelineContext(request_id="r", raw_text="UNESCO named Jana Gana Mana the best anthem", input_type="text")
    ctx.claim = ctx.raw_text
    items = asyncio.run(source_tracer._gather(ctx))
    assert len(items) == 1 and items[0]["tier"] == 2


class _RateLimited(openai.RateLimitError):
    def __init__(self):
        request = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")
        super().__init__("Rate limit reached on tokens per minute (TPM)",
                         response=httpx.Response(429, request=request), body=None)


def test_a_rate_limited_fast_model_switches_to_the_large_model_at_once(monkeypatch):
    from config import settings
    from models import groq_client

    calls = []

    async def once(model, effort, system, user, max_tokens, temperature):
        calls.append(model)
        if model == settings.NANO_MODEL:
            raise _RateLimited()
        return groq_client.LLMResult(data={"ok": True}, model=model, ms=1, tokens=1)

    monkeypatch.setattr(groq_client, "_chat_json_no_rate_wait", once)
    monkeypatch.setattr(groq_client, "_chat_json", once)
    res = asyncio.run(groq_client.call_nano("system", "user"))
    assert res.data == {"ok": True} and res.model == settings.ULTRA_MODEL
    assert calls == [settings.NANO_MODEL, settings.ULTRA_MODEL]


def test_the_fast_model_does_not_wait_out_a_rate_limit(monkeypatch):
    """The no-wait wrapper raises a rate limit on the first try instead of sleeping and retrying."""
    from models import groq_client

    attempts = []

    async def create(**kwargs):
        attempts.append(kwargs["model"])
        raise _RateLimited()

    fake = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(create)})()})()})()
    monkeypatch.setattr(groq_client, "client", lambda: fake)
    with pytest.raises(openai.RateLimitError):
        asyncio.run(groq_client._chat_json_no_rate_wait("m", "low", "s", "u", 10, 0.2))
    assert attempts == ["m"]


def test_a_provider_that_just_failed_is_skipped_for_a_while(monkeypatch):
    """DuckDuckGo times out on every check from a cloud host; after one failure it is paused, not waited for."""
    monkeypatch.setattr(news_service, "_paused_until", {})
    calls = []

    def slow_fail(query, limit):
        calls.append(query)
        raise TimeoutError("timed out")

    monkeypatch.setattr(news_service, "_ddg_sync", slow_fail)
    first, second = [], []
    assert asyncio.run(news_service.search_duckduckgo("a", errors=first)) == []
    assert asyncio.run(news_service.search_duckduckgo("b", errors=second)) == []
    assert calls == ["a"]
    assert first == ["DuckDuckGo search unavailable (timed out)"]
    assert second == ["DuckDuckGo search unavailable (paused after a recent failure)"]
    monkeypatch.setattr(news_service, "_paused_until", {"DuckDuckGo": 0.0})
    asyncio.run(news_service.search_duckduckgo("c", errors=[]))
    assert calls == ["a", "c"]
