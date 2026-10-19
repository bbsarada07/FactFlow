"""GET /api/stats — aggregate numbers for the tracker dashboard."""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.context import HARM_TYPES, VERDICTS
from database.connection import get_session
from database.models import Claim, utcnow

router = APIRouter(prefix="/api", tags=["stats"])


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session)):
    done = Claim.status == "complete"
    live = Claim.is_seed.is_(False)
    since = utcnow() - timedelta(hours=24)

    total = await session.scalar(select(func.count()).select_from(Claim).where(done)) or 0
    total_live = await session.scalar(select(func.count()).select_from(Claim).where(done, live)) or 0
    today = await session.scalar(
        select(func.count()).select_from(Claim).where(done, live, Claim.created_at >= since)
    ) or 0
    critical = await session.scalar(
        select(func.count()).select_from(Claim).where(done, Claim.harm_level == "CRITICAL")
    ) or 0

    verdict_rows = (await session.execute(select(Claim.verdict, func.count()).where(done).group_by(Claim.verdict))).all()
    verdicts = {v: 0 for v in VERDICTS}
    for v, n in verdict_rows:
        if v in verdicts:
            verdicts[v] = n

    harm_rows = (
        await session.execute(select(Claim.harm_type, func.count()).where(done).group_by(Claim.harm_type))
    ).all()
    harms = {h: 0 for h in HARM_TYPES if h != "NONE"}
    for h, n in harm_rows:
        if h in harms:
            harms[h] = n

    avg_ms = await session.scalar(
        select(func.avg(Claim.processing_ms)).where(done, live, Claim.cached_from.is_(None))
    )
    ultra = await session.scalar(
        select(func.count()).select_from(Claim).where(done, live, Claim.used_ultra.is_(True))
    ) or 0

    false_like = verdicts["FALSE"] + verdicts["MISLEADING"]
    return {
        "total_claims": total,
        "live_claims": total_live,
        "claims_today": today,
        "false_or_misleading_pct": round(false_like / total * 100) if total else 0,
        "critical_threats": critical,
        "avg_seconds": round(float(avg_ms) / 1000, 1) if avg_ms else None,
        "ultra_rate_pct": round(ultra / total_live * 100) if total_live else 0,
        "verdict_breakdown": verdicts,
        "harm_categories": harms,
    }
