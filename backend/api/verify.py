"""POST /api/verify — queue a claim for forensic verification."""
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.connection import get_session
from database.models import Claim
from services.text_utils import input_hash
from tasks.pipeline_task import dispatch

router = APIRouter(prefix="/api", tags=["verify"])

MAX_IMAGE_B64 = 11_500_000  # ~8 MB decoded
PLATFORMS = {"whatsapp", "twitter", "instagram", "facebook", "youtube", "news", "web", "extension"}


class VerifyRequest(BaseModel):
    text: str | None = Field(default=None, max_length=5000)
    url: str | None = Field(default=None, max_length=2048)
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_B64)
    image_url: str | None = Field(default=None, max_length=4096)
    language: str = Field(default="auto", max_length=8)
    platform: str | None = Field(default=None, max_length=32)

    @field_validator("url", "image_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL")
        return v or None


class VerifyResponse(BaseModel):
    request_id: str
    status: str
    mode: str
    stream_url: str
    result_url: str


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        q = self.hits[key]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= self.per_minute:
            retry = int(60 - (now - q[0])) + 1
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit: {self.per_minute} verifications per minute. Try again in {retry}s.",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)


limiter = RateLimiter(settings.MAX_REQUESTS_PER_MINUTE)


@router.post("/verify", response_model=VerifyResponse, status_code=status.HTTP_202_ACCEPTED)
async def verify(body: VerifyRequest, request: Request, session: AsyncSession = Depends(get_session)):
    text = (body.text or "").strip()
    if not (text or body.url or body.image_base64 or body.image_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide text, url, image_base64 or image_url")
    if text and not (body.url or body.image_base64 or body.image_url) and len(text) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Claim is too short to verify")

    limiter.check(request.client.host if request.client else "unknown")

    if body.image_base64 or body.image_url:
        input_type, source_url = "image", body.image_url
    elif body.url:
        input_type, source_url = "url", body.url
    else:
        input_type, source_url = "text", None

    platform = (body.platform or "web").lower()
    claim = Claim(
        input_type=input_type,
        raw_input=text,
        input_hash=input_hash(text) if text else "",
        source_url=source_url,
        image_data=body.image_base64,
        requested_language=(body.language or "auto").lower(),
        platform=platform if platform in PLATFORMS else "web",
        status="queued",
    )
    session.add(claim)
    await session.commit()

    mode = dispatch(claim.id)
    return VerifyResponse(
        request_id=claim.id,
        status="queued",
        mode=mode,
        stream_url=f"/api/stream/{claim.id}",
        result_url=f"/api/result/{claim.id}",
    )
