"""Deterministic scoring (master prompt section 4.6). Weights come from config/policy.yml.

component score = min(100, points(highest severity) + extra_per_finding * (n - 1))
overall score   = min(100, max(component scores) + corroboration_bonus * (number of OTHER
                  components scoring >= corroboration_threshold)) + analysis_failure_penalty per failure
label           = SAFE < suspicious <= SUSPICIOUS < dangerous <= DANGEROUS
override        = hidden text that is also an injection forces DANGEROUS
Every point is tied to a listed reason; there are no unexplained scores.
"""
from __future__ import annotations

from shield import settings
from shield.schemas import SEVERITY_RANK, Components, Overall


def cfg() -> dict:
    return settings.load("policy")["scoring"]


def severity_score(severities: list[str]) -> int:
    """Component score for a list of finding severities."""
    if not severities:
        return 0
    c = cfg()
    top = max(severities, key=lambda s: SEVERITY_RANK[s])
    return min(100, c["severity_points"][top] + c["extra_per_finding"] * (len(severities) - 1))


def claim_score(verdicts: list[str]) -> int:
    """Claims component score: the worst claim verdict, plus extra points for further bad claims."""
    if not verdicts:
        return 0
    c = cfg()
    points = sorted((c["claim_points"].get(v, 0) for v in verdicts), reverse=True)
    extra = c["extra_per_finding"] * sum(1 for p in points[1:] if p > 0)
    return min(100, points[0] + extra)


def hidden_injection(components: Components) -> bool:
    """True when hidden content itself carries an injection (an HC finding with instruction-like
    text), which forces DANGEROUS."""
    return any(f.instruction_like for f in components.hidden_content.findings)


def overall(components: Components, analysis_failures: list[str]) -> Overall:
    """Combine component scores into the overall label, score, confidence and reasons."""
    c = cfg()
    scores = {
        "hidden content": components.hidden_content.score,
        "prompt injection": components.injection.score,
        "sender authenticity": components.authenticity.score,
        "links": components.links.score,
        "scam patterns": components.scam.score,
        "false claims": components.claims.score,
    }
    top_name, top = max(scores.items(), key=lambda kv: kv[1])
    others_high = [n for n, s in scores.items() if n != top_name and s >= c["corroboration_threshold"]]
    score = min(100, top + c["corroboration_bonus"] * len(others_high))
    reasons: list[str] = []
    if top > 0:
        reasons.append(f"{top_name} scored {top}")
    if others_high:
        reasons.append(f"+{c['corroboration_bonus'] * len(others_high)} because {', '.join(others_high)} also scored "
                       f"{c['corroboration_threshold']} or more")
    if analysis_failures:
        penalty = c["analysis_failure_penalty"] * len(analysis_failures)
        score = min(100, score + penalty)
        reasons.append(f"+{penalty} because {len(analysis_failures)} part(s) of the analysis failed")

    forced = hidden_injection(components)
    if forced and score < c["labels"]["dangerous"]:
        score = c["labels"]["dangerous"]
    if forced:
        reasons.append("hidden text in this message tries to instruct an AI, which is always treated as dangerous")

    if forced or score >= c["labels"]["dangerous"]:
        label = "DANGEROUS"
    elif score >= c["labels"]["suspicious"]:
        label = "SUSPICIOUS"
    else:
        label = "SAFE"

    conf = c["confidence"]
    if forced:
        confidence = conf["override"]
    else:
        confidence = conf["base"] + conf["per_corroborating_component"] * len(others_high)
    confidence -= conf["failure_penalty"] * len(analysis_failures)
    confidence = round(max(conf["min"], min(conf["max"], confidence)), 2)
    return Overall(label=label, score=score, confidence=confidence, reasons=reasons)
