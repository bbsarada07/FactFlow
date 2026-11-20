"""Runs the mail agent (rules in shield/mail_agent.py): sync a provider, process each new message
through the state machine, gate every step with the policy engine, and resume tasks when a human
decides an approval.

Effects stay inside FactFlow: notes on the task, flags on the email row, and the simulated outbox.
There is no code path that sends, deletes or modifies real mail.

Everything is per user: each user has their own Gmail connection, demo inbox, policy, rate limit, tasks,
approvals and outbox. Every function that reads or changes a task takes the owner's user_id and treats a task
owned by someone else exactly like one that does not exist.
"""
from __future__ import annotations

import asyncio
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from agents.inbox_pipeline import InboxOptions, analyze
from config import BASE_DIR, settings
from database import connection
from database.models import Email, MailTask, ShieldApproval, SimulatedOutbox, iso, utcnow
from services import gmail_account, runtime_settings, shield_runtime
from shield import mail_agent as rules

from shield.email_parser import EmailInputError, parse_input
from shield.mail_agent import Step
from shield.policy import P1_EXCEPTIONS, PolicyConfig, Signals, UserContext, decide
from shield.providers.base import MailProvider, ProviderAuthError, ProviderTemporaryError, RawMessageRef
from shield.providers.eml import EmlProvider
from shield.scan import PIPELINE_VERSION
from shield.schemas import Approval, PolicyDecision, UnifiedVerdict

ACTOR = "agent:mail"
CURSOR_OVERLAP = timedelta(minutes=2)
DEMO_DIR = BASE_DIR / "data" / "demo_emails"
_eml: dict[str, EmlProvider] = {}  # user_id -> that user's demo inbox (shared demo files + their own uploads)
_locks: dict[str, asyncio.Lock] = {}
_recent: dict[str, deque[float]] = {}  # user_id -> processing times in the last minute


class SyncReport(BaseModel):
    provider: str
    listed: int = 0
    new_tasks: list[str] = Field(default_factory=list)
    duplicates: int = 0
    deferred: int = 0
    failed: int = 0
    errors: list[str] = Field(default_factory=list)
    reconnect_required: bool = False


def eml_provider(user_id: str) -> EmlProvider:
    """This user's demo inbox: the shared demo .eml files plus only their own uploads."""
    if user_id not in _eml:
        _eml[user_id] = EmlProvider(DEMO_DIR)
    return _eml[user_id]


async def active_provider(user_id: str) -> tuple[str, MailProvider | None]:
    """(name, provider) for this user. 'auto' uses their Gmail when connected and their demo inbox otherwise."""
    choice = await runtime_settings.mail_provider(user_id)
    if choice in ("auto", "gmail"):
        gmail = await gmail_account.provider(user_id)
        if gmail is not None or choice == "gmail":
            return "gmail", gmail
        if (await gmail_account.status(user_id))["reconnect_required"]:
            return "gmail", None  # say "reconnect" rather than quietly reading the demo inbox
    return "eml", eml_provider(user_id)


def _rate_ok(user_id: str) -> bool:
    """Per-user, per-minute cap on messages processed (MAIL_AGENT_MAX_PER_MINUTE)."""
    now = time.monotonic()
    recent = _recent.setdefault(user_id, deque())
    while recent and now - recent[0] >= 60:
        recent.popleft()
    if len(recent) >= settings.MAIL_AGENT_MAX_PER_MINUTE:
        return False
    recent.append(now)
    return True


def _lock(task_id: str) -> asyncio.Lock:
    return _locks.setdefault(task_id, asyncio.Lock())


# ------------------------------------------------------------------------- persistence


async def _transition(task: MailTask, new: str, s, **payload) -> None:
    rules.check_transition(task.state, new)
    task.transitions = [*(task.transitions or []), {"state": new, "at": utcnow().isoformat()}]
    task.state = new
    await s.commit()
    await shield_runtime.audit().append(ACTOR, "task_state", {
        "email_id": task.email_id, "task_id": task.id, "state": new, "provider": task.provider, **payload},
        user_id=task.user_id)


def _steps(task: MailTask) -> list[Step]:
    return [Step.model_validate(x) for x in (task.steps or [])]


def _put_steps(task: MailTask, steps: list[Step]) -> None:
    task.steps = [x.model_dump(mode="json") for x in steps]


async def _verdict(s, email_id: str | None) -> UnifiedVerdict | None:
    row = await s.get(Email, email_id) if email_id else None
    return UnifiedVerdict.model_validate(row.verdict) if row is not None and row.verdict else None


# ---------------------------------------------------------------------------- policy


def _decide(step: Step, v: UnifiedVerdict, cfg: PolicyConfig) -> PolicyDecision:
    user_values = (step.target,) if step.requested_by == "user" and step.target else ()
    content = rules.draft_reply_text(v) if step.task == "draft_reply" else None
    return decide(step.action, step.target, step.origin, v.overall.label,
                  UserContext(allowed_domains=cfg.allowed_domains, user_values=user_values),
                  mode=cfg.mode, signals=Signals.from_verdict(v), content=content)


async def _execute(s, task: MailTask, steps: list[Step], step: Step, v: UnifiedVerdict,
                   approved_by: str | None = None) -> None:
    """Carry out one allowed or approved step, inside FactFlow only. Runs at most once per step.

    The effect, the step's new status and the task's steps are committed together, before the
    audit entry is written (one writer at a time, as SQLite requires)."""
    if step.status == "executed":
        return
    if step.origin == "untrusted_content" and step.action not in P1_EXCEPTIONS:
        raise PermissionError("a step requested by the message itself is never carried out")  # defence in depth
    if step.task == "summarize":
        step.result = rules.summary_result(v)
    elif step.task == "extract_action_items":
        step.result = rules.action_items_result(v)
    elif step.task == "draft_reply":
        step.result = {"draft": rules.draft_reply_text(v), "stored_in": "FactFlow only; nothing was sent"}
    elif step.task in ("report_phishing", "quarantine_email"):
        email = await s.get(Email, task.email_id)
        if step.task == "report_phishing":
            email.reported_phishing = True
        else:
            email.quarantined = True
        step.result = {"flag": step.task, "where": "FactFlow only; the mailbox was not changed"}
    elif step.task in rules.OUTBOX_KIND:
        subject = v.message.subject if v.message else ""
        entry = SimulatedOutbox(user_id=task.user_id, task_id=task.id, step_id=step.id, email_id=task.email_id,
                                kind=rules.OUTBOX_KIND[step.task],
                                target=step.target, subject=subject[:500], approved_by=approved_by,
                                body_preview=(v.reader_notes.summary if v.reader_notes else "")[:500])
        s.add(entry)
        await s.flush()
        step.result = {"outbox_id": entry.id, "simulated": True, "note": "Simulated: nothing was sent or opened."}
    else:
        raise PermissionError(f"{step.task} cannot be executed")
    step.status = "executed"
    step.notice = step.policy.notice if step.policy else None
    _put_steps(task, steps)
    await s.commit()
    await shield_runtime.audit().append(ACTOR, "step_executed", {
        "email_id": task.email_id, "task_id": task.id, "step_id": step.id, "task": step.task, "target": step.target,
        "approved_by": approved_by, "notice": step.notice}, user_id=task.user_id)


async def _gate(s, task: MailTask, steps: list[Step], v: UnifiedVerdict) -> None:
    """Policy-check planned steps, then execute, park for approval, or block each one."""
    store = shield_runtime.approvals()
    cfg = await runtime_settings.policy_for(task.user_id)
    for step in steps:
        if step.status != "planned":
            continue
        step.policy = _decide(step, v, cfg)
        await shield_runtime.audit().append("policy", "policy_decision", {
            "email_id": task.email_id, "task_id": task.id, "step_id": step.id, "action": step.action,
            "target": step.target, "origin": step.origin, "decision": step.policy.decision,
            "rule_id": step.policy.rule_id, "notice": step.policy.notice}, user_id=task.user_id)
    _put_steps(task, steps)
    await _transition(task, "POLICY_CHECKED", s, steps=len(steps))
    for step in steps:
        if step.status != "planned":
            continue
        if step.policy.decision == "ALLOW":
            await _execute(s, task, steps, step, v)
        elif step.policy.decision == "BLOCK":
            step.status = "blocked"
        elif store is None:
            step.status = "blocked"
            step.notice = "Approvals are switched off on the server (APPROVAL_SECRET is not set), so this step was not run."
        else:
            approval, _token = await store.create(
                user_id=task.user_id, email_id=task.email_id, action=step.action, target=step.target, origin=step.origin,
                rule_id=step.policy.rule_id, reason=step.policy.reason,
                evidence={"task": step.task, "label": v.overall.label, "llm_state": v.llm_status.state,
                          "hidden_text": [d.text[:200] for d in v.visible_vs_raw.diff[:3]],
                          "attempted_actions": [a.model_dump() for a in v.components.injection.attempted_actions]})
            step.status, step.approval_id = "awaiting_approval", approval.id
    _put_steps(task, steps)
    await _settle(s, task, steps)


async def _settle(s, task: MailTask, steps: list[Step]) -> None:
    state = rules.state_after_policy(steps)
    if task.state != state:
        await _transition(task, state, s, steps=[{"task": x.task, "status": x.status} for x in steps])
    if state != "AWAITING_APPROVAL":
        await _transition(task, "DONE", s)


# ------------------------------------------------------------------------------- tasks


async def _exists(user_id: str, provider: str, message_id: str) -> bool:
    async with connection.session_factory()() as s:
        return await s.scalar(select(MailTask.id).where(MailTask.user_id == user_id, MailTask.provider == provider,
                                                        MailTask.message_id == message_id)) is not None


async def _owned_task(s, task_id: str, user_id: str) -> MailTask | None:
    """The task if it belongs to user_id; someone else's task is treated as missing."""
    task = await s.get(MailTask, task_id)
    return task if task is not None and task.user_id == user_id else None


async def process(user_id: str, provider: MailProvider, ref: RawMessageRef, *, source: str | None = None,
                  use_llm: bool | None = None) -> str | None:
    """Run one new message of `user_id` through the whole state machine. Returns the task id (None if another
    worker already took this message)."""
    raw = await provider.fetch_raw(ref.message_id)
    mode = (await runtime_settings.policy_for(user_id)).mode
    async with connection.session_factory()() as s:
        task = MailTask(user_id=user_id, provider=provider.name, message_id=ref.message_id, state="FETCHED",
                        policy_mode=mode, transitions=[{"state": "FETCHED", "at": utcnow().isoformat()}])
        s.add(task)
        try:
            await s.commit()
        except IntegrityError:
            return None
        task_id = task.id
    await shield_runtime.audit().append(ACTOR, "task_state", {"email_id": None, "task_id": task_id, "state": "FETCHED",
                                                             "provider": provider.name, "message_id": ref.message_id},
                                        user_id=user_id)
    async with _lock(task_id), connection.session_factory()() as s:
        task = await s.get(MailTask, task_id)
        try:
            pe = parse_input(raw, source or provider.name)
        except EmailInputError as exc:
            task.error = str(exc)
            await _transition(task, "FAILED", s, error=str(exc))
            return task_id
        email = Email(user_id=user_id, source=source or ("gmail" if provider.name == "gmail" else "demo"), sha256=pe.sha256,
                      pipeline_version=PIPELINE_VERSION, mode="full", status="processing", subject=pe.subject[:500] or None,
                      from_addr=pe.from_addr[:320] or None, provider=provider.name, provider_message_id=ref.message_id)
        s.add(email)
        await s.flush()
        task.email_id = email.id
        await _transition(task, "PARSED", s, has_headers=pe.has_headers, attachments=len(pe.attachments))

        llm = settings.INBOX_USE_LLM if use_llm is None else use_llm
        email.mode = "full" if llm else "rules"
        await s.commit()
        verdict = await analyze(email.id, raw, InboxOptions(source=email.source, use_llm=llm, user_id=user_id,
                                                           llm_disabled_by_server=use_llm is None and not settings.INBOX_USE_LLM))
        await s.refresh(email)  # analyze() wrote the verdict through its own session
        if verdict is None:
            task.error = "the analysis failed"
            await _transition(task, "FAILED", s, error=task.error)
            return task_id
        await _transition(task, "SCANNED", s, label=verdict.overall.label, score=verdict.overall.score,
                          llm_state=verdict.llm_status.state)
        steps = rules.plan(verdict)
        _put_steps(task, steps)
        await _transition(task, "PLANNED", s, steps=[{"task": x.task, "requested_by": x.requested_by} for x in steps])
        await _gate(s, task, steps, verdict)
        return task_id


async def sync(user_id: str, provider: MailProvider, *, use_llm: bool | None = None) -> SyncReport:
    """Fetch this user's new messages from `provider` and process them (at most MAIL_MAX_PER_SYNC, rate-capped)."""
    report = SyncReport(provider=provider.name)
    started = datetime.now(timezone.utc)
    since = await gmail_account.cursor(user_id) if provider.name == "gmail" else None
    try:
        refs = await provider.list_new(since)
    except ProviderAuthError as exc:
        report.reconnect_required, report.errors = True, [str(exc)]
        if provider.name == "gmail":
            await gmail_account.mark(user_id, "reconnect_required", str(exc))
        return report
    except ProviderTemporaryError as exc:
        report.errors = [str(exc)]
        if provider.name == "gmail":
            await gmail_account.record_sync(user_id, None, str(exc))
        return report
    refs = refs[: settings.MAIL_MAX_PER_SYNC]
    report.listed = len(refs)
    for ref in refs:
        if await _exists(user_id, provider.name, ref.message_id):
            report.duplicates += 1
            continue
        if not _rate_ok(user_id):
            report.deferred += 1
            continue
        try:
            task_id = await process(user_id, provider, ref, use_llm=use_llm)
        except ProviderAuthError as exc:
            report.reconnect_required = True
            report.errors.append(str(exc))
            if provider.name == "gmail":
                await gmail_account.mark(user_id, "reconnect_required", str(exc))
            break
        except (ProviderTemporaryError, KeyError) as exc:
            report.failed += 1
            report.errors.append(f"{ref.message_id}: {exc}")
            continue
        if task_id is None:
            report.duplicates += 1
        else:
            report.new_tasks.append(task_id)
    if provider.name == "gmail" and not report.reconnect_required:
        keep_cursor = report.deferred or report.failed
        await gmail_account.record_sync(user_id, None if keep_cursor else started - CURSOR_OVERLAP,
                                        "; ".join(report.errors)[:300] or None)
    await expire_due()
    return report


async def request_step(user_id: str, task_id: str, task_name: str, target: str | None, actor: str = "user") -> dict:
    """A step the user asks for on one of their analysed messages (e.g. forward it). The target counts as the
    user's own (they typed it); everything else about the step is checked as usual."""
    if task_name not in rules.USER_REQUESTABLE:
        raise ValueError(f"{task_name} cannot be requested")
    if task_name in rules.NEEDS_TARGET and not (target or "").strip():
        raise ValueError(f"{task_name} needs a target")
    async with _lock(task_id), connection.session_factory()() as s:
        task = await _owned_task(s, task_id, user_id)
        if task is None:
            raise KeyError(task_id)
        if task.state != "DONE":
            raise RuntimeError(f"the task is {task.state}; wait until it is DONE")
        v = await _verdict(s, task.email_id)
        if v is None:
            raise RuntimeError("the task has no verdict")
        steps = _steps(task)
        step = rules.new_step(task_name, target=(target or "").strip() or None, requested_by="user")
        steps.append(step)
        _put_steps(task, steps)
        await _transition(task, "PLANNED", s, requested_by=f"human:{actor}", step_task=task_name, target=step.target)
        await _gate(s, task, steps, v)
        return await _task_view(s, task)


async def _task_id_for(approval: Approval) -> str | None:
    async with connection.session_factory()() as s:
        for task in (await s.scalars(select(MailTask).where(MailTask.email_id == approval.email_id))).all():
            if any(x.get("approval_id") == approval.id for x in task.steps or []):
                return task.id
    return None


async def task_for_approval(approval: Approval, user_id: str) -> dict | None:
    """The task view of the task whose step waits (or waited) on `approval`."""
    task_id = await _task_id_for(approval)
    return await task_view(task_id, user_id) if task_id else None


async def on_approval_decided(approval: Approval) -> None:
    """Resume the task that waits on `approval`: run the step if approved, end it otherwise."""
    task_id = await _task_id_for(approval)
    if task_id is None:
        return
    async with _lock(task_id), connection.session_factory()() as s:
        task = await s.get(MailTask, task_id)
        steps = _steps(task)
        step = next(x for x in steps if x.approval_id == approval.id)
        if step.status != "awaiting_approval":
            return
        if approval.status == "approved":
            v = await _verdict(s, task.email_id)
            await _execute(s, task, steps, step, v, approved_by=approval.decided_by)
        else:
            step.status = "denied" if approval.status == "denied" else "expired"
            await shield_runtime.audit().append(ACTOR, f"step_{step.status}", {
                "email_id": task.email_id, "task_id": task.id, "step_id": step.id, "task": step.task},
                user_id=task.user_id)
        _put_steps(task, steps)
        if task.state == "AWAITING_APPROVAL" and rules.state_after_policy(steps) != "AWAITING_APPROVAL":
            await _settle(s, task, steps)
        else:
            await s.commit()


async def expire_due() -> int:
    """Expire approvals past their time and end the steps waiting on them."""
    now = datetime.now(timezone.utc)
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(ShieldApproval).where(ShieldApproval.status == "pending"))).all()
        due = [r for r in rows if (r.expires_at if r.expires_at.tzinfo else r.expires_at.replace(tzinfo=timezone.utc)) <= now]
        for r in due:
            r.status = "expired"
        await s.commit()
    store = shield_runtime.approvals()
    for r in due:
        approval = await store.get(r.id) if store else None
        if approval is not None:
            await on_approval_decided(approval)
    return len(due)


# ------------------------------------------------------------------------------- views


async def _task_view(s, task: MailTask) -> dict:
    email = await s.get(Email, task.email_id) if task.email_id else None
    return {"task_id": task.id, "provider": task.provider, "message_id": task.message_id, "email_id": task.email_id,
            "state": task.state, "policy_mode": task.policy_mode, "error": task.error,
            "created_at": iso(task.created_at), "updated_at": iso(task.updated_at),
            "subject": email.subject if email else None, "from_addr": email.from_addr if email else None,
            "label": email.label if email else None, "score": email.score if email else None,
            "quarantined": bool(email.quarantined) if email else False,
            "reported_phishing": bool(email.reported_phishing) if email else False,
            "steps": task.steps or [], "transitions": task.transitions or []}


async def task_view(task_id: str, user_id: str) -> dict | None:
    async with connection.session_factory()() as s:
        task = await _owned_task(s, task_id, user_id)
        return await _task_view(s, task) if task else None


async def list_tasks(user_id: str, limit: int = 30, offset: int = 0, state: str | None = None) -> dict:
    from sqlalchemy import func

    async with connection.session_factory()() as s:
        q = select(MailTask).where(MailTask.user_id == user_id)
        count = select(func.count()).select_from(MailTask).where(MailTask.user_id == user_id)
        if state:
            q, count = q.where(MailTask.state == state), count.where(MailTask.state == state)
        rows = (await s.scalars(q.order_by(MailTask.created_at.desc()).offset(offset).limit(limit))).all()
        items = []
        for task in rows:
            view = await _task_view(s, task)
            view["steps"] = [{"task": x.get("task"), "status": x.get("status"),
                              "decision": (x.get("policy") or {}).get("decision")} for x in view["steps"]]
            view.pop("transitions")
            items.append(view)
        return {"total": await s.scalar(count) or 0, "items": items}


async def outbox(user_id: str, limit: int = 50) -> list[dict]:
    async with connection.session_factory()() as s:
        rows = (await s.scalars(select(SimulatedOutbox).where(SimulatedOutbox.user_id == user_id)
                                .order_by(SimulatedOutbox.id.desc()).limit(limit))).all()
        return [r.to_dict() for r in rows]


async def clear_outbox(user_id: str) -> int:
    from sqlalchemy import delete

    async with connection.session_factory()() as s:
        res = await s.execute(delete(SimulatedOutbox).where(SimulatedOutbox.user_id == user_id))
        await s.commit()
        return res.rowcount or 0


async def poll_once() -> int:
    """One pass: sync every user whose Gmail is connected and set as their inbox. Returns users synced.
    One user's failure never stops the others."""
    synced = 0
    for user_id in await gmail_account.connected_user_ids():
        try:
            name, provider = await active_provider(user_id)
            if name == "gmail" and provider is not None:
                await sync(user_id, provider)
                synced += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - one mailbox must not stop the others
            logger.warning(f"mail poller: one account failed ({type(exc).__name__})")
    await expire_due()
    return synced


async def poll_forever() -> None:
    """Background loop: every MAIL_POLL_SECONDS, sync each connected user's Gmail and expire old approvals.
    Never raises; problems are recorded on the account."""
    while True:
        await asyncio.sleep(settings.MAIL_POLL_SECONDS)
        try:
            await poll_once()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the poller must never die
            logger.warning(f"mail poller iteration failed ({type(exc).__name__})")
