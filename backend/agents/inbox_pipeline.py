"""Agent 0 (inbox pipeline): emails and messages, end to end.

parse -> hidden content -> sender & links -> quarantined reader -> fact-check claims ->
harm & policy -> explain. Events use the same format as the claim pipeline (Run in
orchestrator.py), so the existing progress tracker shows the stages.

Only the quarantined reader (shield/quarantine.py) sees raw message text with a model. Claims it
extracts go through the existing six-agent fact-check pipeline, reusing stored verdicts from the
registry instead of re-checking. The explainer sees FactFlow's own findings plus short quoted
strings, never the message. Rules-only mode makes no model calls at all.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

from loguru import logger

from agents.context import LANGUAGE_NAMES
from agents.explainer import explain_email
from agents.orchestrator import Run, run_pipeline, shield_guard
from config import settings
from database import connection
from database.models import Claim, Email, new_slug, utcnow
from models.groq_client import Usage, call_nano, track_usage, usage_stage
from services import dns_checks, llm_status, shield_runtime
from services.registry import is_fresh, lookup_repeat
from services.safe_fetch import FetchBlocked, FetchError, expand_link
from services.safety import check_sensitive
from services.text_utils import input_hash, normalize, redact_pii, truncate
from shield import phishing, quarantine, scoring
from shield.email_parser import EmailInputError, parse_input
from shield.scan import RulesScan, finalize, rules_scan
from shield.schemas import SEVERITY_RANK, ClaimItem, LLMStatus, LLMUsage, ReaderNotes, UnifiedVerdict
from shield.whatsapp_reply import strip_message_text

STAGES = [
    {"index": 0, "name": "INTAKE & TRIAGE", "tier": "RULES", "role": "Reads the message structure"},
    {"index": 1, "name": "HIDDEN CONTENT", "tier": "RULES", "role": "Finds text you cannot see"},
    {"index": 2, "name": "SENDER & LINKS", "tier": "RULES", "role": "Checks who sent it and where links go"},
    {"index": 3, "name": "QUARANTINED READER", "tier": "NANO", "role": "Reads the text with no tools"},
    {"index": 4, "name": "FACT CHECK", "tier": "NANO", "role": "Checks claims with the six agents"},
    {"index": 5, "name": "HARM & POLICY", "tier": "RULES", "role": "Scores harm and gates actions"},
    {"index": 6, "name": "EXPLAINER", "tier": "NANO", "role": "Explains it in your language"},
]
CLAIM_VERDICTS = {"TRUE", "FALSE", "MISLEADING", "UNVERIFIED"}


@dataclass
class InboxOptions:
    source: str = "paste"
    language: str = "auto"
    use_llm: bool = True
    llm_disabled_by_server: bool = False  # full mode was asked for but INBOX_USE_LLM is off
    # False (WhatsApp): the stored and streamed verdict has the message text and excerpts removed;
    # the full verdict is only returned to the caller, in memory.
    store_message_text: bool = True


async def _q_llm(system: str, user: str, max_tokens: int) -> dict:
    res = await asyncio.wait_for(call_nano(system, user, max_tokens=max_tokens, temperature=0),
                                 timeout=settings.INBOX_LLM_TIMEOUT_SECONDS)
    return res.data


# ------------------------------------------------------------------------------ claims


async def _check_claim(text: str, hidden: bool, language: str, sem: asyncio.Semaphore) -> tuple[ClaimItem, bool, str | None]:
    """Fact-check one claim. Returns (item, answered_from_registry, failure)."""
    clean, _ = shield_guard(text)
    clean = truncate(redact_pii(clean), 300)
    if check_sensitive(clean):
        return ClaimItem(claim="[withheld under the private-person and self-harm rule]", verdict="UNVERIFIED",
                         credibility=0, hidden=hidden), False, None
    normalized = normalize(clean)
    async with connection.session_factory()() as s:
        found = await lookup_repeat(s, normalized, include_private=True)
        if found and is_fresh(found[0].created_at):
            c = found[0]
            return _item(c, clean, hidden), True, None
        claim = Claim(input_type="text", raw_input=clean, input_hash=input_hash(clean), normalized_text=normalized or None,
                      requested_language=language, platform="email", status="queued", slug=new_slug(), is_public=False)
        s.add(claim)
        await s.commit()
        claim_id = claim.id
    async with sem:
        await run_pipeline(claim_id)
    async with connection.session_factory()() as s:
        c = await s.get(Claim, claim_id)
        if c is None or c.status != "complete":
            failure = None if c is not None and c.status == "withheld" else "a claim could not be fact-checked"
            return ClaimItem(claim=clean, verdict="UNVERIFIED", credibility=0, autopsy_id=claim_id, hidden=hidden), False, failure
        return _item(c, clean, hidden), False, None


def _item(c: Claim, text: str, hidden: bool) -> ClaimItem:
    verdict = c.verdict if c.verdict in CLAIM_VERDICTS else "UNVERIFIED"
    return ClaimItem(claim=c.claim_text or text, autopsy_id=c.id, verdict=verdict,
                     credibility=int(round((c.confidence or 0) * 100)), hidden=hidden)


async def fact_check_claims(visible: list[str], hidden: list[str], language: str) -> tuple[list[ClaimItem], int, list[str]]:
    """Fact-check up to INBOX_MAX_CLAIMS claims (visible first). Returns (items, registry_hits, failures)."""
    picked, seen = [], set()
    for text, is_hidden in [*((t, False) for t in visible), *((t, True) for t in hidden)]:
        key = normalize(text)
        if key and key not in seen:
            seen.add(key)
            picked.append((text, is_hidden))
    picked = picked[: settings.INBOX_MAX_CLAIMS]
    sem = asyncio.Semaphore(settings.INBOX_FACTCHECK_CONCURRENCY)
    results = await asyncio.gather(*(_check_claim(t, h, language, sem) for t, h in picked))
    items = [r[0] for r in results]
    return items, sum(1 for r in results if r[1]), [r[2] for r in results if r[2]]


# ------------------------------------------------------------------------- explanation


def _facts_and_quotes(v: UnifiedVerdict) -> tuple[list[str], list[str]]:
    """FactFlow's findings (privileged) and the short strings that came from the message (untrusted)."""
    c = v.components
    facts = [f"overall result {v.overall.label}, score {v.overall.score}/100", *v.overall.reasons]
    facts += [f"hidden content {f.id}: {f.explanation_en}" for f in c.hidden_content.findings[:4]]
    if c.injection.rule_hits or (c.injection.llm or {}).get("is_injection"):
        facts.append("the message contains instructions aimed at AI assistants; FactFlow ignored them")
    facts += [f"sender: {s}" for s in c.authenticity.signals[:3]]
    facts += [f"sender address imitates {lk.brand}" for lk in c.authenticity.lookalikes[:2]]
    facts += [f"scam pattern: {d.name}" for d in c.scam.detectors[:3]]
    flagged = sorted({f for i in c.links.items for f in i.flags})
    if flagged:
        facts.append("links flagged: " + ", ".join(flagged))
    facts += [f"harm if acted on: {r}" for r in v.harm.reasons[:3]]
    quotes = [f"claim checked as {i.verdict}: {i.claim}" for i in c.claims.items]
    quotes += [f"it tried to make an assistant {a.action.replace('_', ' ')}" + (f" to {a.target}" if a.target else "")
               for a in c.injection.attempted_actions[:3]]
    return facts, quotes


# ----------------------------------------------------------------------------- network


async def _expand_shorteners(rs: RulesScan) -> None:
    async def one(item):
        try:
            resp = await expand_link(item.url if "://" in item.url else f"https://{item.url}")
        except (FetchBlocked, FetchError):
            return
        item.expanded_to = resp.url
        if resp.url != item.url:
            final_items, _ = phishing.analyze_links([], resp.url)
            for flag in (final_items[0].flags if final_items else []):
                if flag not in item.flags:
                    item.flags.append(flag)
            sevs = [s for s in (item.severity, final_items[0].severity if final_items else None) if s]
            item.severity = max(sevs, key=lambda s: SEVERITY_RANK[s]) if sevs else None

    await asyncio.gather(*(one(i) for i in rs.links if "shortener_not_expanded" in i.flags))


async def _dns(rs: RulesScan) -> None:
    for signal, severity in await dns_checks.sender_records(rs.parsed.from_domain):
        rs.auth.signals.append(signal)
        rs.auth.score = max(rs.auth.score, scoring.severity_score([severity]))


# -------------------------------------------------------------------------------- main


def _llm_status(opts: InboxOptions, problem: llm_status.LLMProblem | None) -> LLMStatus:
    if not opts.use_llm:
        if opts.llm_disabled_by_server:
            return LLMStatus(state="disabled", reason="the server runs rules-only (INBOX_USE_LLM is off)")
        return LLMStatus(state="not_used", reason="rules-only mode was requested")
    if problem is not None:
        return LLMStatus(state=problem.state, reason=problem.reason + "; this is a rules-only result",
                         retry_after_seconds=problem.retry_after_seconds)
    return LLMStatus(state="ok")


async def _record(v: UnifiedVerdict, source: str, sha256: str) -> None:
    """Audit trail for one verdict. Approvals are created by the mail agent for its own steps
    (services/mail_agent.py); the proposed actions here are the policy's view of the message."""
    log = shield_runtime.audit()
    await log.append("system", "email_received", {"email_id": v.email_id, "source": source, "sha256": sha256,
                                                  "mode": v.mode})
    await log.append("agent:shield", "scan_summary", {
        "email_id": v.email_id, "scores": {k: c["score"] for k, c in v.components.model_dump().items()},
        "hidden_findings": len(v.components.hidden_content.findings), "analysis_failures": len(v.analysis_failures)})
    for pa in v.proposed_actions:
        await log.append("policy", "policy_decision", {"email_id": v.email_id, "action": pa.action, "target": pa.target,
                                                      "origin": pa.origin, "decision": pa.policy.decision,
                                                      "rule_id": pa.policy.rule_id, "notice": pa.policy.notice})
    rec = await log.append("system", "verdict", {"email_id": v.email_id, "label": v.overall.label,
                                                 "score": v.overall.score, "input_type": v.input_type,
                                                 "llm_state": v.llm_status.state})
    v.audit_head_hash = rec.hash


async def analyze(email_id: str, raw: bytes, opts: InboxOptions) -> UnifiedVerdict | None:
    """Analyse one message; persists the verdict on the `emails` row `email_id` and streams progress."""
    run = Run(email_id, STAGES)
    meter: Usage = track_usage()
    t0 = time.perf_counter()
    stages: dict[str, int] = {}
    failures: list[str] = []
    try:
        await run.emit({"type": "start", "request_id": email_id, "input_type": "email", "agents": run.agents})
        await run.set_agent(0, "running", "Reading the message structure")
        t = time.perf_counter()
        try:
            pe = parse_input(raw, opts.source)
        except EmailInputError as exc:
            await run.set_agent(0, "failed", str(exc))
            await _fail(email_id, run, str(exc))
            return None
        stages["parse"] = round((time.perf_counter() - t) * 1000, 1)
        kind = "email with headers" if pe.has_headers else "pasted text"
        await run.set_agent(0, "complete", f"{kind} · {len(pe.attachments)} attachment(s)", ms=stages["parse"])

        await run.set_agent(1, "running", "Comparing what you see with what an AI would read")
        rs = await asyncio.to_thread(rules_scan, pe)
        stages.update(rs.stages)
        await run.set_agent(1, "complete", f"{len(rs.findings)} hidden-content finding(s) · {len(rs.view.diff)} hidden segment(s)",
                            ms=rs.stages.get("hidden_html", 0) + rs.stages.get("hidden_other", 0))
        await run.set_agent(2, "running", "Checking the sender, links and QR codes")
        t = time.perf_counter()
        extra = []
        if settings.ENABLE_LINK_EXPANSION:
            extra.append(_expand_shorteners(rs))
        if settings.ENABLE_DNS_CHECKS and pe.has_headers:
            extra.append(_dns(rs))
        if extra:
            await asyncio.gather(*extra)
            stages["network_checks"] = round((time.perf_counter() - t) * 1000, 1)
        flagged = sum(1 for i in rs.links if i.flags)
        await run.set_agent(2, "complete", f"SPF {rs.auth.spf} · DKIM {rs.auth.dkim} · DMARC {rs.auth.dmarc} · "
                            f"{flagged}/{len(rs.links)} link(s) flagged", ms=rs.stages.get("authenticity_links", 0))

        reading, claim_items, registry_hits, problem = None, [], 0, None
        if opts.use_llm and llm_status.breaker.remaining() > 0:
            problem = llm_status.LLMProblem("quota_exhausted", "the daily model quota is used up",
                                            llm_status.breaker.remaining())
            failures.append("the AI reading was skipped because the daily model quota is used up")
            for idx in (3, 4):
                await run.set_agent(idx, "skipped", "Daily model quota used up: rules-only result")
        elif opts.use_llm:
            await run.set_agent(3, "running", "Reading the untrusted text in quarantine")
            with usage_stage("quarantined_reader"):
                q = await quarantine.read(rs.view.visible_text, rs.hidden_text, _q_llm)
            stages["quarantined_reader"] = q.ms
            if q.failure:
                failures.append(q.failure)
                if q.error is not None:
                    problem = llm_status.classify(q.error)
                    if problem.state == "quota_exhausted":
                        llm_status.breaker.trip(problem.retry_after_seconds)
                else:
                    problem = llm_status.LLMProblem("llm_unavailable", "the AI reading returned an answer in the wrong format")
                await run.set_agent(3, "failed", q.failure + (f": {problem.reason}" if problem else ""), ms=q.ms)
            else:
                reading = q.reading
                n_claims = len(reading.claims.visible) + len(reading.claims.hidden)
                await run.set_agent(3, "complete", f"injection: {'yes' if reading.injection.is_injection else 'no'} · "
                                    f"{n_claims} checkable claim(s)", model=settings.NANO_MODEL, ms=q.ms)
            if reading and (reading.claims.visible or reading.claims.hidden):
                await run.set_agent(4, "running", "Fact-checking the claims")
                t = time.perf_counter()
                language = opts.language if opts.language != "auto" else reading.language
                with usage_stage("fact_check"):
                    claim_items, registry_hits, claim_failures = await fact_check_claims(
                        reading.claims.visible, reading.claims.hidden, language)
                failures += claim_failures
                stages["fact_check"] = round((time.perf_counter() - t) * 1000, 1)
                verdicts = ", ".join(i.verdict for i in claim_items)
                await run.set_agent(4, "complete", f"{len(claim_items)} claim(s): {verdicts} · {registry_hits} from the registry",
                                    ms=stages["fact_check"])
            else:
                await run.set_agent(4, "skipped", "AI reading unavailable" if problem else "No checkable claims")
        else:
            await run.set_agent(3, "skipped", "Rules-only mode")
            await run.set_agent(4, "skipped", "Rules-only mode")
        status = _llm_status(opts, problem)

        await run.set_agent(5, "running", "Scoring harm and checking every action against the policy")
        cfg = shield_runtime.policy_store().get()
        verdict = finalize(rs, email_id, mode=cfg.mode, reading=reading, claims=claim_items, extra_failures=failures,
                           run_mode="full" if opts.use_llm else "rules", source=opts.source,
                           allowed_domains=cfg.allowed_domains, llm_status=status)
        if reading is not None:
            verdict.reader_notes = ReaderNotes(summary=reading.summary, action_items=reading.action_items,
                                               reply_requested=reading.reply_requested, meeting=reading.meeting)
        stages["score_policy"] = verdict.latency_ms.per_stage.get("score_policy", 0)
        await run.set_agent(5, "complete", f"{verdict.overall.label} {verdict.overall.score}/100 · harm {verdict.harm.level}",
                            ms=stages["score_policy"])

        user_code = opts.language if opts.language != "auto" else (reading.language if reading else "en")
        verdict.explanation.user_language = user_code
        if opts.use_llm and llm_status.breaker.remaining() > 0:
            await run.set_agent(6, "skipped", "Daily model quota used up: English summary")
        elif opts.use_llm:
            await run.set_agent(6, "running", f"Writing the explanation in {LANGUAGE_NAMES.get(user_code, user_code)}")
            t = time.perf_counter()
            facts, quotes = _facts_and_quotes(verdict)
            try:
                with usage_stage("explainer"):
                    text, warning = await asyncio.wait_for(
                        explain_email(facts, quotes, verdict.overall.label, verdict.overall.score, user_code,
                                      LANGUAGE_NAMES.get(user_code, user_code)),
                        timeout=settings.INBOX_LLM_TIMEOUT_SECONDS)
                verdict.explanation.text, verdict.explanation.whatsapp_warning = text, warning
                stages["explainer"] = round((time.perf_counter() - t) * 1000, 1)
                await run.set_agent(6, "complete", "Explanation and WhatsApp warning ready", model=settings.NANO_MODEL,
                                    ms=stages["explainer"])
            except Exception as exc:  # noqa: BLE001 - the English listing stays as the explanation
                stages["explainer"] = round((time.perf_counter() - t) * 1000, 1)
                verdict.explanation.user_language = "en"
                explain_problem = llm_status.classify(exc)
                if explain_problem.state == "quota_exhausted":
                    llm_status.breaker.trip(explain_problem.retry_after_seconds)
                if verdict.llm_status.state == "ok":
                    verdict.llm_status = LLMStatus(state=explain_problem.state, retry_after_seconds=explain_problem.retry_after_seconds,
                                                   reason=f"the explanation could not be written: {explain_problem.reason}")
                await run.set_agent(6, "failed", f"Explanation failed ({explain_problem.reason}); showing the English summary")
        else:
            await run.set_agent(6, "skipped", "Rules-only mode: English summary")

        verdict.llm_usage = LLMUsage(**meter.as_dict(), claims_from_registry=registry_hits) if opts.use_llm else None
        t = time.perf_counter()
        await _record(verdict, opts.source, pe.sha256)
        stages["audit"] = round((time.perf_counter() - t) * 1000, 1)
        verdict.latency_ms.per_stage = stages
        verdict.latency_ms.total = int((time.perf_counter() - t0) * 1000)
        kept = verdict if opts.store_message_text else strip_message_text(verdict)
        await _store(email_id, kept, run)
        await run.emit({"type": "result", "progress": 100, "result": kept.model_dump(mode="json")})
        return verdict
    except Exception as exc:  # noqa: BLE001
        logger.exception(f"[{email_id}] inbox pipeline crashed")
        await _fail(email_id, run, f"Internal error: {type(exc).__name__}")
        return None


async def _store(email_id: str, v: UnifiedVerdict, run: Run) -> None:
    async with connection.session_factory()() as s:
        row = await s.get(Email, email_id)
        row.status, row.completed_at = "complete", utcnow()
        row.label, row.score = v.overall.label, v.overall.score
        row.verdict = v.model_dump(mode="json")
        row.latency_ms = v.latency_ms.total
        row.tokens = v.llm_usage.total_tokens if v.llm_usage else 0
        row.agent_log = run.agents
        await s.commit()


async def _fail(email_id: str, run: Run, message: str) -> None:
    async with connection.session_factory()() as s:
        row = await s.get(Email, email_id)
        if row is not None:
            row.status, row.error, row.completed_at, row.agent_log = "failed", message, utcnow(), run.agents
            await s.commit()
    await run.emit({"type": "error", "message": message})
