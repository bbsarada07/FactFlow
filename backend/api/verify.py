"""POST /api/verify — queue a claim for verification, or return a stored verdict for a repeat."""
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database.connection import get_session
from database.models import Claim, iso, new_slug, registry_url
from services.input_service import InputError, validate_screenshot
from services.registry import is_fresh, lookup_repeat
from services.safety import PRIVATE_PERSON_MESSAGE, WITHHELD_LABEL, check_sensitive
from services.text_utils import input_hash, normalize, redact_pii
from tasks.pipeline_task import dispatch

router = APIRouter(prefix="/api", tags=["verify"])

MAX_IMAGE_B64 = 11_500_000  # ~8 MB decoded
PLATFORMS = {"whatsapp", "twitter", "instagram", "facebook", "linkedin", "youtube", "news", "web", "extension"}


class VerifyRequest(BaseModel):
    """Body of POST /api/verify. At least one of text, url, image_base64 or image_url is required."""

    text: str | None = Field(default=None, max_length=settings.MAX_CLAIM_CHARS)
    url: str | None = Field(default=None, max_length=2048)
    image_base64: str | None = Field(default=None, max_length=MAX_IMAGE_B64)
    image_url: str | None = Field(default=None, max_length=4096)
    language: str = Field(default="auto", max_length=8)
    platform: str | None = Field(default=None, max_length=32)
    visibility: Literal["public", "private"] = "public"

    @field_validator("url", "image_url")
    @classmethod
    def _http_only(cls, v: str | None) -> str | None:
        """Only http(s) URLs may be fetched."""
        if v and not v.lower().startswith(("http://", "https://")):
            raise ValueError("must be an http(s) URL")
        return v or None


class VerifyResponse(BaseModel):
    """Either a queued job (cached=false) or a stored verdict for a repeat claim (cached=true)."""

    request_id: str
    slug: str
    status: str
    mode: str
    cached: bool = False
    matched_slug: str | None = None
    matched_at: str | None = None
    match_score: float | None = None
    registry_url: str | None = None
    stream_url: str
    result_url: str
    message: str | None = None  # set when a claim is withheld (private-person / self-harm rule)


class RateLimiter:
    """In-memory sliding-window limiter: at most `per_minute` hits per key in any 60 seconds."""

    def __init__(self, per_minute: int, clock=time.monotonic) -> None:
        self.per_minute = per_minute
        self.clock = clock
        self.hits: dict[str, deque] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Record a hit for `key`, raising HTTP 429 (with Retry-After) when over the limit."""
        now = self.clock()
        q = self.hits[key]
        while q and now - q[0] >= 60:
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


def _response(claim: Claim, mode: str, cached: bool = False, matched_at: datetime | None = None,
              score: float | None = None) -> VerifyResponse:
    """Build the API response for a new or matched claim."""
    return VerifyResponse(
        request_id=claim.id,
        slug=claim.slug,
        status=claim.status if cached else "queued",
        mode=mode,
        cached=cached,
        matched_slug=claim.slug if cached else None,
        matched_at=iso(matched_at) if cached else None,
        match_score=score,
        registry_url=registry_url(claim.slug) if claim.is_public else None,
        stream_url=f"/api/stream/{claim.id}",
        result_url=f"/api/result/{claim.id}",
    )


@router.post("/verify", response_model=VerifyResponse, status_code=status.HTTP_202_ACCEPTED)
async def verify(
    body: VerifyRequest, request: Request, response: Response, session: AsyncSession = Depends(get_session)
):
    """Verify a claim.

    Text is redacted (phone numbers, e-mails, @handles) before storage. A text claim that
    repeats a public verdict from the last REPEAT_WINDOW_DAYS returns that verdict immediately
    with cached=true and no model calls; an older match is re-verified as a new version.
    """
    text = redact_pii((body.text or "").strip())
    if not (text or body.url or body.image_base64 or body.image_url):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Provide text, url, image_base64 or image_url")
    if text and not (body.url or body.image_base64 or body.image_url) and len(text) < 8:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Claim is too short to verify")

    if body.image_base64:
        try:
            validate_screenshot(body.image_base64)
        except InputError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None

    limiter.check(request.client.host if request.client else "unknown")

    if body.image_base64 or body.image_url:
        input_type, source_url = "image", body.image_url
    elif body.url:
        input_type, source_url = "url", body.url
    else:
        input_type, source_url = "text", None

    if check_sensitive(text):
        # Private-person / self-harm rule: before any search, model call or public write.
        # Only a generic label is stored; the input text is not kept anywhere.
        withheld = Claim(
            input_type=input_type,
            raw_input=WITHHELD_LABEL,
            claim_text=WITHHELD_LABEL,
            input_hash="",
            normalized_text=None,
            status="withheld",
            slug=new_slug(),
            is_public=False,
        )
        session.add(withheld)
        await session.commit()
        response.status_code = status.HTTP_200_OK
        return VerifyResponse(
            request_id=withheld.id,
            slug=withheld.slug,
            status="withheld",
            mode="withheld",
            message=PRIVATE_PERSON_MESSAGE,
            stream_url=f"/api/stream/{withheld.id}",
            result_url=f"/api/result/{withheld.id}",
        )

    normalized = normalize(text)
    previous: Claim | None = None
    if input_type == "text":
        found = await lookup_repeat(session, normalized)
        if found:
            match_claim, match = found
            if is_fresh(match_claim.created_at):
                match_claim.repeat_count = (match_claim.repeat_count or 0) + 1
                await session.commit()
                response.status_code = status.HTTP_200_OK
                return _response(match_claim, "registry", cached=True, matched_at=match_claim.created_at,
                                 score=match.score)
            previous = match_claim

    platform = (body.platform or "web").lower()
    claim = Claim(
        input_type=input_type,
        raw_input=text,
        input_hash=input_hash(text) if text else "",
        normalized_text=normalized or None,
        source_url=source_url,
        image_data=body.image_base64,
        requested_language=(body.language or "auto").lower(),
        platform=platform if platform in PLATFORMS else "web",
        status="queued",
        slug=new_slug(),
        is_public=body.visibility == "public",
        previous_id=previous.id if previous else None,
        version=(previous.version or 1) + 1 if previous else 1,
    )
    session.add(claim)
    await session.commit()

    mode = dispatch(claim.id)
    return _response(claim, mode)
