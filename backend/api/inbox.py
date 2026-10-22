"""/api/inbox: analyse emails and messages with the Shield (see docs/API_CONTRACT.md)."""
import asyncio
import base64
import binascii
import json
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from agents.inbox_pipeline import InboxOptions, analyze
from api.verify import RateLimiter
from config import BASE_DIR, settings
from database.connection import get_session
from database.models import Email, iso
from services.event_bus import get_bus
from services.operator_auth import require_operator
from shield.email_parser import MAX_BYTES, EmailInputError, parse_input
from shield.scan import PIPELINE_VERSION

router = APIRouter(prefix="/api/inbox", tags=["inbox"])
limiter = RateLimiter(settings.MAX_INBOX_PER_MINUTE, noun="message checks")
DEMO_DIR = BASE_DIR / "data" / "demo_emails"
_background: set[asyncio.Task] = set()


class AnalyzeOptions(BaseModel):
    language: str = Field(default="auto", max_length=8, description="'auto' or an ISO 639-1 code for the explanation")
    mode: Literal["full", "rules"] = Field(default="full", description="'rules' makes no model calls")
    wait: bool = Field(default=False, description="true: answer with the finished verdict (200) instead of 202")
    force: bool = Field(default=False, description="true: analyse again even if this exact message was analysed before")


class AnalyzeRequest(AnalyzeOptions):
    raw: str | None = Field(default=None, max_length=MAX_BYTES + 1,
                            description="Raw email source (RFC 822) or plain pasted text")
    eml_base64: str | None = Field(default=None, max_length=(MAX_BYTES // 3 + 1) * 4 + 4,
                                   description="An .eml file, base64-encoded")
    source: Literal["paste", "upload"] = "paste"


class AnalyzeResponse(BaseModel):
    email_id: str
    status: str
    mode: str
    cached: bool = False
    stream_url: str
    result_url: str
    verdict: dict | None = None
    error: str | None = None


def _bytes(body: AnalyzeRequest) -> bytes:
    if body.eml_base64:
        try:
            return base64.b64decode(body.eml_base64, validate=True)
        except (binascii.Error, ValueError):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "eml_base64 is not valid base64") from None
    if body.raw and body.raw.strip():
        return body.raw.encode("utf-8")
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Provide raw or eml_base64")


def _response(row: Email, cached: bool = False) -> AnalyzeResponse:
    return AnalyzeResponse(email_id=row.id, status=row.status, mode=row.mode, cached=cached,
                           stream_url=f"/api/inbox/{row.id}/stream", result_url=f"/api/inbox/{row.id}",
                           verdict=row.verdict if row.status == "complete" else None, error=row.error)


async def _submit(data: bytes, source: str, opts: AnalyzeOptions, request: Request, response: Response,
                  session: AsyncSession) -> AnalyzeResponse:
    try:
        pe = parse_input(data, source)
    except EmailInputError as exc:
        code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if "larger" in str(exc) else status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(code, str(exc)) from None
    limiter.check(request.client.host if request.client else "unknown")
    use_llm = opts.mode == "full" and settings.INBOX_USE_LLM
    mode = "full" if use_llm else "rules"
    if not opts.force:
        cached = await session.scalar(
            select(Email).where(Email.sha256 == pe.sha256, Email.pipeline_version == PIPELINE_VERSION,
                                Email.mode == mode, Email.language == opts.language, Email.status == "complete")
            .order_by(Email.created_at.desc()).limit(1))
        if cached is not None:
            response.status_code = status.HTTP_200_OK
            return _response(cached, cached=True)
    row = Email(source=source, sha256=pe.sha256, pipeline_version=PIPELINE_VERSION, mode=mode, language=opts.language,
                status="processing", subject=pe.subject[:500] or None, from_addr=pe.from_addr[:320] or None)
    session.add(row)
    await session.commit()
    email_id = row.id
    job = analyze(email_id, data, InboxOptions(source=source, language=opts.language, use_llm=use_llm))
    if opts.wait:
        await job
        await session.refresh(row)
        response.status_code = status.HTTP_200_OK if row.status == "complete" else status.HTTP_422_UNPROCESSABLE_CONTENT
        return _response(row)
    task = asyncio.create_task(job)
    _background.add(task)
    task.add_done_callback(_background.discard)
    response.status_code = status.HTTP_202_ACCEPTED
    return _response(row)


@router.post("/analyze", response_model=AnalyzeResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_message(body: AnalyzeRequest, request: Request, response: Response,
                          session: AsyncSession = Depends(get_session)):
    """Analyse an email (raw source or .eml) or a pasted message. Public, rate-limited."""
    return await _submit(_bytes(body), body.source, body, request, response, session)


def _demo_files() -> list[Path]:
    return sorted(DEMO_DIR.glob("*.eml")) if DEMO_DIR.exists() else []


@router.get("/demo")
async def list_demo_emails():
    """The seeded demo emails (data/demo_emails)."""
    out = []
    for path in _demo_files():
        pe = parse_input(path.read_bytes(), "demo")
        out.append({"name": path.stem, "subject": pe.subject, "from_addr": pe.from_addr})
    return {"items": out}


@router.post("/demo/{name}", response_model=AnalyzeResponse, status_code=status.HTTP_202_ACCEPTED)
async def analyze_demo_email(name: str, request: Request, response: Response, opts: AnalyzeOptions | None = None,
                             session: AsyncSession = Depends(get_session)):
    """Analyse one seeded demo email by name (see GET /api/inbox/demo)."""
    path = next((p for p in _demo_files() if p.stem == name), None)
    if path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such demo email")
    return await _submit(path.read_bytes(), "demo", opts or AnalyzeOptions(), request, response, session)


@router.get("")
async def list_inbox(limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0),
                     label: Literal["SAFE", "SUSPICIOUS", "DANGEROUS"] | None = None, source: str | None = None,
                     session: AsyncSession = Depends(get_session), _actor: str = Depends(require_operator)):
    """Analysed messages, newest first. Needs the operator token (it lists other people's messages)."""
    q, count = select(Email), select(func.count()).select_from(Email)
    if label:
        q, count = q.where(Email.label == label), count.where(Email.label == label)
    if source:
        q, count = q.where(Email.source == source), count.where(Email.source == source)
    rows = (await session.scalars(q.order_by(Email.created_at.desc()).offset(offset).limit(limit))).all()
    return {"total": await session.scalar(count) or 0, "items": [r.summary() for r in rows]}


@router.get("/{email_id}")
async def get_email(email_id: str, response: Response, session: AsyncSession = Depends(get_session)):
    """One analysis by its id (the id is unguessable, like /api/result/{id}). 202 while processing."""
    row = await session.get(Email, email_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown email_id")
    if row.status == "processing":
        response.status_code = status.HTTP_202_ACCEPTED
    return {"email_id": row.id, "status": row.status, "mode": row.mode, "created_at": iso(row.created_at),
            "completed_at": iso(row.completed_at), "verdict": row.verdict, "error": row.error}


def _sse(event: dict) -> dict:
    return {"event": event["type"], "data": json.dumps(event, default=str)}


@router.get("/{email_id}/stream")
async def stream_email(email_id: str, request: Request, session: AsyncSession = Depends(get_session)):
    """Live stage events in the same format as /api/stream/{request_id}."""
    row = await session.get(Email, email_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown email_id")
    bus = get_bus()
    replay = None
    if row.status in ("complete", "failed") and not bus.has(email_id):
        replay = {"agents": row.agent_log or [], "status": row.status, "verdict": row.verdict, "error": row.error}
    await session.close()

    async def events():
        if replay is not None:
            for a in replay["agents"]:
                yield _sse({"type": "agent", "agent": a.get("index"), **a, "progress": 100})
            if replay["status"] == "complete":
                yield _sse({"type": "result", "progress": 100, "result": replay["verdict"]})
            else:
                yield _sse({"type": "error", "message": replay["error"] or "Analysis failed"})
            return
        async for ev in bus.subscribe(email_id):
            if await request.is_disconnected():
                return
            if ev["type"] == "ping":
                yield {"comment": "keep-alive"}
                continue
            yield _sse(ev)

    return EventSourceResponse(events(), ping=15, headers={"X-Accel-Buffering": "no"})
