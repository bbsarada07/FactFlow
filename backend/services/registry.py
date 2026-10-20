"""Public verdict registry: repeat-claim detection over stored verdicts.

Matching uses only the stdlib and rapidfuzz (no embeddings / pgvector):
  1. exact match on the normalised-text hash, then
  2. rapidfuzz token_set_ratio >= REPEAT_SIMILARITY over the most recent public claims.
"""
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.models import Claim
from services.text_utils import input_hash

# token_set_ratio scores 100 whenever one text's tokens are a subset of the other's, so a
# two-word query would "match" any long claim containing those words. Require comparable
# lengths before trusting a fuzzy score. 0.6 keeps short boilerplate forwards ("forward this
# to ...") from matching longer, different claims.
MIN_LENGTH_RATIO = 0.6

# redact_pii() inserts [phone]/[email]/[handle]; normalize() turns them into bare words. Two
# unrelated forwards that both contained a phone number would share that token, so drop the
# placeholders before fuzzy scoring. (Exact-hash matching is unaffected.)
_PLACEHOLDERS = re.compile(r"\b(?:phone|email|handle)\b")
_SPACES = re.compile(r"\s+")


def _for_fuzzy(normalized: str) -> str:
    """Normalised text with redaction placeholders removed, for fuzzy comparison only."""
    return _SPACES.sub(" ", _PLACEHOLDERS.sub(" ", normalized)).strip()


@dataclass(frozen=True)
class Candidate:
    """Minimal view of a stored claim used for matching."""

    id: str
    normalized_text: str
    created_at: datetime


@dataclass(frozen=True)
class RepeatMatch:
    """A stored claim that the new input repeats, with its similarity score (0-100)."""

    candidate: Candidate
    score: float
    exact: bool


def find_repeat(normalized: str, candidates: list[Candidate], threshold: float | None = None) -> RepeatMatch | None:
    """Return the best stored claim that `normalized` repeats, or None.

    Exact normalised equality wins outright; otherwise the highest token_set_ratio at or above
    `threshold` among candidates of comparable length. Pure function (no I/O).
    """
    threshold = settings.REPEAT_SIMILARITY if threshold is None else threshold
    if not normalized:
        return None
    best: RepeatMatch | None = None
    query = _for_fuzzy(normalized)
    for c in candidates:
        if not c.normalized_text:
            continue
        if c.normalized_text == normalized:
            return RepeatMatch(c, 100.0, True)
        other = _for_fuzzy(c.normalized_text)
        shorter, longer = sorted((len(query), len(other)))
        if shorter == 0 or shorter / longer < MIN_LENGTH_RATIO:
            continue
        score = fuzz.token_set_ratio(query, other)
        if score >= threshold and (best is None or score > best.score):
            best = RepeatMatch(c, float(score), False)
    return best


def is_fresh(created_at: datetime, now: datetime | None = None, days: int | None = None) -> bool:
    """True when a stored verdict is younger than the repeat window (default REPEAT_WINDOW_DAYS)."""
    now = now or datetime.now(timezone.utc)
    days = settings.REPEAT_WINDOW_DAYS if days is None else days
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return now - created_at < timedelta(days=days)


def _public_live():
    return (
        Claim.is_public.is_(True),
        Claim.is_seed.is_(False),
        Claim.status == "complete",
    )


async def lookup_repeat(session: AsyncSession, normalized: str) -> tuple[Claim, RepeatMatch] | None:
    """Find a stored public verdict for this normalised text (exact hash first, then fuzzy)."""
    if not normalized:
        return None
    exact = await session.scalar(
        select(Claim)
        .where(*_public_live(), Claim.input_hash == input_hash(normalized))
        .order_by(Claim.created_at.desc())
        .limit(1)
    )
    if exact is not None:
        cand = Candidate(exact.id, exact.normalized_text or normalized, exact.created_at)
        return exact, RepeatMatch(cand, 100.0, True)

    rows = (
        await session.execute(
            select(Claim.id, Claim.normalized_text, Claim.created_at)
            .where(*_public_live(), Claim.normalized_text.is_not(None))
            .order_by(Claim.created_at.desc())
            .limit(settings.REPEAT_CORPUS_SIZE)
        )
    ).all()
    match = find_repeat(normalized, [Candidate(r.id, r.normalized_text, r.created_at) for r in rows])
    if match is None:
        return None
    claim = await session.get(Claim, match.candidate.id)
    return (claim, match) if claim else None
