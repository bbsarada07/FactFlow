"""SQLAlchemy 2.0 models. Portable across PostgreSQL (asyncpg) and SQLite (aiosqlite)."""
import secrets
import string
import uuid
from datetime import date, datetime, timezone
from urllib.parse import quote_plus

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from config import settings

_SLUG_ALPHABET = string.ascii_lowercase + string.digits


def utcnow() -> datetime:
    """Timezone-aware current UTC time."""
    return datetime.now(timezone.utc)


def new_id() -> str:
    """Internal request id (32 hex chars)."""
    return uuid.uuid4().hex


def new_slug() -> str:
    """Short, unguessable public id for registry URLs (10 chars, ~51 bits)."""
    return "".join(secrets.choice(_SLUG_ALPHABET) for _ in range(10))


def registry_url(slug: str | None) -> str | None:
    """Public verdict page URL on the configured frontend."""
    return f"{settings.FRONTEND_URL.rstrip('/')}/v/{slug}" if slug else None


def confidence_band(confidence: float | None) -> str:
    """Map a 0-1 confidence to high (>=0.85), medium (0.6-0.84) or low (<0.6 or unknown)."""
    if confidence is None:
        return "low"
    if confidence >= 0.85:
        return "high"
    if confidence >= 0.6:
        return "medium"
    return "low"


def iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class Base(DeclarativeBase):
    pass


class Claim(Base):
    """One verification request and its full forensic result."""

    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Input
    input_type: Mapped[str] = mapped_column(String(16), default="text")  # text | url | image
    raw_input: Mapped[str] = mapped_column(Text, default="")
    input_hash: Mapped[str] = mapped_column(String(64), index=True, default="")
    source_url: Mapped[str | None] = mapped_column(Text)
    image_data: Mapped[str | None] = mapped_column(Text)  # base64, cleared after processing
    requested_language: Mapped[str] = mapped_column(String(16), default="auto")
    platform: Mapped[str] = mapped_column(String(32), default="web")

    # Pipeline state
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    error: Mapped[str | None] = mapped_column(Text)
    agent_log: Mapped[list] = mapped_column(JSON, default=list)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    used_ultra: Mapped[bool] = mapped_column(Boolean, default=False)
    cached_from: Mapped[str | None] = mapped_column(String(32))
    is_seed: Mapped[bool] = mapped_column(Boolean, default=False)

    # Public registry
    slug: Mapped[str | None] = mapped_column(String(12), unique=True, index=True, default=new_slug)
    is_public: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    normalized_text: Mapped[str | None] = mapped_column(Text)
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    repeat_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    previous_id: Mapped[str | None] = mapped_column(String(32))

    # Intake
    claim_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32))
    language_name: Mapped[str | None] = mapped_column(String(64))
    claim_type: Mapped[str | None] = mapped_column(String(32))
    urgency: Mapped[str | None] = mapped_column(String(16))
    pattern_matches: Mapped[list] = mapped_column(JSON, default=list)
    search_log: Mapped[list] = mapped_column(JSON, default=list)  # provider, query, results, domains, error
    image_info: Mapped[dict | None] = mapped_column(JSON)  # screenshot reader, label and visible cues (display only)

    # Verdict
    verdict: Mapped[str | None] = mapped_column(String(16), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    reasoning_chain: Mapped[list] = mapped_column(JSON, default=list)
    contradictions: Mapped[list] = mapped_column(JSON, default=list)

    # Honest uncertainty
    confidence_band: Mapped[str | None] = mapped_column(String(8))
    model_verdict: Mapped[str | None] = mapped_column(String(16))
    model_confidence: Mapped[float | None] = mapped_column(Float)
    gate_reasons: Mapped[list] = mapped_column(JSON, default=list)
    missing_context: Mapped[list] = mapped_column(JSON, default=list)
    evidence_gaps: Mapped[list] = mapped_column(JSON, default=list)
    checks_to_do: Mapped[list] = mapped_column(JSON, default=list)
    correction: Mapped[dict | None] = mapped_column(JSON)

    # Explainer
    summary_local: Mapped[str | None] = mapped_column(Text)
    myth: Mapped[str | None] = mapped_column(Text)
    fact: Mapped[str | None] = mapped_column(Text)
    fact_source: Mapped[str | None] = mapped_column(Text)
    whatsapp_reply: Mapped[str | None] = mapped_column(Text)

    # Harm
    harm_type: Mapped[str | None] = mapped_column(String(32), index=True)
    harm_level: Mapped[str | None] = mapped_column(String(16))
    harm_score: Mapped[float | None] = mapped_column(Float)
    harm_rationale: Mapped[str | None] = mapped_column(Text)

    sources: Mapped[list["Source"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", lazy="selectin", order_by="Source.id"
    )

    def to_summary(self) -> dict:
        """Compact row for feeds and registry listings."""
        return {
            "request_id": self.id,
            "slug": self.slug,
            "created_at": iso(self.created_at),
            "status": self.status,
            "claim": self.claim_text or self.raw_input[:280],
            "verdict": self.verdict,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band or confidence_band(self.confidence),
            "harm_type": self.harm_type,
            "harm_level": self.harm_level,
            "urgency": self.urgency,
            "platform": self.platform,
            "is_seed": self.is_seed,
            "is_public": self.is_public,
            "view_count": self.view_count or 0,
            "repeat_count": self.repeat_count or 0,
        }

    def to_public(self) -> dict:
        """Registry record served at /api/v/{slug}: only what is safe and useful to share."""
        return {
            "slug": self.slug,
            "registry_url": registry_url(self.slug),
            "claim": self.claim_text or self.raw_input[:280],
            "verdict": self.verdict,
            "confidence": self.confidence,
            "confidence_band": self.confidence_band or confidence_band(self.confidence),
            "summary": self.summary,
            "reasons": self.reasoning_chain or [],
            "contradictions": self.contradictions or [],
            "evidence_gaps": self.evidence_gaps or [],
            "checks_to_do": self.checks_to_do or [],
            "gate_reasons": self.gate_reasons or [],
            "model_verdict": self.model_verdict,
            "model_confidence": self.model_confidence,
            "correction": self.correction,
            "sources": [s.to_dict() for s in self.sources],
            "harm_type": self.harm_type,
            "harm_level": self.harm_level,
            "claim_type": self.claim_type,
            "language_name": self.language_name,
            "platform": self.platform,
            "is_seed": self.is_seed,
            "version": self.version or 1,
            "repeat_count": self.repeat_count or 0,
            "created_at": iso(self.created_at),
            "view_count": self.view_count or 0,
        }

    def to_result(self) -> dict:
        """Full record for the requester (includes pipeline internals)."""
        return {
            **self.to_summary(),
            **self.to_public(),
            "request_id": self.id,
            "completed_at": iso(self.completed_at),
            "input_type": self.input_type,
            "raw_input": self.raw_input,
            "source_url": self.source_url,
            "error": self.error,
            "processing_ms": self.processing_ms,
            "used_ultra": self.used_ultra,
            "cached_from": self.cached_from,
            "language": self.language,
            "language_name": self.language_name,
            "claim_type": self.claim_type,
            "pattern_matches": self.pattern_matches or [],
            "search_log": self.search_log or [],
            "image_info": self.image_info,
            "summary": self.summary,
            "summary_local": self.summary_local,
            "reasoning_chain": self.reasoning_chain or [],
            "contradictions": self.contradictions or [],
            "myth": self.myth,
            "fact": self.fact,
            "fact_source": self.fact_source,
            "whatsapp_reply": self.whatsapp_reply,
            "harm_score": self.harm_score,
            "harm_rationale": self.harm_rationale,
            "agents": self.agent_log or [],
            "sources": [s.to_dict() for s in self.sources],
        }


class Source(Base):
    """A piece of evidence found by the Source Tracer."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    claim_id: Mapped[str] = mapped_column(ForeignKey("claims.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(Text)
    snippet: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(32))  # factcheck | newsapi | duckduckgo
    tier: Mapped[int] = mapped_column(Integer, default=3)
    credibility: Mapped[float] = mapped_column(Float, default=0.5)
    stance: Mapped[str] = mapped_column(String(16), default="NEUTRAL")  # SUPPORTS | REFUTES | NEUTRAL
    rating: Mapped[str | None] = mapped_column(String(255))  # fact-check textual rating
    published_at: Mapped[str | None] = mapped_column(String(64))
    ref: Mapped[str | None] = mapped_column(String(8))  # citation ID (S1, S2, ...) used in the verdict text

    claim: Mapped[Claim] = relationship(back_populates="sources")

    def to_dict(self) -> dict:
        return {
            "ref": self.ref,
            "name": self.name,
            "url": self.url,
            "title": self.title,
            "snippet": self.snippet,
            "origin": self.origin,
            "tier": self.tier,
            "credibility": self.credibility,
            "stance": self.stance,
            "rating": self.rating,
            "published_at": self.published_at,
        }


class KnownPattern(Base):
    """Recurring misinformation archetypes, matched by lexical similarity."""

    __tablename__ = "known_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32))
    typical_verdict: Mapped[str] = mapped_column(String(16))
    description: Mapped[str] = mapped_column(Text)
    example_text: Mapped[str] = mapped_column(Text)
    keywords: Mapped[list] = mapped_column(JSON, default=list)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "typical_verdict": self.typical_verdict,
            "description": self.description,
        }


class Incident(Base):
    """Documented real-world harm caused by misinformation."""

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    occurred_on: Mapped[date] = mapped_column(Date)
    location: Mapped[str] = mapped_column(String(255))
    platform: Mapped[str] = mapped_column(String(64))
    deaths: Mapped[int] = mapped_column(Integer, default=0)
    harm_type: Mapped[str] = mapped_column(String(32))
    verdict: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text)
    what_was_true: Mapped[str] = mapped_column(Text)
    forward_text: Mapped[str] = mapped_column(Text)
    forward_is_reconstruction: Mapped[bool] = mapped_column(Boolean, default=True)
    spread_minutes: Mapped[int | None] = mapped_column(Integer)
    fact_check_days: Mapped[int | None] = mapped_column(Integer)
    reference_query: Mapped[str] = mapped_column(String(255))
    # Primary source for the figures shown; when unconfirmed, a search link labelled "Find source".
    source_url: Mapped[str | None] = mapped_column(Text)
    source_label: Mapped[str | None] = mapped_column(String(255))
    source_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    extra_sources: Mapped[list] = mapped_column(JSON, default=list)

    def to_dict(self) -> dict:
        """Incident record; every figure is accompanied by its source link."""
        if self.source_confirmed and self.source_url:
            source = {"label": self.source_label or "Source", "url": self.source_url, "confirmed": True}
        else:
            source = {
                "label": "Find source",
                "url": settings.GOOGLE_SEARCH_URL + quote_plus(self.reference_query),
                "confirmed": False,
            }
        return {
            "slug": self.slug,
            "name": self.name,
            "date": self.occurred_on.isoformat(),
            "location": self.location,
            "platform": self.platform,
            "deaths": self.deaths,
            "harm_type": self.harm_type,
            "verdict": self.verdict,
            "summary": self.summary,
            "what_was_true": self.what_was_true,
            "forward_text": self.forward_text,
            "forward_is_reconstruction": self.forward_is_reconstruction,
            "spread_minutes": self.spread_minutes,
            "fact_check_days": self.fact_check_days,
            "source": source,
            "extra_sources": self.extra_sources or [],
        }


class AuditLog(Base):
    """Shield audit log: an append-only SHA-256 hash chain (see shield/audit.py).

    `seq` is the primary key, so two writers can never both append record N; the loser retries
    on the new head. `ts` is stored as the exact string that was hashed.
    """

    __tablename__ = "audit_log"

    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    ts: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64), unique=True)
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    # Copied from payload["email_id"] for filtering; not part of the hash.
    email_id: Mapped[str | None] = mapped_column(String(64), index=True)


class Email(Base):
    """An analysed email or pasted message and its unified verdict (see agents/inbox_pipeline.py).

    Subject and sender come from the message itself: show them as text, never as HTML."""

    __tablename__ = "emails"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[str] = mapped_column(String(16), default="paste")  # upload | paste | demo | gmail | whatsapp
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    pipeline_version: Mapped[str] = mapped_column(String(16))
    mode: Mapped[str] = mapped_column(String(8), default="full")  # rules | full
    language: Mapped[str] = mapped_column(String(8), default="auto")
    status: Mapped[str] = mapped_column(String(16), default="processing", index=True)  # processing | complete | failed
    subject: Mapped[str | None] = mapped_column(Text)
    from_addr: Mapped[str | None] = mapped_column(String(320))
    label: Mapped[str | None] = mapped_column(String(16), index=True)
    score: Mapped[int | None] = mapped_column(Integer)
    verdict: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    tokens: Mapped[int | None] = mapped_column(Integer)
    agent_log: Mapped[list] = mapped_column(JSON, default=list)

    def summary(self) -> dict:
        """Row for the inbox list."""
        reasons = ((self.verdict or {}).get("overall") or {}).get("reasons") or []
        return {
            "email_id": self.id, "created_at": iso(self.created_at), "source": self.source, "status": self.status,
            "mode": self.mode, "subject": self.subject, "from_addr": self.from_addr, "label": self.label,
            "score": self.score, "top_reason": reasons[0] if reasons else None,
        }


class ShieldApproval(Base):
    """A human-in-the-loop approval request (see shield/approvals.py)."""

    __tablename__ = "approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    email_id: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str | None] = mapped_column(Text)
    origin: Mapped[str] = mapped_column(String(32))
    rule_id: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
