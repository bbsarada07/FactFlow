"""Agent 0 — Orchestrator.

Routes the input (text / URL / image), matches known patterns, runs the five
specialist agents in order, applies the honest-uncertainty gate (decide_verdict),
emits SSE events for every state change, degrades gracefully when an agent fails,
and persists the result to the public registry. Repeat claims are caught before the
pipeline starts (see services/registry.py and api/verify.py).
"""
import asyncio
import time
from collections.abc import Awaitable, Callable

from loguru import logger
from sqlalchemy import select

from agents import deep_reasoning, explainer, harm_assessor, intake_agent, source_tracer
from agents.context import AgentOutput, PipelineContext, clamp, norm_verdict
from agents.grounding import drop_contradictions, ground_list
from agents.uncertainty import build_checks, evidence_gaps, strong_source_count
from config import settings
from database import connection
from database.models import Claim, KnownPattern, Source, confidence_band, utcnow
from services import input_service
from services.event_bus import get_bus
from services.safety import PRIVATE_PERSON_MESSAGE, WITHHELD_LABEL, check_sensitive
from services.text_utils import input_hash, keyword_score, normalize, redact_pii, similarity, truncate

AGENTS = [
    {"index": 0, "name": "ORCHESTRATOR", "tier": "NANO", "role": "Routes and controls"},
    {"index": 1, "name": "INTAKE & TRIAGE", "tier": "NANO", "role": "Extracts core claim"},
    {"index": 2, "name": "SOURCE TRACER", "tier": "NANO", "role": "Finds evidence"},
    {"index": 3, "name": "DEEP REASONING", "tier": "ULTRA", "role": "Multi-hop analysis"},
    {"index": 4, "name": "EXPLAINER", "tier": "NANO", "role": "Translates verdict"},
    {"index": 5, "name": "HARM ASSESSOR", "tier": "NANO", "role": "Risk classification"},
]
PIPELINE_TIMEOUT = 170

_patterns: list[dict] | None = None


class PipelineError(RuntimeError):
    pass


def decide_verdict(evidence: list[dict], model_output: dict) -> dict:
    """Honest-uncertainty gate. Pure function: returns {verdict, confidence, reasons}.

    The model's verdict stands only when the evidence can carry it. UNVERIFIED is returned if
      - fewer than MIN_STRONG_SOURCES evidence items come from credibility tier 1 or 2, or
      - the model's confidence is below MIN_VERDICT_CONFIDENCE, or
      - the model found no contradictions but reports missing context.
    A model verdict of UNVERIFIED is never upgraded. When the gate downgrades a verdict,
    confidence is None (there is no calibrated confidence for "unverified").
    """
    verdict = norm_verdict(model_output.get("verdict"))
    raw_conf = model_output.get("confidence")
    confidence = None if raw_conf is None else clamp(raw_conf)
    contradictions = model_output.get("contradictions_found") or []
    missing = model_output.get("missing_context") or []
    strong = strong_source_count(evidence)

    reasons: list[str] = []
    if strong < settings.MIN_STRONG_SOURCES:
        plural = "s" if strong != 1 else ""
        reasons.append(
            f"Only {strong} high-credibility (tier 1-2) source{plural} found; "
            f"at least {settings.MIN_STRONG_SOURCES} are needed for a definite verdict."
        )
    if confidence is None or confidence < settings.MIN_VERDICT_CONFIDENCE:
        reasons.append("The analysis was not confident enough to give a definite verdict.")
    if not contradictions and missing:
        reasons.append("No contradiction was found, and key context is missing.")

    if verdict == "UNVERIFIED":
        return {
            "verdict": "UNVERIFIED",
            "confidence": confidence,
            "reasons": reasons or ["The evidence reviewed was not enough to confirm or refute the claim."],
        }
    if reasons:
        return {"verdict": "UNVERIFIED", "confidence": None, "reasons": reasons}
    return {"verdict": verdict, "confidence": confidence, "reasons": []}


def remove_contradicting_text(ctx: PipelineContext) -> None:
    """Final post-check on displayed text: drop sentences whose wording contradicts the verdict
    (see grounding.drop_contradictions) unless they cite a retrieved source. Covers the harm
    rationale, which no other grounding step sees."""
    n, verdict = len(ctx.evidence), ctx.verdict
    ctx.summary = drop_contradictions(ctx.summary, verdict, n)
    ctx.fact = drop_contradictions(ctx.fact, verdict, n)
    ctx.whatsapp_reply = drop_contradictions(ctx.whatsapp_reply, verdict, n)
    ctx.harm_rationale = drop_contradictions(ctx.harm_rationale, verdict, n)
    ctx.reasoning_chain = [t for t in (drop_contradictions(i, verdict, n) for i in ctx.reasoning_chain) if t]
    ctx.contradictions = [t for t in (drop_contradictions(i, verdict, n) for i in ctx.contradictions) if t]


def apply_gate(ctx: PipelineContext) -> None:
    """Run decide_verdict on the pipeline state and attach evidence gaps and next-step checks."""
    ctx.model_verdict = ctx.verdict
    ctx.model_confidence = ctx.confidence
    decision = decide_verdict(
        ctx.evidence,
        {
            "verdict": ctx.verdict,
            "confidence": ctx.confidence,
            "contradictions_found": ctx.contradictions,
            "missing_context": ctx.missing_context,
        },
    )
    ctx.verdict = decision["verdict"]
    ctx.confidence = decision["confidence"]
    ctx.gate_reasons = decision["reasons"]
    ctx.evidence_gaps = evidence_gaps(
        ctx.evidence, ctx.model_gaps + ctx.missing_context, ctx.input_type, ctx.provider_errors
    )
    ctx.checks_to_do = build_checks(ctx.claim, ctx.raw_text, ctx.input_type, ctx.claim_type)


class Run:
    """Tracks agent state for one request and publishes events."""

    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.bus = get_bus()
        self.t0 = time.perf_counter()
        self.agents = [{**a, "status": "waiting", "preview": "", "model": None, "ms": 0} for a in AGENTS]

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self.t0) * 1000)

    @property
    def progress(self) -> int:
        done = sum(1 for a in self.agents if a["status"] in ("complete", "skipped", "failed"))
        return round(done / len(self.agents) * 100)

    async def emit(self, event: dict) -> None:
        await self.bus.publish(self.request_id, {**event, "elapsed_ms": self.elapsed_ms})

    async def set_agent(self, idx: int, status: str, preview: str = "", model: str | None = None, ms: int = 0) -> None:
        a = self.agents[idx]
        a.update(status=status, preview=preview or a["preview"], model=model or a["model"], ms=ms or a["ms"])
        await self.emit({"type": "agent", "agent": idx, **a, "progress": self.progress})

    async def step(
        self, idx: int, fn: Callable[[PipelineContext], Awaitable[AgentOutput]], ctx: PipelineContext, running: str
    ) -> bool:
        """Run one agent with a single orchestrator-level retry. Returns success."""
        await self.set_agent(idx, "running", running)
        last_exc: Exception | None = None
        for attempt in range(2):
            try:
                out = await fn(ctx)
                await self.set_agent(idx, "complete", out.preview, out.model, out.ms)
                return True
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                logger.warning(f"[{self.request_id}] agent {idx} attempt {attempt + 1} failed: {exc!r}")
                if attempt == 0:
                    await self.set_agent(idx, "running", "Retrying after an upstream error…")
        await self.set_agent(idx, "failed", f"Failed: {truncate(str(last_exc), 140)}")
        return False


async def _known_patterns() -> list[dict]:
    global _patterns
    if _patterns is None:
        async with connection.session_factory()() as s:
            rows = (await s.scalars(select(KnownPattern))).all()
        _patterns = [{**p.to_dict(), "example_text": p.example_text, "keywords": p.keywords or []} for p in rows]
    return _patterns


async def match_patterns(text: str) -> list[dict]:
    scored = []
    for p in await _known_patterns():
        score = 0.5 * similarity(text, p["example_text"]) + 0.5 * keyword_score(text, p["keywords"])
        if score >= 0.35:
            scored.append({k: p[k] for k in ("slug", "name", "category", "typical_verdict")} | {"score": round(score, 2)})
    return sorted(scored, key=lambda x: -x["score"])[:2]


async def _prepare_input(claim: Claim) -> tuple[str, str, dict | None]:
    """Returns (text_to_analyse, routing_note, image_info). For screenshots, only the extracted
    text goes on to the reasoning agents; the reader label and visible cues are display-only."""
    note = claim.raw_input.strip()
    if claim.input_type == "image":
        if claim.image_data:
            b64, mime = input_service.validate_screenshot(claim.image_data)
        elif claim.source_url:
            b64, mime = await input_service.download_image(claim.source_url)
        else:
            raise input_service.InputError("Image input has no data")
        read = await input_service.read_image(b64, mime)
        text = redact_pii(read.text)
        image_info = {"reader": read.reader, "label": read.label, "cues": [redact_pii(c) for c in read.cues]}
        combined = f"{text}\n\nUser note: {note}" if note else text
        return combined, f"Image → text via {read.reader} ({len(text)} chars)", image_info
    if claim.input_type == "url" and claim.source_url:
        text = redact_pii(await input_service.fetch_url_text(claim.source_url))
        combined = f"{text}\n\nUser note: {note}" if note else text
        return combined, f"URL fetched ({len(text)} chars)", None
    if not note:
        raise input_service.InputError("No text to analyse")
    return note, f"Text input ({len(note)} chars)", None


async def _persist(ctx: PipelineContext, run: Run, raw_text: str) -> Claim:
    """Write the finished verdict, its uncertainty fields and evidence to the database."""
    async with connection.session_factory()() as s:
        claim = await s.get(Claim, ctx.request_id)
        claim.raw_input = raw_text
        claim.normalized_text = normalize(raw_text)
        claim.input_hash = input_hash(raw_text)
        claim.image_data = None
        claim.status = "complete"
        claim.completed_at = utcnow()
        claim.processing_ms = run.elapsed_ms
        claim.agent_log = run.agents
        claim.platform = ctx.platform
        claim.pattern_matches = ctx.pattern_matches
        claim.search_log = ctx.search_log
        claim.image_info = ctx.image_info
        claim.claim_text = ctx.claim
        claim.language = ctx.language
        claim.language_name = ctx.language_name
        claim.claim_type = ctx.claim_type
        claim.urgency = ctx.urgency
        claim.verdict = ctx.verdict
        claim.confidence = None if ctx.confidence is None else round(ctx.confidence, 3)
        claim.confidence_band = confidence_band(ctx.confidence)
        claim.model_verdict = ctx.model_verdict
        claim.model_confidence = None if ctx.model_confidence is None else round(ctx.model_confidence, 3)
        claim.gate_reasons = ctx.gate_reasons
        claim.missing_context = ctx.missing_context
        claim.evidence_gaps = ctx.evidence_gaps
        claim.checks_to_do = ctx.checks_to_do
        claim.correction = ctx.correction
        claim.summary = ctx.summary
        claim.reasoning_chain = ctx.reasoning_chain
        claim.contradictions = ctx.contradictions + [f"Manipulation marker: {m}" for m in ctx.manipulation_markers]
        claim.used_ultra = ctx.used_ultra
        claim.summary_local = ctx.summary_local
        claim.myth = ctx.myth
        claim.fact = ctx.fact
        claim.fact_source = ctx.fact_source
        claim.whatsapp_reply = ctx.whatsapp_reply
        claim.harm_type = ctx.harm_type
        claim.harm_level = ctx.harm_level
        claim.harm_score = ctx.harm_score
        claim.harm_rationale = ctx.harm_rationale
        for e in ctx.evidence:
            s.add(
                Source(
                    claim_id=ctx.request_id,
                    name=truncate(e["name"] or "Unknown", 250),
                    url=e["url"],
                    title=e.get("title"),
                    snippet=truncate(e.get("snippet") or "", 600),
                    origin=e["origin"],
                    tier=e["tier"],
                    credibility=e["credibility"],
                    stance=e.get("stance", "NEUTRAL"),
                    ref=e.get("ref"),
                    rating=e.get("rating"),
                    published_at=e.get("published_at"),
                )
            )
        await s.commit()
        await s.refresh(claim)
        return claim


async def _withhold(request_id: str, run: Run) -> None:
    """Store the claim privately under a generic label (no input text kept) and end the stream
    with the fixed message."""
    async with connection.session_factory()() as s:
        claim = await s.get(Claim, request_id)
        claim.raw_input = WITHHELD_LABEL
        claim.claim_text = WITHHELD_LABEL
        claim.input_hash = ""
        claim.normalized_text = None
        claim.image_data = None
        claim.source_url = None
        claim.is_public = False
        claim.status = "withheld"
        claim.completed_at = utcnow()
        claim.agent_log = []
        await s.commit()
    await run.emit({"type": "withheld", "message": PRIVATE_PERSON_MESSAGE})


async def _mark_failed(request_id: str, run: Run, message: str) -> None:
    async with connection.session_factory()() as s:
        claim = await s.get(Claim, request_id)
        if claim:
            claim.status = "failed"
            claim.error = message
            claim.image_data = None
            claim.completed_at = utcnow()
            claim.processing_ms = run.elapsed_ms
            claim.agent_log = run.agents
            await s.commit()
    await run.emit({"type": "error", "message": message})


async def _pipeline(request_id: str, run: Run) -> None:
    async with connection.session_factory()() as s:
        claim = await s.get(Claim, request_id)
        if claim is None:
            raise PipelineError(f"Unknown request {request_id}")
        claim.status = "processing"
        await s.commit()
        input_type, platform, language = claim.input_type, claim.platform, claim.requested_language
        slug = claim.slug
        snapshot = Claim(
            input_type=claim.input_type, raw_input=claim.raw_input, image_data=claim.image_data,
            source_url=claim.source_url,
        )

    await run.emit({"type": "start", "request_id": request_id, "input_type": input_type, "agents": run.agents})

    # ── Agent 0: routing ──────────────────────────────────────────────
    await run.set_agent(0, "running", f"Routing {input_type} input")
    try:
        raw_text, route_note, image_info = await _prepare_input(snapshot)
    except input_service.InputError as exc:
        await run.set_agent(0, "failed", str(exc))
        raise PipelineError(str(exc)) from exc

    # Private-person / self-harm rule for text extracted from a URL or image (text input is
    # checked in api/verify.py before the pipeline starts). Runs before intake and search.
    if check_sensitive(raw_text):
        await _withhold(request_id, run)
        return

    ctx = PipelineContext(
        request_id=request_id, raw_text=raw_text, input_type=input_type,
        requested_language=language or "auto", platform=platform or "web", slug=slug,
        image_info=image_info,
    )
    ctx.pattern_matches = await match_patterns(raw_text)

    pattern_note = f" · resembles '{ctx.pattern_matches[0]['name']}'" if ctx.pattern_matches else ""
    await run.set_agent(0, "complete", f"{route_note}{pattern_note} · dispatching 5 agents")

    # ── Agent 1: intake ───────────────────────────────────────────────
    if not await run.step(1, intake_agent.run, ctx, "Extracting core claim and language"):
        ctx.claim = truncate(raw_text, 300)
        ctx.search_queries = [truncate(raw_text, 80)]
        ctx.fact_check_query = ctx.search_queries[0]

    # ── Agent 2: source tracer ────────────────────────────────────────
    tracer_ok = await run.step(2, source_tracer.run, ctx, "Searching fact-checks, news and the open web")

    # ── Agent 3: deep reasoning (conditional) ─────────────────────────
    if not ctx.evidence:
        # Zero relevant sources: UNVERIFIED regardless of any model output; nothing to reason over.
        if not tracer_ok:
            ctx.provider_errors.append("Evidence assessment unavailable (model error)")
        ctx.verdict, ctx.confidence = "UNVERIFIED", 0.0
        ctx.summary, ctx.fact, ctx.reasoning_chain, ctx.contradictions = "", "", [], []
        await run.set_agent(3, "skipped", "No relevant sources to reason over")
    elif deep_reasoning.should_run(ctx):
        reason = "claim is CRITICAL" if ctx.urgency == "CRITICAL" else f"confidence {ctx.confidence:.0%} below threshold"
        await run.step(3, deep_reasoning.run, ctx, f"Escalated to Ultra: {reason}")
    else:
        await run.set_agent(3, "skipped", f"Not needed — confidence {ctx.confidence:.0%} and urgency {ctx.urgency}")

    # ── Honest-uncertainty gate, then the grounding rule for displayed reasons ──
    apply_gate(ctx)
    ctx.reasoning_chain = ground_list(ctx.reasoning_chain, len(ctx.evidence))
    ctx.contradictions = ground_list(ctx.contradictions, len(ctx.evidence))

    # ── Agents 4 & 5 in parallel ──────────────────────────────────────
    explain_ok, harm_ok = await asyncio.gather(
        run.step(4, explainer.run, ctx, f"Writing explanation in {ctx.output_language_name}"),
        run.step(5, harm_assessor.run, ctx, "Scoring real-world harm"),
    )
    if not explain_ok:
        explainer.fallback(ctx)
    if not harm_ok:
        harm_assessor.fallback(ctx)
    remove_contradicting_text(ctx)

    stored = await _persist(ctx, run, raw_text)
    await run.emit({"type": "result", "progress": 100, "result": stored.to_result()})


async def run_pipeline(request_id: str) -> None:
    run = Run(request_id)
    try:
        await asyncio.wait_for(_pipeline(request_id, run), timeout=PIPELINE_TIMEOUT)
    except asyncio.TimeoutError:
        await _mark_failed(request_id, run, f"Analysis timed out after {PIPELINE_TIMEOUT}s")
    except PipelineError as exc:
        await _mark_failed(request_id, run, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[{request_id}] pipeline crashed")
        await _mark_failed(request_id, run, f"Internal error: {exc.__class__.__name__}: {exc}")
