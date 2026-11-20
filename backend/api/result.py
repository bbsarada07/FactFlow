"""GET /api/result/{id} and GET /api/status/{id}."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import get_session
from database.models import Claim
from services import auth
from services.auth import CurrentUser

router = APIRouter(prefix="/api", tags=["result"])


def visible_to(claim: Claim | None, user: CurrentUser) -> bool:
    """A user sees their own checks and the curated seed examples; nothing else."""
    return claim is not None and (claim.user_id == user.id or (claim.is_seed and claim.user_id is None))


async def owned_claim(session: AsyncSession, request_id: str, user: CurrentUser) -> Claim:
    claim = await session.get(Claim, request_id)
    if not visible_to(claim, user):
        raise HTTPException(404, "Unknown request_id")  # someone else's check looks exactly like a missing one
    return claim


@router.get("/result/{request_id}")
async def result(request_id: str, session: AsyncSession = Depends(get_session),
                 user: CurrentUser = Depends(auth.current_user)):
    claim = await owned_claim(session, request_id, user)
    if claim.status in ("queued", "processing"):
        return JSONResponse(status_code=202, content={"request_id": claim.id, "status": claim.status})
    return claim.to_result()


@router.get("/status/{request_id}")
async def status(request_id: str, session: AsyncSession = Depends(get_session),
                 user: CurrentUser = Depends(auth.current_user)):
    claim = await owned_claim(session, request_id, user)
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
