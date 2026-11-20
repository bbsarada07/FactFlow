"""GET /api/history — the signed-in user's most recent checks (plus the seed examples, if asked)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from database.models import Claim
from services import auth
from services.auth import CurrentUser

router = APIRouter(prefix="/api", tags=["history"])


@router.get("/history")
async def history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    include_seed: bool = True,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(auth.current_user),
):
    mine = Claim.user_id == user.id
    seeds = Claim.is_seed.is_(True) & Claim.user_id.is_(None)
    cond = [Claim.status == "complete", (mine | seeds) if include_seed else mine]
    rows = (
        await session.scalars(
            select(Claim).where(*cond).order_by(Claim.created_at.desc()).limit(limit).offset(offset)
        )
    ).all()
    total = await session.scalar(select(func.count()).select_from(Claim).where(*cond))
    return {"total": total, "items": [c.to_summary() for c in rows]}
