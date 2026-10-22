"""Agent 5 — Harm Assessor (Nano): classify harm type and score severity."""
from agents.context import HARM_TYPES, URGENCY, AgentOutput, PipelineContext, clamp, pick
from models.groq_client import call_nano

LEVEL_FLOOR = {"LOW": 1.5, "MEDIUM": 4.0, "HIGH": 6.5, "CRITICAL": 8.5}


def level_for(score: float) -> str:
    if score >= 8:
        return "CRITICAL"
    if score >= 6:
        return "HIGH"
    if score >= 3:
        return "MEDIUM"
    return "LOW"

SYSTEM = """You are the Harm Assessor agent of FactFlow. You estimate the real-world damage a piece of content
could cause if it keeps spreading in India, drawing on documented cases (mob lynchings after child-lifter
rumours, communal riots after recycled videos, deaths from fake cures). Respond with a single JSON object only."""

PROMPT = """CONTENT: \"\"\"{raw}\"\"\"
CLAIM: {claim}
VERDICT: {verdict} (model leaned {model_verdict} at {confidence:.0%})
Claim type: {claim_type} | Urgency: {urgency} | Platform: {platform}

Return JSON:
{{"harm_type": one of {harm_types},
 "harm_level": one of LOW, MEDIUM, HIGH, CRITICAL,
 "severity": number 0-10,
 "rationale": "one sentence explaining the most likely real-world harm",
 "at_risk": ["groups most likely to be harmed"]}}

Rules:
- Harm means what happens if people BELIEVE and ACT on the content. False rumours that call for action
  ("stop every outsider", "boycott them", "drink this") are the MOST dangerous, not the least.
- CRITICAL (8-10): could incite imminent violence against identifiable people or communities, or advice that can kill.
- HIGH (6-7.9): health, communal or electoral harm at scale. MEDIUM (3-5.9): financial scams, reputational harm. LOW (0-2.9): little harm.
- TRUE content usually has LOW harm unless it is being used to incite. SATIRE is LOW unless widely mistaken for fact.
- Use NONE as harm_type only when there is no plausible harm."""


async def run(ctx: PipelineContext) -> AgentOutput:
    res = await call_nano(
        SYSTEM,
        PROMPT.format(
            raw=ctx.raw_text[:1500],
            claim=ctx.claim,
            verdict=ctx.verdict,
            confidence=ctx.model_confidence if ctx.model_confidence is not None else 0.0,
            model_verdict=ctx.model_verdict or ctx.verdict,
            claim_type=ctx.claim_type,
            urgency=ctx.urgency,
            platform=ctx.platform,
            harm_types=", ".join(HARM_TYPES),
        ),
        max_tokens=500,
    )
    d = res.data
    ctx.harm_type = pick(d.get("harm_type"), HARM_TYPES, "NONE")
    stated = pick(d.get("harm_level"), URGENCY, "LOW")
    score = clamp(d.get("severity"), 0, 10, default=LEVEL_FLOOR[stated])
    # Never rate a CRITICAL-urgency falsehood below HIGH, and keep level and score consistent.
    if ctx.urgency == "CRITICAL" and (ctx.model_verdict or ctx.verdict) in ("FALSE", "MISLEADING"):
        score = max(score, LEVEL_FLOOR["HIGH"])
    ctx.harm_score = round(score, 1)
    ctx.harm_level = level_for(score)
    ctx.harm_rationale = str(d.get("rationale") or "").strip()
    return AgentOutput(
        preview=f"{ctx.harm_type} harm · {ctx.harm_level} · severity {ctx.harm_score:.1f}/10",
        model=res.model,
        ms=res.ms,
    )


def fallback(ctx: PipelineContext) -> None:
    mapping = {"VIOLENCE": "VIOLENCE", "HEALTH": "HEALTH", "COMMUNAL": "COMMUNAL", "ELECTORAL": "ELECTORAL",
               "POLITICAL": "ELECTORAL", "FINANCIAL": "FINANCIAL"}
    ctx.harm_type = mapping.get(ctx.claim_type, "NONE")
    ctx.harm_level = ctx.urgency if (ctx.model_verdict or ctx.verdict) in ("FALSE", "MISLEADING") else "LOW"
    ctx.harm_score = LEVEL_FLOOR[ctx.harm_level]
    ctx.harm_rationale = "Estimated from claim type and urgency (harm model unavailable)."
