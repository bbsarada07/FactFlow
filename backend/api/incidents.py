"""GET /api/incidents — documented incidents, with FactFlow's latest live run of each forward."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from database.models import Claim, Incident
from services import auth
from services.auth import CurrentUser
from services.text_utils import input_hash

router = APIRouter(prefix="/api", tags=["incidents"])


@router.get("/incidents")
async def incidents(session: AsyncSession = Depends(get_session), user: CurrentUser = Depends(auth.current_user)):
    """The documented incidents (shared reference material) and this user's own latest run of each forward."""
    rows = (await session.scalars(select(Incident).order_by(Incident.deaths.desc(), Incident.occurred_on))).all()
    hashes = {input_hash(i.forward_text): i.slug for i in rows}

    runs = (
        await session.scalars(
            select(Claim)
            .where(
                Claim.input_hash.in_(hashes),
                Claim.user_id == user.id,
                Claim.is_seed.is_(False),
                Claim.status == "complete",
                Claim.cached_from.is_(None),
            )
            .order_by(Claim.created_at.desc())
        )
    ).all()
    latest: dict[str, dict] = {}
    for c in runs:
        slug = hashes[c.input_hash]
        if slug not in latest:
            latest[slug] = {
                "request_id": c.id,
                "verdict": c.verdict,
                "confidence": c.confidence,
                "seconds": round((c.processing_ms or 0) / 1000, 1),
                "used_ultra": c.used_ultra,
            }

    return {"items": [{**i.to_dict(), "latest_run": latest.get(i.slug)} for i in rows]}
