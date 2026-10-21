"""Gemma 4 through the Gemini API (google-genai SDK) — screenshot reading only.

read_screenshot -> the visible text and a short list of visible cues. Gemma never produces a
verdict, a confidence or a correction: every reply goes through parse_vision_output, which
keeps only text and cues.

The API key is read from settings (environment / backend .env) and never appears in logs or
in raised exceptions: provider errors are re-raised as LLMError with the key masked and the
original exception chain suppressed.
"""
import asyncio
import base64
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types
from loguru import logger

from config import settings
from models.groq_client import VISION_PROMPT, LLMError
from models.vision_output import parse_vision_output

_KEY_PATTERN = re.compile(r"AIza[0-9A-Za-z_\-]{20,}")
_TRANSIENT = ("429", "500", "503", "UNAVAILABLE", "INTERNAL", "RESOURCE_EXHAUSTED", "DEADLINE")
_genai_client: genai.Client | None = None


@dataclass
class VisionRead:
    """What a vision model may return: the visible text and visible cues. Nothing else."""

    text: str
    cues: list[str] = field(default_factory=list)


def vision_available() -> bool:
    """True when screenshots should go to Gemma: VISION_PROVIDER is gemini and a key is set."""
    return settings.VISION_PROVIDER == "gemini" and bool(settings.GEMINI_API_KEY)


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


async def read_screenshot(image_b64: str, mime: str) -> VisionRead:
    """Send a screenshot with the shared VISION_PROMPT to GEMMA_MODEL; keep only text and cues."""
    part = types.Part.from_bytes(data=base64.b64decode(image_b64), mime_type=mime)
    resp = await _generate([part, VISION_PROMPT], types.GenerateContentConfig(temperature=0, max_output_tokens=1200))
    text, cues = parse_vision_output(resp.text or "")
    return VisionRead(text=text, cues=cues)
