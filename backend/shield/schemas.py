"""Pydantic v2 models shared by every Shield component (master prompt section 4.6).

The Shield package is pure Python: nothing in it imports FastAPI, the database or
backend/config.py, so it can be reused on an edge device later.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Severity = Literal["low", "medium", "high", "critical"]
SEVERITY_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3, "critical": 4}

Label = Literal["SAFE", "SUSPICIOUS", "DANGEROUS"]
AuthValue = Literal["pass", "fail", "softfail", "none", "unknown"]
ClaimVerdict = Literal["TRUE", "FALSE", "MISLEADING", "UNVERIFIED"]

Action = Literal[
    "summarize",
    "draft_reply",
    "send_reply",
    "forward_email",
    "share_data",
    "open_link",
    "download_attachment",
    "add_calendar_event",
    "delete_email",
    "report_phishing",
    "quarantine_email",
    "execute_instruction_from_content",
]
ACTIONS: tuple[str, ...] = Action.__args__  # type: ignore[attr-defined]
Origin = Literal["user", "untrusted_content"]
Decision = Literal["ALLOW", "REQUIRE_APPROVAL", "BLOCK"]
PolicyMode = Literal["strict", "balanced"]

MAX_HIDDEN_TEXT = 300


def escape_control(text: str, limit: int = MAX_HIDDEN_TEXT) -> str:
    """Truncate to `limit` characters and show control/format characters as \\uXXXX escapes.

    Used for every piece of untrusted text that is displayed or logged as evidence, so invisible
    characters can be seen and cannot affect rendering.
    """
    import unicodedata

    out: list[str] = []
    for ch in text or "":
        cat = unicodedata.category(ch)
        if ch in "\n\t":
            out.append(" ")
        elif cat in ("Cc", "Cf", "Cs", "Co", "Cn"):
            cp = ord(ch)
            out.append(f"\\u{cp:04X}" if cp <= 0xFFFF else f"\\U{cp:08X}")
        else:
            out.append(ch)
    s = "".join(out)
    return s if len(s) <= limit else s[: limit - 1] + "…"


def max_severity(items: list[str]) -> str | None:
    """Highest severity in `items`, or None when empty."""
    return max(items, key=lambda s: SEVERITY_RANK[s]) if items else None


class HiddenFinding(BaseModel):
    """One hidden-content detector hit (HC-01..HC-12)."""

    id: str
    type: str
    severity: Severity
    location: str
    hidden_text: str = ""
    explanation_en: str
    instruction_like: bool = False

    @field_validator("hidden_text")
    @classmethod
    def _escape(cls, v: str) -> str:
        return escape_control(v)


class RuleHit(BaseModel):
    """One injection-rule match (config/patterns.yml)."""

    id: str
    category: str
    severity: Severity
    evidence: str
    location: str = "body"

    @field_validator("evidence")
    @classmethod
    def _escape(cls, v: str) -> str:
        return escape_control(v, 160)


class ScamHit(BaseModel):
    """One India-specific scam detector result."""

    id: str
    name: str
    matched_evidence: list[str]
    severity: Severity

    @field_validator("matched_evidence")
    @classmethod
    def _escape(cls, v: list[str]) -> list[str]:
        return [escape_control(x, 120) for x in v[:5]]


class Lookalike(BaseModel):
    """A domain that imitates a known brand's domain."""

    domain: str
    brand: str
    legit_domain: str | None = None
    reason: str
    severity: Severity


class LinkItem(BaseModel):
    """One link found in the message and the deterministic flags raised on it (never fetched)."""

    url: str
    host: str | None = None
    flags: list[str] = Field(default_factory=list)
    severity: Severity | None = None


class AttemptedAction(BaseModel):
    """What hidden or injected text tried to make an AI do. Shown to the user; never executed."""

    action: Action
    target: str | None = None


class HiddenContentComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    findings: list[HiddenFinding] = Field(default_factory=list)


class InjectionComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    rule_hits: list[RuleHit] = Field(default_factory=list)
    llm: dict | None = None
    attempted_actions: list[AttemptedAction] = Field(default_factory=list)


class AuthenticityComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    spf: AuthValue = "unknown"
    dkim: AuthValue = "unknown"
    dmarc: AuthValue = "unknown"
    reply_to_mismatch: bool = False
    return_path_mismatch: bool = False
    display_name_impersonation: str | None = None
    lookalikes: list[Lookalike] = Field(default_factory=list)
    signals: list[str] = Field(default_factory=list)


class LinksComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    items: list[LinkItem] = Field(default_factory=list)


class ScamComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    detectors: list[ScamHit] = Field(default_factory=list)


class ClaimItem(BaseModel):
    claim: str
    autopsy_id: str | None = None
    verdict: ClaimVerdict
    credibility: int = Field(ge=0, le=100)
    hidden: bool = False


class ClaimsComponent(BaseModel):
    score: int = Field(ge=0, le=100)
    items: list[ClaimItem] = Field(default_factory=list)


class Components(BaseModel):
    hidden_content: HiddenContentComponent
    injection: InjectionComponent
    authenticity: AuthenticityComponent
    links: LinksComponent
    scam: ScamComponent
    claims: ClaimsComponent


class DiffSegment(BaseModel):
    """Text an AI would read that a person does not see, with the detector that explains why."""

    text: str
    hc_id: str


class VisibleVsRaw(BaseModel):
    visible_text: str
    raw_text: str
    diff: list[DiffSegment] = Field(default_factory=list)


class PolicyDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    decision: Decision
    rule_id: str
    reason: str


class ProposedAction(BaseModel):
    action: Action
    target: str | None = None
    origin: Origin
    policy: PolicyDecision | None = None


class Overall(BaseModel):
    label: Label
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    en: str = ""
    user_language: str = "en"
    text: str = ""
    whatsapp_warning: str = ""


class Latency(BaseModel):
    total: int = 0
    per_stage: dict[str, int] = Field(default_factory=dict)


class UnifiedVerdict(BaseModel):
    """The single verdict FactFlow returns for an email or message (master prompt section 4.6)."""

    email_id: str
    overall: Overall
    components: Components
    visible_vs_raw: VisibleVsRaw
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
    explanation: Explanation = Field(default_factory=Explanation)
    analysis_failures: list[str] = Field(default_factory=list)
    latency_ms: Latency = Field(default_factory=Latency)
    audit_head_hash: str | None = None


ApprovalStatus = Literal["pending", "approved", "denied", "expired"]


class Approval(BaseModel):
    """A human-in-the-loop approval request (master prompt section 7)."""

    id: str
    email_id: str
    action: Action
    target: str | None = None
    origin: Origin
    rule_id: str
    reason: str
    evidence: dict = Field(default_factory=dict)
    status: ApprovalStatus = "pending"
    created_at: datetime
    expires_at: datetime
    decided_by: str | None = None
    decided_at: datetime | None = None


class AuditRecord(BaseModel):
    """One row of the hash-chained audit log (master prompt section 8)."""

    model_config = ConfigDict(frozen=True)

    seq: int = Field(ge=1)
    ts: str
    actor: str
    event_type: str
    payload: dict
    prev_hash: str
    hash: str
