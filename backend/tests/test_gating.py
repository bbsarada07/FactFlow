"""decide_verdict: the honest-uncertainty gate."""
from agents.orchestrator import decide_verdict

TIER1 = {"tier": 1, "name": "Alt News", "origin": "factcheck"}
TIER2 = {"tier": 2, "name": "The Hindu", "origin": "newsapi"}
TIER3 = {"tier": 3, "name": "someblog.in", "origin": "duckduckgo"}


def model(verdict="FALSE", confidence=0.9, contradictions=("Police found no gang",), missing=()):
    """Model output in the shape the source tracer / deep reasoning agents produce."""
    return {
        "verdict": verdict,
        "confidence": confidence,
        "contradictions_found": list(contradictions),
        "missing_context": list(missing),
    }


def test_zero_sources_is_unverified():
    out = decide_verdict([], model())
    assert out["verdict"] == "UNVERIFIED"
    assert out["confidence"] is None
    assert any("0 high-credibility" in r for r in out["reasons"])


def test_two_tier1_sources_high_confidence_keeps_model_verdict():
    out = decide_verdict([TIER1, dict(TIER1, name="BOOM")], model("FALSE", 0.9))
    assert out == {"verdict": "FALSE", "confidence": 0.9, "reasons": []}


def test_low_confidence_is_unverified():
    out = decide_verdict([TIER1, TIER2], model("FALSE", 0.5))
    assert out["verdict"] == "UNVERIFIED"


def test_no_contradictions_but_missing_context_is_unverified():
    out = decide_verdict([TIER1, TIER2], model("TRUE", 0.95, contradictions=(), missing=("No official statement",)))
    assert out["verdict"] == "UNVERIFIED"
    assert any("missing" in r for r in out["reasons"])


def test_tier3_sources_do_not_count_as_strong():
    out = decide_verdict([TIER1, TIER3, TIER3], model("FALSE", 0.95))
    assert out["verdict"] == "UNVERIFIED"


def test_model_unverified_is_never_upgraded():
    out = decide_verdict([TIER1, TIER2, TIER1], model("UNVERIFIED", 0.95, contradictions=()))
    assert out["verdict"] == "UNVERIFIED"


def test_true_with_sufficient_evidence_passes():
    out = decide_verdict([TIER1, TIER2], model("TRUE", 0.9, contradictions=(), missing=()))
    assert out["verdict"] == "TRUE"


def test_missing_confidence_is_unverified():
    out = decide_verdict([TIER1, TIER2], model("FALSE", None))
    assert out["verdict"] == "UNVERIFIED"
