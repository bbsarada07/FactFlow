"""GET /api/history — most recent verifications for the live feed."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from database.models import Claim

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
async def history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_seed: bool = True,
    session: AsyncSession = Depends(get_session),
):
    cond = [Claim.status == "complete", Claim.is_public.is_(True)]
    if not include_seed:
        cond.append(Claim.is_seed.is_(False))
    rows = (
        await session.scalars(
            select(Claim).where(*cond).order_by(Claim.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    total = await session.scalar(select(func.count()).select_from(Claim).where(*cond))
    return {"total": total, "items": [c.to_summary() for c in rows]}
