"""Agent 3 — Deep Reasoning (Ultra).

Runs when the preliminary confidence is below DEEP_REASONING_THRESHOLD or the
claim is CRITICAL. Performs multi-hop reasoning over sub-claims and evidence and
surfaces contradictions and manipulation markers.
"""
from agents.context import HONESTY_RULE, VERDICTS, AgentOutput, PipelineContext, clamp, norm_verdict, str_list
from config import settings
from models.groq_client import call_ultra

SYSTEM = """You are the Deep Reasoning agent of NemesisAI — a senior forensic fact-checker who has investigated
viral misinformation in India for years. You reason step by step, separate what the evidence shows from
assumptions, and never overstate certainty.
""" + HONESTY_RULE

PROMPT = """Today's date: {today}

ORIGINAL CONTENT (as received):
\"\"\"
{raw}
\"\"\"

CORE CLAIM: {claim}
Type: {claim_type} | Urgency: {urgency} | Language: {language}
Resembles known misinformation patterns: {patterns}

EVIDENCE (with stance judged by the Source Tracer):
{evidence}

Preliminary verdict from Source Tracer: {verdict} at {confidence:.0%} confidence.
Preliminary reasoning: {prelim}

Perform multi-hop analysis:
1. Decompose the claim into its sub-claims (who / what / where / when / causal link).
2. Test each sub-claim against the evidence listed.
3. Look for contradictions: between sources, between the claim and the evidence, and inside the content itself.
4. Look for manipulation markers: emotional urgency, "forward to all", fake authority, recycled media, missing dates, impossible numbers.
5. Decide the final verdict ({verdicts}). Overrule the preliminary verdict if the reasoning demands it.
   Rely on the evidence listed, not on memory. If it cannot settle the claim, return UNVERIFIED and name what is missing.

Return JSON:
{{"sub_claims": [{{"text": "...", "assessment": "supported | refuted | unsupported"}}],
 "reasoning_chain": ["4-6 numbered-in-order steps, each one or two sentences"],
 "contradictions_found": ["specific contradictions between the claim and the evidence; empty list if none"],
 "missing_context": ["context needed to decide that the evidence does not provide; empty list if sufficient"],
 "evidence_gaps": ["short phrases naming what is missing, e.g. 'no primary source found'"],
 "manipulation_markers": ["..."],
 "verdict": "...", "confidence": 0.0,
 "summary": "2-3 sentences for a general reader explaining what we found",
 "fact": "one sentence stating what is actually true",
 "key_source": "the most authoritative source name relied on"}}"""


def should_run(ctx: PipelineContext) -> bool:
    return ctx.confidence < settings.DEEP_REASONING_THRESHOLD or ctx.urgency == "CRITICAL"


async def run(ctx: PipelineContext) -> AgentOutput:
    res = await call_ultra(
        SYSTEM,
        PROMPT.format(
            today=ctx.today,
            raw=ctx.raw_text[:2500],
            claim=ctx.claim,
            claim_type=ctx.claim_type,
            urgency=ctx.urgency,
            language=ctx.language_name,
            patterns=", ".join(f"{p['name']} ({p['score']:.2f})" for p in ctx.pattern_matches) or "none",
            evidence=ctx.evidence_block(with_stance=True),
            verdict=ctx.verdict,
            confidence=ctx.confidence,
            prelim=" ".join(ctx.reasoning_chain) or ctx.summary,
            verdicts=", ".join(VERDICTS),
        ),
    )
    d = res.data

    ctx.used_ultra = True
    ctx.verdict = norm_verdict(d.get("verdict") or ctx.verdict)
    ctx.confidence = clamp(d.get("confidence"), default=ctx.confidence)
    ctx.summary = str(d.get("summary") or ctx.summary).strip()
    chain = str_list(d.get("reasoning_chain"), 7)
    if chain:
        ctx.reasoning_chain = chain
    markers = str_list(d.get("manipulation_markers"), 4)
    ctx.contradictions = str_list(d.get("contradictions_found") or d.get("contradictions"), 6)
    ctx.missing_context = str_list(d.get("missing_context"), 6)
    ctx.model_gaps = str_list(d.get("evidence_gaps"), 6)
    ctx.manipulation_markers = markers
    ctx.fact = str(d.get("fact") or ctx.fact).strip()
    ctx.key_source = str(d.get("key_source") or ctx.key_source).strip()

    sub = d.get("sub_claims") if isinstance(d.get("sub_claims"), list) else []
    preview = (
        f"{len(sub)} sub-claims tested · {len(ctx.contradictions)} contradictions · "
        f"{len(ctx.missing_context)} context gaps → "
        f"{ctx.verdict} ({ctx.confidence:.0%})"
    )
    return AgentOutput(preview=preview, model=res.model, ms=res.ms)
