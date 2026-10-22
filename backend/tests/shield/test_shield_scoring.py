"""Deterministic scoring rule (section 4.6)."""
from shield import scoring
from shield.schemas import (
    AuthenticityComponent,
    ClaimsComponent,
    Components,
    HiddenContentComponent,
    HiddenFinding,
    InjectionComponent,
    LinksComponent,
    ScamComponent,
)


def comps(hidden=0, injection=0, auth=0, links=0, scam=0, claims=0, findings=()):
    return Components(
        hidden_content=HiddenContentComponent(score=hidden, findings=list(findings)),
        injection=InjectionComponent(score=injection), authenticity=AuthenticityComponent(score=auth),
        links=LinksComponent(score=links), scam=ScamComponent(score=scam), claims=ClaimsComponent(score=claims),
    )


def finding(instruction_like: bool) -> HiddenFinding:
    return HiddenFinding(id="HC-01", type="css_hidden", severity="critical" if instruction_like else "low",
                         location="div", hidden_text="x", explanation_en="x", instruction_like=instruction_like)


def test_severity_score():
    assert scoring.severity_score([]) == 0
    assert scoring.severity_score(["low"]) == 15
    assert scoring.severity_score(["low", "high"]) == 65
    assert scoring.severity_score(["critical"] * 10) == 100


def test_claim_score():
    assert scoring.claim_score([]) == 0
    assert scoring.claim_score(["TRUE"]) == 0
    assert scoring.claim_score(["FALSE", "MISLEADING"]) == 75


def test_overall_formula_and_labels():
    assert scoring.overall(comps(), []).label == "SAFE"
    o = scoring.overall(comps(scam=35), [])
    assert (o.score, o.label) == (35, "SUSPICIOUS")
    o = scoring.overall(comps(scam=60, links=50, auth=55), [])
    assert (o.score, o.label) == (80, "DANGEROUS") and any("+20" in r for r in o.reasons)


def test_boundaries():
    assert scoring.overall(comps(scam=24), []).label == "SAFE"
    assert scoring.overall(comps(scam=25), []).label == "SUSPICIOUS"
    assert scoring.overall(comps(scam=59), []).label == "SUSPICIOUS"
    assert scoring.overall(comps(scam=60), []).label == "DANGEROUS"


def test_analysis_failures_only_raise_the_score():
    clean = scoring.overall(comps(scam=15), [])
    failed = scoring.overall(comps(scam=15), ["LLM unavailable"])
    assert failed.score == clean.score + 15 and failed.label == "SUSPICIOUS" and failed.confidence < clean.confidence


def test_hidden_injection_forces_dangerous():
    o = scoring.overall(comps(hidden=15, findings=[finding(True)]), [])
    assert o.label == "DANGEROUS" and o.score >= 60 and o.confidence == 0.9
    assert scoring.overall(comps(hidden=15, findings=[finding(False)]), []).label == "SAFE"


def test_every_nonzero_score_has_a_reason():
    o = scoring.overall(comps(links=35), ["x"])
    assert o.score > 0 and len(o.reasons) == 2
