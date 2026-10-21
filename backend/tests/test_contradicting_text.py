"""Displayed text must not contradict the verdict unless a retrieved source backs the sentence."""
from agents.context import PipelineContext
from agents.grounding import drop_contradictions
from agents.orchestrator import remove_contradicting_text

HYDERABAD_HARM = (
    "The claim is a likely false rumor about school closures that would cause minimal confusion "
    "but no significant real-world harm."
)
EVIDENCE = [
    {"ref": "S1", "name": "Telangana Today", "url": "https://telanganatoday.com/x", "tier": 2, "stance": "SUPPORTS"},
    {"ref": "S2", "name": "Siasat", "url": "https://www.siasat.com/x", "tier": 2, "stance": "SUPPORTS"},
]


def _ctx(verdict: str) -> PipelineContext:
    ctx = PipelineContext(request_id="x", raw_text="Schools in Hyderabad were closed for Ganesh Nimajjanam")
    ctx.verdict, ctx.evidence = verdict, list(EVIDENCE)
    return ctx


def test_true_verdict_drops_uncited_likely_false_rumor_sentence():
    ctx = _ctx("TRUE")
    ctx.summary = "Telangana Today reported the holiday [S1]. The claim is a likely false rumor about school closures."
    ctx.harm_rationale = HYDERABAD_HARM
    remove_contradicting_text(ctx)
    assert "likely false rumor" not in ctx.summary
    assert ctx.summary == "Telangana Today reported the holiday [S1]."
    assert "likely false rumor" not in ctx.harm_rationale and ctx.harm_rationale == ""


def test_true_verdict_drops_each_contradicting_word_without_citation():
    for sentence in ("This is a hoax.", "The post is fake.", "Rumours like this spread fast.", "It was falsely shared."):
        assert drop_contradictions(f"Schools were shut [S1]. {sentence}", "TRUE", 2) == "Schools were shut [S1]."


def test_true_verdict_keeps_contradicting_word_with_valid_citation():
    text = "Some posts falsely said every school shut for a week [S2]."
    assert drop_contradictions(text, "TRUE", 2) == text
    # A citation to a source that was not retrieved does not count.
    assert drop_contradictions("This is a hoax [S9].", "TRUE", 2) == ""


def test_false_verdict_keeps_cited_sentence():
    ctx = _ctx("FALSE")
    cited = "Alt News found the kidnapping message is a hoax [S1]."
    ctx.summary = cited
    ctx.harm_rationale = "False rumours like this have led to mob violence."
    ctx.reasoning_chain = [cited]
    remove_contradicting_text(ctx)
    assert ctx.summary == cited
    assert ctx.reasoning_chain == [cited]
    assert ctx.harm_rationale == "False rumours like this have led to mob violence."
