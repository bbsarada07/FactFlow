"""Agent 2 — Source Tracer (Nano + GDELT + NewsAPI + Google Fact Check + DuckDuckGo).

Gathers evidence with spelling/transliteration query variants, assigns credibility tiers
from the config allow-lists (never from the model), asks the Nano model to judge
relevance/stance of each item, and produces a preliminary verdict. Kept evidence gets IDs
S1..Sn that every later agent must cite. Provider failures are recorded for the evidence gaps.
"""
import asyncio
import re
from datetime import date, timedelta

from agents.context import HONESTY_RULE, VERDICTS, AgentOutput, PipelineContext, clamp, norm_verdict, str_list
from agents.grounding import assign_refs, remap_candidate_citations
from agents.query_variants import expand_queries, gdelt_query, variant_queries
from config import settings
from models.groq_client import LLMJSONError, call_nano
from services.factcheck_service import search_factchecks
from services.news_service import search_duckduckgo, search_gdelt, search_newsapi
from services.tiers import TIER_SCORE, tier_for

MAX_CANDIDATES = 16
_YEAR = re.compile(r"\b(19\d{2}|20\d{2})\b")

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
   - Base the verdict only on the evidence listed. If it is thin, return UNVERIFIED and say what is missing rather than relying on memory.
   - Never claim that an authority or outlet did NOT say something unless an evidence item shows that.
3. "confidence": probability (0.0-1.0) that your verdict is correct. Be calibrated: few relevant sources means lower confidence.
4. "contradictions_found": specific contradictions between the claim and the evidence (empty list if none).
   "missing_context": context needed to decide that the evidence does NOT provide (empty list if the evidence is sufficient).
   "evidence_gaps": short phrases naming what is missing, e.g. "no primary source found", "image origin unknown".
5. Citations: end every factual sentence in "summary", "reasoning" and "fact" with the number(s) of the evidence item(s) that support it in square brackets, e.g. [2] or [2, 5].

Return JSON:
{{"assessments": [{{"i": 1, "relevance": 0.0, "stance": "NEUTRAL"}}],
 "verdict": "...", "confidence": 0.0,
 "summary": "2-3 sentences explaining the verdict, each citing evidence numbers",
 "reasoning": ["3-5 short reasoning steps, each citing evidence numbers"],
 "contradictions_found": [], "missing_context": [], "evidence_gaps": [],
 "fact": "one sentence stating what the evidence shows, with its citation",
 "key_source": "name of the single most authoritative source used, or empty if none"}}"""


def news_window(claim_text: str, today: str) -> int | None:
    """Days of news history to search, or None (no date filter) when the claim names a year
    that ended before the window began."""
    start = date.fromisoformat(today) - timedelta(days=settings.NEWS_WINDOW_DAYS)
    years = [int(y) for y in _YEAR.findall(claim_text or "")]
    if years and min(years) < start.year:
        return None
    return settings.NEWS_WINDOW_DAYS


async def _gather(ctx: PipelineContext) -> list[dict]:
    """Run all providers in parallel over expanded queries; dedupe by URL; tier by allow-list."""
    queries = expand_queries(ctx.search_queries or [], ctx.claim)
    base = queries[0] if queries else ctx.claim[:100]
    stripped = base.lower().replace("fact check", "").strip()
    news_q = queries[1] if len(queries) > 1 else stripped
    errors = ctx.provider_errors

    tasks = [
        search_gdelt(gdelt_query(news_q) or gdelt_query(ctx.claim), news_window(f"{ctx.claim} {ctx.raw_text}", ctx.today), errors=errors),
        search_factchecks(ctx.fact_check_query or stripped, errors=errors),
        search_newsapi(news_q, errors=errors),
        search_duckduckgo(base, errors=errors),
    ]
    if stripped != (ctx.fact_check_query or "").lower():
        tasks.append(search_factchecks(stripped, errors=errors))
    tasks += [search_newsapi(v, errors=errors) for v in variant_queries(news_q, limit=1)]
    tasks += [search_duckduckgo(q, errors=errors) for q in queries[1:3]]
    batches = await asyncio.gather(*tasks)

    seen: set[str] = set()
    items: list[dict] = []
    for batch in batches:
        for r in batch:
            key = r["url"].split("?")[0].split("#")[0].rstrip("/").lower()
            if key in seen:
                continue
            seen.add(key)
            r["tier"] = tier_for(r["url"])
            r["credibility"] = TIER_SCORE[r["tier"]]
            items.append(r)
    # Deduplicate provider failure messages (several queries hit the same provider).
    ctx.provider_errors[:] = list(dict.fromkeys(errors))
    ctx.scanned_count = len(items)
    origin_rank = {"factcheck": 0, "gdelt": 1, "newsapi": 2, "duckduckgo": 3}
    items.sort(key=lambda r: (r["tier"], origin_rank.get(r["origin"], 4)))
    return items[:MAX_CANDIDATES]


async def run(ctx: PipelineContext) -> AgentOutput:
    """Gather evidence, have the model assess it, and set the preliminary verdict.

    Evidence is only kept once the model has assessed it; if assessment fails, ctx.evidence is
    left empty so unassessed search hits can never count towards the uncertainty gate.
    """
    candidates = await _gather(ctx)
    ctx.evidence = candidates
    if not candidates:
        ctx.evidence = []
        return _no_evidence(ctx, scanned=0)
    try:
        return await _assess(ctx, candidates)
    except Exception:
        ctx.evidence = []
        raise


def _no_evidence(ctx: PipelineContext, scanned: int) -> AgentOutput:
    """Zero relevant sources: the verdict is UNVERIFIED and the model may not lean either way."""
    ctx.verdict = "UNVERIFIED"
    ctx.confidence = 0.0
    ctx.summary = ""
    ctx.reasoning_chain = []
    ctx.contradictions = []
    ctx.fact = ""
    ctx.key_source = ""
    failed = f" · {len(ctx.provider_errors)} provider failure(s)" if ctx.provider_errors else ""
    return AgentOutput(preview=f"{scanned} sources scanned · 0 relevant{failed} → UNVERIFIED (no evidence)")


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
        max_tokens=1600,
    )
    d = res.data

    by_index: dict[int, dict] = {}
    for a in d.get("assessments") or []:
        try:
            by_index[int(a.get("i", a.get("index", a.get("id"))))] = a
        except (TypeError, ValueError, AttributeError):
            continue
    if not by_index:
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
        ev["candidate"] = i
        ev["credibility"] = round(TIER_SCORE[ev["tier"]] * (0.6 + 0.4 * relevance), 2)
        kept.append(ev)
    kept.sort(key=lambda e: (-e["credibility"], e["tier"]))
    ctx.evidence = kept[:8]
    mapping = assign_refs(ctx.evidence)

    if not ctx.evidence:
        return _no_evidence(ctx, scanned=ctx.scanned_count)

    ctx.verdict = norm_verdict(d.get("verdict"))
    ctx.confidence = clamp(d.get("confidence"), default=0.5)
    ctx.summary = remap_candidate_citations(str(d.get("summary") or ""), mapping)
    ctx.reasoning_chain = [remap_candidate_citations(s, mapping) for s in str_list(d.get("reasoning"), 6)]
    ctx.fact = remap_candidate_citations(str(d.get("fact") or ""), mapping)
    ctx.key_source = str(d.get("key_source") or ctx.evidence[0]["name"]).strip()
    ctx.contradictions = [remap_candidate_citations(s, mapping) for s in str_list(d.get("contradictions_found"), 6)]
    ctx.missing_context = str_list(d.get("missing_context"), 6)
    ctx.model_gaps = str_list(d.get("evidence_gaps"), 6)

    refutes = sum(1 for e in ctx.evidence if e["stance"] == "REFUTES")
    supports = sum(1 for e in ctx.evidence if e["stance"] == "SUPPORTS")
    preview = (
        f"{ctx.scanned_count} sources scanned · {len(ctx.evidence)} relevant · "
        f"{refutes} refute · {supports} support → {ctx.verdict} ({ctx.confidence:.0%})"
    )
    return AgentOutput(preview=preview, model=res.model, ms=res.ms)
