"""Retrieval: allow-list tiers, query variants, news window and provider failures as gaps."""
import pytest

from agents.query_variants import expand_queries, gdelt_query, keyword_query, variant_queries
from agents.source_tracer import gdelt_dates, news_window
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
        ("https://factcheck.afp.com/x", 2),
        ("https://newschecker.in/fact-check/x", 2),
        ("https://www.thequint.com/news/webqoof/x", 2),
        ("https://www.snopes.com/fact-check/x/", 2),
        ("https://en.wikipedia.org/wiki/2020_Palghar_mob_lynching", 3),
        ("https://www.youtube.com/watch?v=1", 4),
        ("https://www.fbi.gov/x", 3),  # foreign .gov is not on the allow-list
        ("https://randomblog.example/x", 3),
    ],
)
def test_tiers_come_from_allow_list(url, tier):
    assert tier_for(url) == tier


def test_verdict_cannot_rest_on_wikipedia_alone():
    from agents.orchestrator import decide_verdict

    urls = [
        "https://en.wikipedia.org/wiki/2020_Palghar_mob_lynching",
        "https://en.wikipedia.org/wiki/Palghar_district",
        "https://hi.wikipedia.org/wiki/x",
    ]
    evidence = [{"url": u, "tier": tier_for(u), "origin": "duckduckgo"} for u in urls]
    out = decide_verdict(
        evidence, {"verdict": "TRUE", "confidence": 0.97, "contradictions_found": [], "missing_context": []}
    )
    assert out["verdict"] == "UNVERIFIED"


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


def test_gdelt_searches_the_period_an_old_event_names():
    # Regression (T09): with no date filter GDELT only searches ~3 months, so a 2020 event found nothing.
    params, _ = gdelt_dates("Two sadhus were lynched in Palghar in April 2020", "2026-10-21")
    assert params == {"startdatetime": "20200401000000", "enddatetime": "20200531235959"}
    params, _ = gdelt_dates("Article 370 was revoked in 2019", "2026-10-21")
    assert params == {"startdatetime": "20190101000000", "enddatetime": "20191231235959"}
    params, _ = gdelt_dates("Schools closed for Ganesh Nimarjan", "2026-10-21")
    assert params == {"timespan": f"{settings.NEWS_WINDOW_DAYS}d"}


def test_gdelt_skips_events_before_its_archive():
    params, label = gdelt_dates("Riots in Muzaffarnagar in September 2013", "2026-10-21")
    assert params is None and "2017" in label


def test_variant_never_repeats_a_word():
    assert all("mob mob" not in v.lower() for v in variant_queries("Palghar mob lynching April 2020", 5))


def test_keyword_and_gdelt_queries_drop_years_and_months():
    claim = "Two sadhus and their driver were lynched by a mob in Palghar, Maharashtra in April 2020"
    assert keyword_query(claim) == "sadhus driver lynched palghar"
    assert "2020" not in gdelt_query("Palghar mob lynching April 2020")
    assert "april" not in gdelt_query("Palghar mob lynching April 2020")


def test_provider_failures_become_evidence_gaps_first():
    gaps = evidence_gaps([], ["no primary source found"] * 1, "text", ["DuckDuckGo search unavailable (timed out)"])
    assert gaps[0] == "DuckDuckGo search unavailable (timed out)"
    assert "No relevant source found" in gaps


@pytest.mark.parametrize(
    "url,tier",
    [
        ("https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx", 1),
        ("https://website.rbi.org.in/web/rbi/press-releases", 1),
        ("https://www.sebi.gov.in/media/press-releases", 1),  # covered by .gov.in
        ("https://www.mohfw.gov.in/", 1),  # covered by .gov.in
        ("https://rbi.org.in.example.com/x", 3),  # look-alike host is not official
        ("https://fakerbi.org.in/x", 3),
    ],
)
def test_official_regulator_sites_are_tier_1(url, tier):
    assert tier_for(url) == tier
