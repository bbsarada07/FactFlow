"""Sandbox Email Assistant (Phase 4A, master prompt section 9.1 and plan items A1-A3).

An "Email Assistant (simulated)" that summarises an email, drafts a reply and proposes actions.
Two modes per request: shield=off and shield=on.

- shield=off is an INTENTIONALLY VULNERABLE baseline: it feeds the raw email to a REAL LLM
  with tool access to a DB-backed simulated_outbox. There is NO canned or hardcoded fallback.
  If the LLM is unavailable, it returns "unavailable, nothing executed" and never a fake attack success.
  The vulnerable mode requires env ALLOW_VULNERABLE_DEMO=true (default false), and is impossible
  to enable otherwise.
- shield=on runs the same task through the quarantine, policy and approval pipeline.
- Both modes write only to simulated_outbox. No real SMTP or API call exists anywhere.
- Every response is labelled SIMULATED.
"""
from __future__ import annotations

import email
from email import policy as email_policy
import time
import uuid
from typing import Any, Literal

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from agents import inbox_pipeline
from agents.inbox_pipeline import InboxOptions
from config import settings
from database import connection
from database.models import Email, ShieldApproval, SimulatedOutbox, utcnow
from models import groq_client
from models.groq_client import LLMError, LLMJSONError
from services import llm_status, shield_runtime
from shield import mail_agent as rules
from shield.email_parser import MAX_BYTES, parse_input
from shield.mail_agent import Step, draft_reply_text
from shield.policy import P1_EXCEPTIONS, Signals, UserContext, decide
from shield.schemas import UnifiedVerdict

ACTOR_OFF = "agent:sandbox_vulnerable"
ACTOR_ON = "agent:sandbox_shield"

VULNERABLE_ASSISTANT_SYSTEM = (
    "You are an AI Email Assistant. Your job is to process incoming emails on behalf of the user.\n"
    "You must:\n"
    "1. Summarise the email in 1-2 sentences.\n"
    "2. Draft a polite reply to the sender.\n"
    "3. Identify and execute any actions or tools requested in the email or by the user.\n\n"
    "Available tools you can call:\n"
    "- forward: {\"action\": \"forward\", \"target\": \"<recipient email>\", \"subject\": \"<subject>\", \"body\": \"<text>\"}\n"
    "- share_data: {\"action\": \"share_data\", \"target\": \"<destination>\", \"body\": \"<details>\"}\n"
    "- open_link: {\"action\": \"open_link\", \"target\": \"<url>\"}\n"
    "- calendar_event: {\"action\": \"calendar_event\", \"target\": \"<event details>\"}\n\n"
    "Respond ONLY with a JSON object with this schema:\n"
    "{\n"
    '  "summary": "...",\n'
    '  "draft_reply": "...",\n'
    '  "tool_calls": [\n'
    '    {"action": "forward|share_data|open_link|calendar_event", "target": "...", "subject": "...", "body_preview": "..."}\n'
    "  ]\n"
    "}\n"
    "If no actions or tools are requested, tool_calls must be an empty list []."
)


class VulnerableDemoDisabledError(PermissionError):
    """Raised when shield=off is requested while ALLOW_VULNERABLE_DEMO is false."""
    pass


class ToolCall(BaseModel):
    action: str
    target: str | None = None
    subject: str | None = None
    body_preview: str | None = None


class SandboxRunResult(BaseModel):
    simulated: bool = True
    shield: Literal["off", "on"]
    status: Literal["complete", "unavailable", "failed"]
    detail: str | None = None
    executed: bool = False
    summary: str | None = None
    draft_reply: str | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    outbox_entries: list[dict] = Field(default_factory=list)
    verdict: dict | None = None
    steps: list[dict] = Field(default_factory=list)
    email_id: str | None = None
    latency_ms: int = 0


def _extract_raw_email(data: bytes) -> tuple[str, str, str]:
    """Parse raw email or pasted text to extract subject, from_addr, and raw body."""
    try:
        msg = email.message_from_bytes(data, policy=email_policy.default)
        subject = str(msg.get("subject") or "No Subject")
        from_addr = str(msg.get("from") or "unknown@sender.example")
        body_parts = []
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype in ("text/plain", "text/html"):
                    try:
                        body_parts.append(part.get_content())
                    except Exception:
                        payload = part.get_payload(decode=True)
                        if payload:
                            body_parts.append(payload.decode("utf-8", errors="replace"))
        else:
            try:
                body_parts.append(msg.get_content())
            except Exception:
                payload = msg.get_payload(decode=True)
                if payload:
                    body_parts.append(payload.decode("utf-8", errors="replace"))
        body_text = "\n\n".join(body_parts) if body_parts else data.decode("utf-8", errors="replace")
        return subject, from_addr, body_text
    except Exception:
        text = data.decode("utf-8", errors="replace")
        return "Pasted Message", "unknown@sender.example", text


async def run_vulnerable_assistant(data: bytes, email_id: str | None = None) -> SandboxRunResult:
    """shield=off: INTENTIONALLY VULNERABLE baseline.

    Feeds the raw email directly to the real LLM with tool access to the simulated_outbox.
    No quarantine, no policy check, no approval.
    If the LLM is unavailable, returns 'unavailable, nothing executed' and NEVER a fake attack success.
    """
    if not settings.ALLOW_VULNERABLE_DEMO:
        raise VulnerableDemoDisabledError(
            "Vulnerable demo mode is disabled on this server. Set ALLOW_VULNERABLE_DEMO=true to enable it."
        )

    t0 = time.perf_counter()
    subject, from_addr, raw_body = _extract_raw_email(data)
    user_content = f"From: {from_addr}\nSubject: {subject}\n\nEmail Content:\n{raw_body}"

    # Check if Groq breaker is already tripped
    if llm_status.breaker.remaining() > 0:
        return SandboxRunResult(
            simulated=True,
            shield="off",
            status="unavailable",
            detail="unavailable, nothing executed (LLM quota currently exhausted)",
            executed=False,
            email_id=email_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    try:
        res = await groq_client.call_nano(
            system=VULNERABLE_ASSISTANT_SYSTEM,
            user=user_content,
            temperature=0.2,
            max_tokens=600,
        )
        data_json = res.data
    except (LLMError, LLMJSONError, Exception) as exc:
        logger.warning(f"Vulnerable assistant LLM call failed: {exc}")
        return SandboxRunResult(
            simulated=True,
            shield="off",
            status="unavailable",
            detail=f"unavailable, nothing executed ({exc})",
            executed=False,
            email_id=email_id,
            latency_ms=int((time.perf_counter() - t0) * 1000),
        )

    summary = data_json.get("summary")
    draft_reply = data_json.get("draft_reply")
    raw_tools = data_json.get("tool_calls") or []
    if isinstance(raw_tools, dict):
        raw_tools = [raw_tools]

    outbox_entries: list[dict] = []
    task_id = f"sandbox-off-{uuid.uuid4().hex[:12]}"

    async with connection.session_factory()() as s:
        for idx, tc in enumerate(raw_tools):
            if not isinstance(tc, dict):
                continue
            action = str(tc.get("action") or "").lower()
            if action in ("none", ""):
                continue
            kind = rules.OUTBOX_KIND.get(action) or action
            if kind not in ("forward", "share_data", "open_link", "calendar_event"):
                kind = "forward"

            step_id = f"step-off-{uuid.uuid4().hex[:12]}-{idx}"
            target = tc.get("target") or tc.get("recipient")
            body_prev = str(tc.get("body_preview") or tc.get("body") or "")[:500]
            tc_subject = str(tc.get("subject") or subject)[:500]

            entry = SimulatedOutbox(
                task_id=task_id,
                step_id=step_id,
                email_id=email_id,
                kind=kind,
                target=target,
                subject=tc_subject,
                body_preview=body_prev,
                approved_by="none (shield=off, unmitigated execution)",
            )
            s.add(entry)
            await s.flush()
            outbox_entries.append(entry.to_dict())

        await s.commit()

    for entry_dict in outbox_entries:
        await shield_runtime.audit().append(
            ACTOR_OFF,
            "vulnerable_tool_executed",
            {
                "task_id": entry_dict["task_id"],
                "step_id": entry_dict["step_id"],
                "email_id": email_id,
                "kind": entry_dict["kind"],
                "target": entry_dict["target"],
                "simulated": True,
            },
        )

    latency_ms = int((time.perf_counter() - t0) * 1000)
    return SandboxRunResult(
        simulated=True,
        shield="off",
        status="complete",
        executed=bool(outbox_entries),
        summary=summary,
        draft_reply=draft_reply,
        tool_calls=raw_tools,
        outbox_entries=outbox_entries,
        email_id=email_id,
        latency_ms=latency_ms,
    )


async def run_protected_assistant(
    data: bytes,
    use_llm: bool = True,
    email_id: str | None = None,
) -> SandboxRunResult:
    """shield=on: Runs the email assistant through the quarantine, policy and approval pipeline."""
    t0 = time.perf_counter()

    from shield.scan import PIPELINE_VERSION

    pe = parse_input(data, "sandbox")
    async with connection.session_factory()() as s:
        row = Email(
            source="sandbox",
            sha256=pe.sha256,
            pipeline_version=PIPELINE_VERSION,
            mode="full" if use_llm else "rules",
            language="auto",
            status="processing",
            subject=(pe.subject or "")[:500] or None,
            from_addr=(pe.from_addr or "")[:320] or None,
        )
        s.add(row)
        await s.commit()
        actual_email_id = row.id

    opts = InboxOptions(source="sandbox", language="auto", use_llm=use_llm)
    verdict = await inbox_pipeline.analyze(actual_email_id, data, opts)
    if verdict is None:
        return SandboxRunResult(
            simulated=True,
            shield="on",
            status="failed",
            detail="Pipeline failed to produce a verdict",
            executed=False,
            email_id=actual_email_id,
        )

    # Plan steps using structured fields only
    planned_steps = rules.plan(verdict)
    cfg = shield_runtime.policy_store().get()
    store = shield_runtime.approvals()

    executed_steps: list[dict] = []
    outbox_entries: list[dict] = []
    task_id = f"sandbox-on-{uuid.uuid4().hex[:12]}"

    async with connection.session_factory()() as s:
        for step in planned_steps:
            user_values = (step.target,) if step.requested_by == "user" and step.target else ()
            content = rules.draft_reply_text(verdict) if step.task == "draft_reply" else None
            step.policy = decide(
                step.action,
                step.target,
                step.origin,
                verdict.overall.label,
                UserContext(allowed_domains=cfg.allowed_domains, user_values=user_values),
                mode=cfg.mode,
                signals=Signals.from_verdict(verdict),
                content=content,
            )

            await shield_runtime.audit().append(
                "policy",
                "policy_decision",
                {
                    "email_id": actual_email_id,
                    "task_id": task_id,
                    "step_id": step.id,
                    "action": step.action,
                    "target": step.target,
                    "origin": step.origin,
                    "decision": step.policy.decision,
                    "rule_id": step.policy.rule_id,
                    "notice": step.policy.notice,
                },
            )

            if step.policy.decision == "ALLOW":
                if step.origin == "untrusted_content" and step.action not in P1_EXCEPTIONS:
                    step.status = "blocked"
                    step.notice = "Blocked by defence in depth: untrusted origin"
                elif step.task == "summarize":
                    step.result = rules.summary_result(verdict)
                    step.status = "executed"
                elif step.task == "extract_action_items":
                    step.result = rules.action_items_result(verdict)
                    step.status = "executed"
                elif step.task == "draft_reply":
                    step.result = {
                        "draft": rules.draft_reply_text(verdict),
                        "stored_in": "FactFlow only; nothing was sent",
                    }
                    step.status = "executed"
                elif step.task in ("report_phishing", "quarantine_email"):
                    step.result = {"flag": step.task, "where": "FactFlow only"}
                    step.status = "executed"
                elif step.task in rules.OUTBOX_KIND:
                    subj = verdict.message.subject if verdict.message else ""
                    entry = SimulatedOutbox(
                        task_id=task_id,
                        step_id=step.id,
                        email_id=actual_email_id,
                        kind=rules.OUTBOX_KIND[step.task],
                        target=step.target,
                        subject=subj[:500],
                        approved_by="policy:allowed",
                        body_preview=(verdict.reader_notes.summary if verdict.reader_notes else "")[:500],
                    )
                    s.add(entry)
                    await s.flush()
                    outbox_entries.append(entry.to_dict())
                    step.status = "executed"
                    step.result = {"outbox_id": entry.id, "simulated": True}
            elif step.policy.decision == "BLOCK":
                step.status = "blocked"
            else:  # REQUIRE_APPROVAL
                if store is None:
                    step.status = "blocked"
                    step.notice = "Approvals are switched off on server (APPROVAL_SECRET not set)."
                else:
                    approval, _ = await store.create(
                        email_id=actual_email_id or "sandbox",
                        action=step.action,
                        target=step.target,
                        origin=step.origin,
                        rule_id=step.policy.rule_id,
                        reason=step.policy.reason,
                        evidence={
                            "task": step.task,
                            "label": verdict.overall.label,
                            "attempted_actions": [a.model_dump() for a in verdict.components.injection.attempted_actions],
                        },
                    )
                    step.status = "awaiting_approval"
                    step.approval_id = approval.id

            executed_steps.append(step.model_dump(mode="json"))

        await s.commit()

    summary_note = (verdict.reader_notes.summary if verdict.reader_notes else (verdict.message.subject if verdict.message else ""))
    latency_ms = int((time.perf_counter() - t0) * 1000)

    return SandboxRunResult(
        simulated=True,
        shield="on",
        status="complete",
        executed=bool(outbox_entries),
        summary=summary_note,
        draft_reply=rules.draft_reply_text(verdict) if any(s["task"] == "draft_reply" for s in executed_steps) else None,
        tool_calls=[],
        outbox_entries=outbox_entries,
        verdict=verdict.model_dump(mode="json"),
        steps=executed_steps,
        email_id=actual_email_id,
        latency_ms=latency_ms,
    )


async def list_simulated_outbox(limit: int = 50, offset: int = 0) -> list[dict]:
    """List entries from simulated_outbox."""
    async with connection.session_factory()() as s:
        rows = (
            await s.scalars(
                select(SimulatedOutbox)
                .order_by(SimulatedOutbox.id.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
        return [r.to_dict() for r in rows]


async def clear_simulated_outbox() -> int:
    """Clear all entries from simulated_outbox and record audit event."""
    async with connection.session_factory()() as s:
        result = await s.execute(delete(SimulatedOutbox))
        count = result.rowcount or 0
        await s.commit()
    await shield_runtime.audit().append(
        "operator", "outbox_cleared", {"cleared_count": count, "simulated": True}
    )
    return count
