"""Deterministic outputs: checks_to_do, confidence bands and the correction text."""
from agents.context import PipelineContext
from agents.explainer import POST_LIMIT, build_correction
from agents.uncertainty import build_checks
from config import settings
from database.models import confidence_band


def labels(checks):
    return [c["label"] for c in checks]


def test_google_search_always_present_and_uses_allow_list():
    checks = build_checks("Garlic cures coronavirus", "", "text", "HEALTH")
    assert labels(checks) == ["Search the claim on Google"]
    assert checks[0]["url"].startswith(settings.GOOGLE_SEARCH_URL)


def test_media_government_and_date_checks():
    checks = build_checks("Video shows PM announcing new scheme on 12 March", "", "text", "OTHER")
    assert labels(checks) == [
        "Search the claim on Google",
        "Reverse image search",
        "Check PIB Fact Check",
        "Check the original post date",
    ]
    assert checks[1]["url"] == settings.REVERSE_IMAGE_SEARCH_URL
    assert checks[2]["url"] == settings.PIB_FACTCHECK_URL
    assert checks[3]["url"] is None


def test_confidence_bands():
    assert confidence_band(0.9) == "high"
    assert confidence_band(0.85) == "high"
    assert confidence_band(0.84) == "medium"
    assert confidence_band(0.6) == "medium"
    assert confidence_band(0.59) == "low"
    assert confidence_band(None) == "low"


def ctx(verdict):
    """Pipeline state with two tier-1 sources and a long claim."""
    c = PipelineContext(request_id="x", raw_text="Some forward text")
    c.claim = "A gang of child thieves harvesting organs is active in the area " * 3
    c.verdict = verdict
    c.slug = "abc123xyz0"
    c.fact = "Police found no such gang."
    c.evidence = [{"name": "Alt News", "tier": 1, "credibility": 0.95}, {"name": "BOOM", "tier": 1, "credibility": 0.9}]
    return c


def test_unverified_correction_never_calls_claim_false():
    corr = build_correction(ctx("UNVERIFIED"), {"correction_en": "This is FALSE and fake"})
    assert corr["text_en"].startswith("We could not verify this yet")
    assert "false" not in corr["text_en"].lower() and "fake" not in corr["text_en"].lower()
    assert corr["source_label"] == "No verified source yet"
    for key in ("text_en", "text_hi", "text_te"):
        assert len(corr[key]) <= POST_LIMIT
        assert corr[key].endswith("/v/abc123xyz0")


def test_definite_correction_fits_one_post_and_links_registry():
    long_text = "Fact check: this claim is false. " * 20
    corr = build_correction(ctx("FALSE"), {"correction_en": long_text, "correction_hi": "यह दावा झूठा है।"})
    assert corr["source_label"] == "Alt News"
    assert len(corr["text_en"]) <= POST_LIMIT and corr["text_en"].endswith("/v/abc123xyz0")
    assert corr["text_hi"].startswith("यह दावा")
    assert corr["text_te"] is None


def test_correction_strips_model_urls():
    corr = build_correction(ctx("FALSE"), {"correction_en": "False, see https://made-up.example/x for details"})
    assert "made-up.example" not in corr["text_en"]
