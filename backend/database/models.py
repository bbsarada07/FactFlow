"""SQLAlchemy 2.0 models. Portable across PostgreSQL (asyncpg) and SQLite (aiosqlite)."""
import uuid
from datetime import date, datetime, timezone

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


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id() -> str:
    return uuid.uuid4().hex


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

    # Intake
    claim_text: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(32))
    language_name: Mapped[str | None] = mapped_column(String(64))
    claim_type: Mapped[str | None] = mapped_column(String(32))
    urgency: Mapped[str | None] = mapped_column(String(16))
    pattern_matches: Mapped[list] = mapped_column(JSON, default=list)

    # Verdict
    verdict: Mapped[str | None] = mapped_column(String(16), index=True)
    confidence: Mapped[float | None] = mapped_column(Float)
    summary: Mapped[str | None] = mapped_column(Text)
    reasoning_chain: Mapped[list] = mapped_column(JSON, default=list)
    contradictions: Mapped[list] = mapped_column(JSON, default=list)

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
        back_populates="claim", cascade="all, delete-orphan", lazy="selectin", order_by="Source.credibility.desc()"
    )

    def to_summary(self) -> dict:
        return {
            "request_id": self.id,
            "created_at": iso(self.created_at),
            "status": self.status,
            "claim": self.claim_text or self.raw_input[:280],
            "verdict": self.verdict,
            "confidence": self.confidence,
            "harm_type": self.harm_type,
            "harm_level": self.harm_level,
            "urgency": self.urgency,
            "platform": self.platform,
            "is_seed": self.is_seed,
        }

    def to_result(self) -> dict:
        return {
            **self.to_summary(),
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

    claim: Mapped[Claim] = relationship(back_populates="sources")

    def to_dict(self) -> dict:
        return {
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

    def to_dict(self) -> dict:
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
            "reference_url": "https://en.wikipedia.org/w/index.php?search="
            + self.reference_query.replace(" ", "+"),
        }
