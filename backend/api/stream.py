"""GET /api/stream/{request_id} — Server-Sent Events for live agent progress."""
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from database.connection import get_session
from database.models import Claim
from services.event_bus import get_bus
from services.safety import PRIVATE_PERSON_MESSAGE

router = APIRouter(prefix="/api", tags=["stream"])


def _sse(event: dict) -> dict:
    return {"event": event["type"], "data": json.dumps(event, default=str)}


@router.get("/stream/{request_id}")
async def stream(request_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    claim = await session.get(Claim, request_id)
    if claim is None:
        raise HTTPException(404, "Unknown request_id")

    bus = get_bus()
    finished = claim.status in ("complete", "failed", "withheld")
    replay = None
    if finished and not bus.has(request_id):
        # Pipeline ran in an earlier process; rebuild the stream from the stored record.
        replay = {
            "agents": claim.agent_log or [],
            "status": claim.status,
            "result": claim.to_result() if claim.status == "complete" else None,
            "error": claim.error,
            "elapsed_ms": claim.processing_ms or 0,
        }
    await session.close()

    async def events():
        if replay is not None:
            for a in replay["agents"]:
                yield _sse({"type": "agent", "agent": a.get("index"), **a, "progress": 100, "elapsed_ms": replay["elapsed_ms"]})
            if replay["status"] == "complete":
                yield _sse({"type": "result", "progress": 100, "result": replay["result"], "elapsed_ms": replay["elapsed_ms"]})
            elif replay["status"] == "withheld":
                yield _sse({"type": "withheld", "message": PRIVATE_PERSON_MESSAGE})
            else:
                yield _sse({"type": "error", "message": replay["error"] or "Verification failed"})
            return

        async for ev in bus.subscribe(request_id):
            if await request.is_disconnected():
                return
            if ev["type"] == "ping":
                yield {"comment": "keep-alive"}
                continue
            yield _sse(ev)

    return EventSourceResponse(events(), ping=15, headers={"X-Accel-Buffering": "no"})
