"""Gemma 4 through the Gemini API (google-genai SDK).

call_gemma        -> JSON reasoning call (same LLMResult shape as the Groq client)
call_gemma_vision -> text + description extracted from a screenshot
provider()        -> "gemini" or "groq" (MODEL_PROVIDER, else gemini only if a key is set)

The API key is read from settings (environment / backend .env) and never appears in logs or
in raised exceptions: provider errors are re-raised as LLMError with the key masked and the
original exception chain suppressed.
"""
import asyncio
import base64
import re
import time

from google import genai
from google.genai import types
from loguru import logger

from config import settings
from models.groq_client import LLMError, LLMJSONError, LLMResult, parse_json

_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_TRANSIENT = ("429", "500", "503", "UNAVAILABLE", "INTERNAL", "RESOURCE_EXHAUSTED", "DEADLINE")
_genai_client: genai.Client | None = None


def provider() -> str:
    """Active provider for the Gemma-capable steps: MODEL_PROVIDER if set, else by key presence."""
    chosen = (settings.MODEL_PROVIDER or "").strip().lower()
    if chosen in ("gemini", "groq"):
        return chosen
    return "gemini" if settings.GEMINI_API_KEY else "groq"


def _client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        if not settings.GEMINI_API_KEY:
            raise LLMError("GEMINI_API_KEY is not set")
        _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _genai_client


def _safe(exc: BaseException) -> str:
    """Exception text with any API key masked."""
    text = f"{type(exc).__name__}: {exc}"
    if settings.GEMINI_API_KEY:
        text = text.replace(settings.GEMINI_API_KEY, "****")
    return _KEY_PATTERN.sub("****", text)[:300]


async def _generate(contents, config: types.GenerateContentConfig):
    """One Gemma request with up to two retries on transient provider errors."""
    for attempt in range(3):
        try:
            return await _client().aio.models.generate_content(
                model=settings.GEMMA_MODEL, contents=contents, config=config
            )
        except LLMError:
            raise
        except Exception as exc:  # noqa: BLE001 - provider SDK raises many types
            message = _safe(exc)
            if attempt < 2 and any(code in message for code in _TRANSIENT):
                logger.warning(f"Gemma transient error, retrying: {message[:120]}")
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            raise LLMError(f"Gemma call failed: {message}") from None
    raise LLMError("Gemma call failed after retries")


async def call_gemma(system: str, user: str, max_tokens: int = 3000, temperature: float = 0.2) -> LLMResult:
    """JSON-mode reasoning call to GEMMA_MODEL; returns the same LLMResult as the Groq client."""
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=temperature,
        max_output_tokens=max_tokens,
    )
    t0 = time.perf_counter()
    for attempt in range(2):
        resp = await _generate(user, config)
        try:
            data = parse_json(resp.text or "")
            break
        except LLMJSONError:
            if attempt == 1:
                raise
            logger.debug(f"{settings.GEMMA_MODEL} returned malformed JSON; retrying once")
    ms = int((time.perf_counter() - t0) * 1000)
    usage = getattr(resp, "usage_metadata", None)
    tokens = getattr(usage, "total_token_count", 0) or 0
    logger.debug(f"{settings.GEMMA_MODEL} {ms}ms {tokens}tok")
    return LLMResult(data=data, model=settings.GEMMA_MODEL, ms=ms, tokens=tokens)


async def call_gemma_vision(image_b64: str, mime: str, prompt: str) -> str:
    """Send an image plus the claim-extraction instruction to GEMMA_MODEL; returns its text."""
    part = types.Part.from_bytes(data=base64.b64decode(image_b64), mime_type=mime)
    resp = await _generate([part, prompt], types.GenerateContentConfig(temperature=0, max_output_tokens=1200))
    return (resp.text or "").strip()
