"""Grounding rule: sentences must cite retrieved sources; absence claims need a citation."""
from agents.context import PipelineContext
from agents.explainer import build_correction, fallback
from agents.grounding import (
    NO_SOURCES,
    assign_refs,
    ground_list,
    ground_text,
    remap_candidate_citations,
    require_named_sources,
    uncited_sentences,
)


def test_absence_claim_without_citation_is_removed():
    text = "Schools were shut on 25 September [S1]. No official announcements confirm this."
    assert ground_text(text, n_sources=2, strict=False) == "Schools were shut on 25 September [S1]."


def test_absence_claim_with_citation_is_kept():
    text = "No evidence of a kidnapping gang was found by police [S2]."
    assert ground_text(text, n_sources=2, strict=False) == text


def test_strict_mode_drops_every_uncited_sentence():
    text = "The claim has three parts. Telangana declared a holiday [S1]. It was widely shared."
    out = ground_text(text, n_sources=1)
    assert out == "Telangana declared a holiday [S1]."
    assert uncited_sentences(out, 1) == []


def test_citations_after_the_full_stop_belong_to_that_sentence():
    # Regression: the Hyderabad re-run produced "... September 25. [S1][S2]" and the sentence
    # text was dropped as uncited, leaving only "[S1][S2]".
    text = "Telangana closed schools on 25 September. [S1][S2] Offices also shut. [S3]"
    out = ground_text(text, n_sources=3)
    assert out == text
    assert uncited_sentences(out, 3) == []


TOI = {"name": "timesofindia.indiatimes.com", "url": "https://timesofindia.indiatimes.com/x.cms", "ref": "S1",
       "tier": 2, "credibility": 0.8}
TT = {"name": "telanganatoday.com", "url": "https://telanganatoday.com/x", "ref": "S2", "tier": 2, "credibility": 0.8}


def test_reporting_claim_without_a_named_source_is_rejected():
    text = "Several reputable news outlets reported the closure [S1]."
    assert require_named_sources(text, [TOI, TT]) == ""


def test_reporting_claim_naming_a_retrieved_source_is_kept():
    text = "Telangana Today reported the closure on 25 September [S2]. The Times of India confirmed it [S1]."
    assert require_named_sources(text, [TOI, TT]) == text


def test_named_but_uncited_reporting_claim_is_rejected():
    assert require_named_sources("Telangana Today reported the closure.", [TOI, TT]) == ""


def test_non_reporting_sentences_are_left_alone():
    text = "Schools were closed on 25 September for the immersion [S1]."
    assert require_named_sources(text, [TOI]) == text


def test_explainer_summary_drops_unnamed_reporting():
    from agents.explainer import _named_summary

    ctx = PipelineContext(request_id="x", raw_text="r")
    ctx.evidence = [TOI, TT]
    out = _named_summary("This closure was reported by several reputable news outlets. [S1][S2] "
                         "Telangana Today reported the holiday [S2].", ctx)
    assert out == "Telangana Today reported the holiday [S2]."


def test_citations_to_unretrieved_sources_are_invalid():
    # [S5] does not exist when only 2 sources were retrieved.
    assert ground_text("A holiday was declared [S5].", n_sources=2) == ""
    assert ground_text("No announcement was made [S5].", n_sources=2, strict=False) == ""


def test_zero_sources_leaves_nothing_ungrounded():
    assert ground_text("No official notice was issued. Schools stayed open.", n_sources=0) == ""


def test_candidate_citations_are_remapped_to_source_ids():
    evidence = [{"candidate": 4}, {"candidate": 1}]
    mapping = assign_refs(evidence)
    assert [e["ref"] for e in evidence] == ["S1", "S2"]
    out = remap_candidate_citations("Holiday declared [4]. Also reported [1, 9].", mapping)
    assert out == "Holiday declared [S1]. Also reported [S2]."


def test_ground_list_drops_uncited_reasons():
    reasons = ["Claim has three parts.", "TOI reports the holiday [S1].", "No evidence exists."]
    assert ground_list(reasons, 1) == ["TOI reports the holiday [S1]."]


def test_zero_evidence_output_says_no_sources_found_yet():
    ctx = PipelineContext(request_id="x", raw_text="Schools closed for Ganesh Nimarjan")
    ctx.claim, ctx.verdict, ctx.slug = "Schools closed for Ganesh Nimarjan", "UNVERIFIED", "abc"
    ctx.summary = "No official announcements confirm this."
    fallback(ctx)
    assert ctx.summary.startswith("No sources found yet.")
    assert ctx.fact == NO_SOURCES
    assert "official" not in ctx.summary.lower() and "announcement" not in ctx.summary.lower()
    assert "No sources found yet." in ctx.correction["text_en"]


def test_definite_correction_names_its_source_and_drops_absence_claims():
    ctx = PipelineContext(request_id="x", raw_text="r")
    ctx.claim, ctx.verdict, ctx.slug = "Schools were closed", "TRUE", "abc"
    ctx.evidence = [{"name": "Times of India", "tier": 2, "credibility": 0.8, "ref": "S1"}]
    corr = build_correction(ctx, {"correction_en": "True: schools were closed. No official notice exists."})
    assert "No official" not in corr["text_en"]
    assert "Times of India" in corr["text_en"]
