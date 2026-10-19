"""GET /api/result/{id} and GET /api/status/{id}."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from database.models import Claim

router = APIRouter(prefix="/api", tags=["result"])


async def _get(session: AsyncSession, request_id: str) -> Claim:
    claim = await session.get(Claim, request_id)
    if claim is None:
        raise HTTPException(404, "Unknown request_id")
    return claim


@router.get("/result/{request_id}")
async def result(request_id: str, session: AsyncSession = Depends(get_session)):
    claim = await _get(session, request_id)
    if claim.status in ("queued", "processing"):
        return JSONResponse(status_code=202, content={"request_id": claim.id, "status": claim.status})
    return claim.to_result()


@router.get("/status/{request_id}")
async def status(request_id: str, session: AsyncSession = Depends(get_session)):
    claim = await _get(session, request_id)
    agents = claim.agent_log or []
    done = sum(1 for a in agents if a.get("status") in ("complete", "skipped", "failed"))
    return {
        "request_id": claim.id,
        "status": claim.status,
        "progress": 100 if claim.status in ("complete", "failed") else round(done / 6 * 100),
        "verdict": claim.verdict,
        "error": claim.error,
        "agents": agents,
    }
