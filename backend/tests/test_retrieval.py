"""Retrieval: allow-list tiers, query variants, news window and provider failures as gaps."""
import pytest

from agents.query_variants import expand_queries, gdelt_query, variant_queries
from agents.source_tracer import news_window
from agents.uncertainty import evidence_gaps
from config import settings
from services.tiers import tier_for


@pytest.mark.parametrize(
    "url,tier",
    [
        ("https://www.aninews.in/news/national/x", 1),
        ("https://pib.gov.in/PressReleasePage.aspx?PRID=1", 1),
        ("https://www.reuters.com/world/india/x", 1),
        ("https://hyderabad.telangana.gov.in/notice", 1),
        ("https://school.nic.in/x", 1),
        ("https://www.siasat.com/hyderabad-holiday-x/", 2),
        ("https://telanganatoday.com/x", 2),
        ("https://timesofindia.indiatimes.com/city/hyderabad/x.cms", 2),
        ("https://www.ndtv.com/x", 2),
        ("https://www.news18.com/x", 2),
        ("https://www.altnews.in/x", 2),
        ("https://www.boomlive.in/x", 2),
        ("https://factly.in/x", 2),
        ("https://www.youtube.com/watch?v=1", 4),
        ("https://www.fbi.gov/x", 3),  # foreign .gov is not on the allow-list
        ("https://randomblog.example/x", 3),
    ],
)
def test_tiers_come_from_allow_list(url, tier):
    assert tier_for(url) == tier


def test_variants_cover_transliterations():
    vs = variant_queries("Hyderabad schools closed Ganesh Nimarjan", limit=4)
    joined = " ".join(vs).lower()
    assert "immersion" in joined and "nimajjanam" in joined


def test_expand_queries_gives_at_least_three_and_dedupes():
    out = expand_queries(["Ganesh Nimarjan holiday", "ganesh  nimarjan holiday"], "Schools closed for Ganesh Nimarjan")
    assert len(out) >= 3
    assert len({" ".join(q.lower().split()) for q in out}) == len(out)


def test_gdelt_query_uses_or_groups():
    q = gdelt_query("Hyderabad schools closed Ganesh Nimarjan")
    assert "(immersion OR nimajjanam OR nimarjan OR visarjan OR nimajjan)" in q
    assert "hyderabad" in q


def test_news_window_default_and_old_events():
    assert news_window("Schools closed for Ganesh Nimarjan", "2026-10-21") == settings.NEWS_WINDOW_DAYS
    assert news_window("Palghar lynching in 2020", "2026-10-21") is None
    assert news_window("Holiday on 25 September 2026", "2026-10-21") == settings.NEWS_WINDOW_DAYS


def test_provider_failures_become_evidence_gaps_first():
    gaps = evidence_gaps([], ["no primary source found"] * 1, "text", ["DuckDuckGo search unavailable (timed out)"])
    assert gaps[0] == "DuckDuckGo search unavailable (timed out)"
    assert "No relevant source found" in gaps
