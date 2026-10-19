"""Agent 2 — Source Tracer (Nano + NewsAPI + Google Fact Check + DuckDuckGo).

Gathers evidence, scores source credibility by tier, asks the Nano model to judge
relevance/stance of each source, and produces a preliminary verdict.
"""
import asyncio

from agents.context import HONESTY_RULE, VERDICTS, AgentOutput, PipelineContext, clamp, norm_verdict, str_list
from models.groq_client import LLMJSONError, call_nano
from services.factcheck_service import search_factchecks
from services.news_service import domain_of, search_duckduckgo, search_newsapi

TIER_1 = {
    "reuters.com", "apnews.com", "afp.com", "bbc.com", "bbc.co.uk", "who.int", "un.org", "pib.gov.in",
    "altnews.in", "boomlive.in", "factly.in", "newschecker.in", "vishvasnews.com", "newsmobile.in",
    "snopes.com", "politifact.com", "fullfact.org", "factcheck.org", "leadstories.com", "nature.com",
    "thelancet.com", "nih.gov", "cdc.gov", "icmr.gov.in", "eci.gov.in", "rbi.org.in", "mohfw.gov.in",
}
TIER_2 = {
    "thehindu.com", "indianexpress.com", "hindustantimes.com", "ndtv.com", "timesofindia.indiatimes.com",
    "livemint.com", "scroll.in", "thewire.in", "theprint.in", "indiatoday.in", "thequint.com",
    "economictimes.indiatimes.com", "business-standard.com", "deccanherald.com", "newindianexpress.com",
    "aljazeera.com", "theguardian.com", "nytimes.com", "washingtonpost.com", "cnn.com", "bloomberg.com",
    "wikipedia.org", "britannica.com", "npr.org", "dw.com", "france24.com", "news18.com", "firstpost.com",
}
TIER_4 = {
    "facebook.com", "twitter.com", "x.com", "instagram.com", "youtube.com", "tiktok.com", "reddit.com",
    "quora.com", "medium.com", "blogspot.com", "wordpress.com", "sharechat.com", "t.me", "telegram.me",
    "whatsapp.com", "pinterest.com", "substack.com", "kooapp.com",
}
TIER_SCORE = {1: 0.95, 2: 0.8, 3: 0.55, 4: 0.3}


def tier_for(url: str, origin: str) -> int:
    if origin == "factcheck":
        return 1
    host = domain_of(url)

    def matches(domains: set[str]) -> bool:
        return any(host == d or host.endswith("." + d) for d in domains)

    if matches(TIER_1) or host.endswith(".gov.in") or host.endswith(".nic.in") or host.endswith(".gov"):
        return 1
    if matches(TIER_2):
        return 2
    if matches(TIER_4):
        return 4
    return 3


SYSTEM = """You are the Source Tracer agent of NemesisAI, a misinformation forensics system.
You judge evidence against a claim with the rigour of a professional fact-checker.
""" + HONESTY_RULE

PROMPT = """Today's date: {today}
CLAIM: {claim}
Claim type: {claim_type} | Satire signals: {satire}

EVIDENCE (numbered):
{evidence}

Tasks:
1. For every evidence item, rate "relevance" (0.0-1.0) and "stance" toward the claim:
   SUPPORTS = the source shows the claim is true; REFUTES = the source shows the claim is false; NEUTRAL = neither.
   Judge stance against the CLAIM as written, not against the rumour in general.
   Relevance means "useful for judging this claim": 0.9+ addresses this exact claim; 0.6-0.8 debunks or reports the same rumour, a close variant of it, or its central premise (e.g. a fact-check of earlier child-kidnapping rumours is relevant to a new child-kidnapping forward); 0.3-0.5 related background; below 0.3 unrelated.
2. Reach a preliminary verdict: one of {verdicts}.
   - FALSE: the core claim is wrong. TRUE: accurate. MISLEADING: real elements but distorted, out of context, exaggerated, or old media presented as new.
   - UNVERIFIED: no reliable evidence either way (typical for brand-new events with no coverage). SATIRE: obviously a joke or parody.
   - A tier-1 fact-check rating such as "False" or "Misleading" about this same claim is strong evidence.
   - Base the verdict on the evidence listed. If it is thin, return UNVERIFIED and say what is missing rather than relying on memory.
3. "confidence": probability (0.0-1.0) that your verdict is correct. Be calibrated: few relevant sources means lower confidence.
4. "contradictions_found": specific contradictions between the claim and the evidence (empty list if none).
   "missing_context": context needed to decide that the evidence does NOT provide (empty list if the evidence is sufficient).
   "evidence_gaps": short phrases naming what is missing, e.g. "no primary source found", "no official statement", "image origin unknown".

Return JSON:
{{"assessments": [{{"i": 1, "relevance": 0.0, "stance": "NEUTRAL"}}],
 "verdict": "...", "confidence": 0.0,
 "summary": "2-3 sentences explaining the verdict, citing source names",
 "reasoning": ["3-5 short reasoning steps"],
 "contradictions_found": [], "missing_context": [], "evidence_gaps": [],
 "fact": "one sentence stating what the evidence shows, naming its source",
 "key_source": "name of the single most authoritative source used, or empty if none"}}"""


async def _gather(ctx: PipelineContext) -> list[dict]:
    q = ctx.search_queries or [ctx.claim[:100]]
    stripped = q[0].lower().replace("fact check", "").strip()
    tasks = [
        search_factchecks(ctx.fact_check_query or stripped),
        search_newsapi(q[1] if len(q) > 1 else stripped),
        search_duckduckgo(q[0]),
    ]
    if stripped != ctx.fact_check_query.lower():
        tasks.append(search_factchecks(stripped))
    tasks += [search_duckduckgo(extra) for extra in q[1:3]]
    batches = await asyncio.gather(*tasks)

    seen: set[str] = set()
    items: list[dict] = []
    for batch in batches:
        for r in batch:
            key = r["url"].split("?")[0].rstrip("/")
            if key in seen:
                continue
            seen.add(key)
            r["tier"] = tier_for(r["url"], r["origin"])
            r["credibility"] = TIER_SCORE[r["tier"]]
            items.append(r)
    ctx.scanned_count = len(items)
    origin_rank = {"factcheck": 0, "newsapi": 1, "duckduckgo": 2}
    items.sort(key=lambda r: (r["tier"], origin_rank.get(r["origin"], 3)))
    return items[:14]


async def run(ctx: PipelineContext) -> AgentOutput:
    """Gather evidence, have the model assess it, and set the preliminary verdict.

    Evidence is only kept once the model has assessed it; if assessment fails, ctx.evidence is
    left empty so unassessed search hits can never count towards the uncertainty gate.
    """
    candidates = await _gather(ctx)
    ctx.evidence = candidates
    try:
        return await _assess(ctx, candidates)
    except Exception:
        ctx.evidence = []
        raise


async def _assess(ctx: PipelineContext, candidates: list[dict]) -> AgentOutput:
    """Model call + parsing for run()."""
    res = await call_nano(
        SYSTEM,
        PROMPT.format(
            today=ctx.today,
            claim=ctx.claim,
            claim_type=ctx.claim_type,
            satire=ctx.satire_signals,
            evidence=ctx.evidence_block(),
            verdicts=", ".join(VERDICTS),
        ),
        max_tokens=1400,
    )
    d = res.data

    by_index: dict[int, dict] = {}
    for a in d.get("assessments") or []:
        try:
            by_index[int(a.get("i", a.get("index", a.get("id"))))] = a
        except (TypeError, ValueError, AttributeError):
            continue
    if candidates and not by_index:
        # A missing assessment list is a malformed answer, not evidence of absence.
        raise LLMJSONError("Source tracer returned no usable relevance assessments")

    kept = []
    for i, ev in enumerate(candidates, 1):
        a = by_index.get(i, {})
        relevance = clamp(a.get("relevance"), default=0.0)
        if relevance < 0.35:
            continue
        stance = str(a.get("stance") or "NEUTRAL").upper()
        ev["stance"] = stance if stance in ("SUPPORTS", "REFUTES", "NEUTRAL") else "NEUTRAL"
        ev["relevance"] = relevance
        ev["credibility"] = round(TIER_SCORE[ev["tier"]] * (0.6 + 0.4 * relevance), 2)
        kept.append(ev)
    kept.sort(key=lambda e: (-e["credibility"], e["tier"]))
    ctx.evidence = kept[:8]

    ctx.verdict = norm_verdict(d.get("verdict"))
    ctx.confidence = clamp(d.get("confidence"), default=0.5)
    ctx.summary = str(d.get("summary") or "").strip()
    ctx.reasoning_chain = str_list(d.get("reasoning"), 6)
    ctx.fact = str(d.get("fact") or "").strip()
    ctx.key_source = str(d.get("key_source") or (ctx.evidence[0]["name"] if ctx.evidence else "")).strip()
    ctx.contradictions = str_list(d.get("contradictions_found"), 6)
    ctx.missing_context = str_list(d.get("missing_context"), 6)
    ctx.model_gaps = str_list(d.get("evidence_gaps"), 6)

    refutes = sum(1 for e in ctx.evidence if e["stance"] == "REFUTES")
    supports = sum(1 for e in ctx.evidence if e["stance"] == "SUPPORTS")
    preview = (
        f"{ctx.scanned_count} sources scanned · {len(ctx.evidence)} relevant · "
        f"{refutes} refute · {supports} support → {ctx.verdict} ({ctx.confidence:.0%})"
    )
    return AgentOutput(preview=preview, model=res.model, ms=res.ms)
