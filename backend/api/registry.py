"""Verdict pages and search: GET /api/v/{slug} and GET /api/registry.

A verdict page is visible to the person who ran the check, and to anyone with the link once its owner shared it
(POST /api/result/{id}/share). Curated seed examples are open to all. Nothing is listed or searchable by anyone
but its owner; a shared page shows the claim, verdict and evidence only, never who checked it."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from rapidfuzz import fuzz
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.connection import get_session
from database.models import Claim
from services import auth
from services.auth import CurrentUser
from services.text_utils import normalize

router = APIRouter(prefix="/api", tags=["registry"])

SEARCH_MIN_SCORE = 80  # partial_ratio: tolerates typos without matching unrelated text


def _public(user: CurrentUser):
    """This user's completed live verdicts."""
    return (Claim.user_id == user.id, Claim.is_seed.is_(False), Claim.status == "complete")


def _viewable(user: CurrentUser | None):
    """A verdict page this visitor may open: their own, a shared one, or a seed example."""
    open_to_all = Claim.shared_at.is_not(None) | (Claim.is_seed.is_(True) & Claim.user_id.is_(None))
    who = open_to_all if user is None else (Claim.user_id == user.id) | open_to_all
    return (who, Claim.status == "complete")


async def _visitor(request: Request) -> CurrentUser | None:
    return await auth.optional_user(request)


@router.get("/v/{slug}")
async def public_verdict(slug: str, track: bool = True, session: AsyncSession = Depends(get_session),
                         user: CurrentUser | None = Depends(_visitor)):
    """Public verdict record for a shareable registry page. Increments view_count unless track=false
    (used by link-preview image rendering so crawlers don't inflate the count).

    Also returns links to other versions of the same claim (re-verifications after the
    repeat window) so readers can see whether the verdict changed over time.
    """
    claim = await session.scalar(select(Claim).where(Claim.slug == slug, *_viewable(user)))
    if claim is None:
        # Signed out: maybe it exists but is private, so ask them to sign in; signed in: not theirs or missing.
        raise HTTPException(401 if user is None else 404, "Sign in to see this verdict" if user is None
                            else "No verdict with this id")
    is_owner = user is not None and claim.user_id == user.id

    if track and not is_owner:  # the owner opening their own verdict is not a view
        await session.execute(update(Claim).where(Claim.id == claim.id).values(view_count=Claim.view_count + 1))
        await session.commit()
        await session.refresh(claim)

    related_ids = {i for i in (claim.previous_id,) if i}
    newer = (await session.scalars(select(Claim.id).where(Claim.previous_id == claim.id, *_viewable(user)))).all()
    related_ids.update(newer)
    versions = []
    if related_ids:
        rows = (await session.scalars(select(Claim).where(Claim.id.in_(related_ids), *_viewable(user)))).all()
        versions = sorted(
            ({"slug": r.slug, "verdict": r.verdict, "version": r.version, "created_at": r.to_summary()["created_at"]} for r in rows),
            key=lambda v: v["version"],
        )
    return {
        **claim.to_public(),
        # Same stored values the verify/result responses use, so both views agree.
        "urgency": claim.urgency,
        "processing_ms": claim.processing_ms,
        "processing_time_seconds": round(claim.processing_ms / 1000, 1) if claim.processing_ms is not None else None,
        "versions": versions,
        "shared": claim.shared_at is not None,
        "is_owner": is_owner,
        # Only the owner gets the id that the share / stop-sharing routes take.
        **({"request_id": claim.id} if is_owner else {}),
    }


@router.get("/registry")
async def registry(
    q: str = Query("", max_length=200),
    limit: int = Query(20, ge=1, le=50),
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(auth.current_user),
):
    """Search public verdicts by normalised text (fuzzy, via rapidfuzz). Empty q lists the latest."""
    if not q.strip():
        rows = (
            await session.scalars(select(Claim).where(*_public(user)).order_by(Claim.created_at.desc()).limit(limit))
        ).all()
        return {"query": "", "items": [c.to_summary() for c in rows]}

    query = normalize(q)
    rows = (
        await session.scalars(
            select(Claim).where(*_public(user)).order_by(Claim.created_at.desc()).limit(settings.REPEAT_CORPUS_SIZE)
        )
    ).all()
    scored = []
    for c in rows:
        haystack = f"{normalize(c.claim_text or '')} {c.normalized_text or ''}"
        score = 100.0 if query in haystack else fuzz.partial_ratio(query, haystack)
        if score >= SEARCH_MIN_SCORE:
            scored.append((score, c))
    scored.sort(key=lambda t: (-t[0], -t[1].created_at.timestamp()))
    return {
        "query": q,
        "items": [{**c.to_summary(), "match_score": round(s)} for s, c in scored[:limit]],
    }
