"""The mail agent's rules: task states, the planner and the in-FactFlow effects (Addendum A3).

FETCHED -> PARSED -> SCANNED -> PLANNED -> POLICY_CHECKED -> (EXECUTED | AWAITING_APPROVAL | BLOCKED) -> DONE

The planner works from structured fields of the verdict only: the label, whether a reply was
requested, whether the message has headers, and the actions the message tried to make an AI take.
It never reads message text, so nothing written in a message can add or change a step. Every step
then goes through the policy engine; the runner (services/mail_agent.py) persists and executes.
Nothing here can send, delete or modify real mail: outward steps end in a simulated outbox.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

from shield.schemas import Action, PolicyDecision, UnifiedVerdict

TaskState = Literal["FETCHED", "PARSED", "SCANNED", "PLANNED", "POLICY_CHECKED", "EXECUTED",
                    "AWAITING_APPROVAL", "BLOCKED", "DONE", "FAILED"]
TRANSITIONS: dict[str | None, set[str]] = {
    None: {"FETCHED"},
    "FETCHED": {"PARSED", "FAILED"},
    "PARSED": {"SCANNED", "FAILED"},
    "SCANNED": {"PLANNED", "FAILED"},
    "PLANNED": {"POLICY_CHECKED", "FAILED"},
    "POLICY_CHECKED": {"EXECUTED", "AWAITING_APPROVAL", "BLOCKED", "FAILED"},
    "AWAITING_APPROVAL": {"EXECUTED", "BLOCKED"},
    "EXECUTED": {"DONE"},
    "BLOCKED": {"DONE"},
    "DONE": {"PLANNED"},  # a step the user asks for later re-opens the task
    "FAILED": set(),
}

AgentTask = Literal["summarize", "extract_action_items", "draft_reply", "propose_calendar_event", "propose_forward",
                    "propose_share_data", "propose_open_link", "report_phishing", "quarantine_email",
                    "follow_message_instructions"]
TASK_ACTION: dict[str, str] = {
    "summarize": "summarize", "extract_action_items": "extract_action_items", "draft_reply": "draft_reply",
    "propose_calendar_event": "add_calendar_event", "propose_forward": "forward_email",
    "propose_share_data": "share_data", "propose_open_link": "open_link", "report_phishing": "report_phishing",
    "quarantine_email": "quarantine_email", "follow_message_instructions": "execute_instruction_from_content",
}
ACTION_TASK = {a: t for t, a in TASK_ACTION.items()}
USER_REQUESTABLE = {"extract_action_items", "draft_reply", "propose_calendar_event", "propose_forward",
                    "propose_share_data", "propose_open_link", "report_phishing", "quarantine_email"}
NEEDS_TARGET = {"propose_forward", "propose_share_data", "propose_open_link"}
# Steps whose effect leaves FactFlow (simulated): they land in the simulated outbox.
OUTBOX_KIND = {"propose_forward": "forward", "propose_share_data": "share_data", "propose_open_link": "open_link",
               "propose_calendar_event": "calendar_event"}
StepStatus = Literal["planned", "executed", "awaiting_approval", "denied", "expired", "blocked", "failed"]


class InvalidTransition(Exception):
    pass


def check_transition(old: str | None, new: str) -> None:
    if new not in TRANSITIONS.get(old, set()):
        raise InvalidTransition(f"{old} -> {new} is not allowed")


class Step(BaseModel):
    """One unit of work. `requested_by`: the agent's own plan, the user, or the message itself
    (an attempted action read from the content, which is never carried out)."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    task: AgentTask
    action: Action
    target: str | None = None
    origin: Literal["user", "untrusted_content"] = "user"
    requested_by: Literal["agent", "user", "message"] = "agent"
    status: StepStatus = "planned"
    policy: PolicyDecision | None = None
    approval_id: str | None = None
    notice: str | None = None
    result: dict = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


def new_step(task: str, *, target: str | None = None, requested_by: str = "agent") -> Step:
    return Step(task=task, action=TASK_ACTION[task], target=target, origin="user", requested_by=requested_by)


def plan(verdict: UnifiedVerdict) -> list[Step]:
    """The agent's plan for one message, built from structured verdict fields only."""
    steps = [new_step("summarize")]
    if verdict.overall.label == "DANGEROUS":
        steps += [new_step("report_phishing"), new_step("quarantine_email")]
    else:
        steps.append(new_step("extract_action_items"))
        notes = verdict.reader_notes
        if notes and notes.reply_requested and verdict.message and verdict.message.has_headers:
            steps.append(new_step("draft_reply"))
    for attempt in verdict.components.injection.attempted_actions:
        steps.append(Step(task=ACTION_TASK.get(attempt.action, "follow_message_instructions"), action=attempt.action,
                          target=attempt.target, origin="untrusted_content", requested_by="message"))
    return steps


def state_after_policy(steps: list[Step]) -> str:
    """AWAITING_APPROVAL while any step waits; otherwise EXECUTED if anything ran, else BLOCKED."""
    if any(s.status == "awaiting_approval" for s in steps):
        return "AWAITING_APPROVAL"
    if any(s.status == "executed" for s in steps):
        return "EXECUTED"
    return "BLOCKED"


# ---------------------------------------------------------------------------- effects


def summary_result(v: UnifiedVerdict) -> dict:
    """The warning summary: what the message is about (from the quarantined reader) and the verdict."""
    notes = v.reader_notes
    return {"summary": notes.summary if notes and notes.summary else (v.message.subject if v.message else ""),
            "verdict": v.overall.label, "score": v.overall.score, "why": v.explanation.text or v.explanation.en}


def action_items_result(v: UnifiedVerdict) -> dict:
    notes = v.reader_notes
    if notes is None:
        return {"items": [], "meeting": None, "note": "Action items need the AI reader; this is a rules-only result."}
    return {"items": [i.model_dump() for i in notes.action_items],
            "meeting": notes.meeting.model_dump() if notes.meeting else None, "note": None}


def draft_reply_text(v: UnifiedVerdict) -> str:
    """A reply draft kept inside FactFlow (never written to the mailbox). Built from structured
    fields; the sender's name and subject are quoted as plain text."""
    m = v.message
    name = (m.from_display or m.from_addr.split("@")[0] if m else "") or "there"
    subject = (m.subject if m else "") or "your message"
    items = [i.task for i in (v.reader_notes.action_items if v.reader_notes else [])][:3]
    noted = (" I have noted: " + "; ".join(items) + ".") if items else ""
    return f"Hi {name},\n\nThank you for your message about \"{subject}\".{noted} I will get back to you soon.\n\nRegards"
