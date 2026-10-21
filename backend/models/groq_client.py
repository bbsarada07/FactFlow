"""Groq inference via the OpenAI-compatible API.

call_nano  -> fast tier (NANO_MODEL), used by most agents
call_ultra -> deep tier (ULTRA_MODEL), used by Deep Reasoning
call_vision -> extracts text from screenshots when Tesseract is unavailable
"""
import json
import re
import time
from dataclasses import dataclass

import openai
from loguru import logger
from openai import AsyncOpenAI
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config import settings

_client: AsyncOpenAI | None = None

# Claim-extraction instruction for screenshots (shared with the Gemma client).
VISION_PROMPT = (
    "Transcribe every piece of readable text in this image exactly, in its "
    "original language. Then, on a new line starting with 'IMAGE:', describe "
    "in one sentence what the image shows. Output nothing else."
)

RETRYABLE = (
    openai.RateLimitError,
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.InternalServerError,
)


class LLMError(RuntimeError):
    pass


class LLMJSONError(LLMError):
    pass


@dataclass
class LLMResult:
    data: dict
    model: str
    ms: int
    tokens: int


def client() -> AsyncOpenAI:
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise LLMError("GROQ_API_KEY is not set in backend/.env")
        _client = AsyncOpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url=settings.GROQ_BASE_URL,
            timeout=settings.LLM_TIMEOUT_SECONDS,
            max_retries=0,
        )
    return _client


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(raw: str) -> dict:
    text = _FENCE.sub("", (raw or "").strip())
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise LLMJSONError(f"Model did not return JSON: {text[:200]!r}")
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMJSONError(f"Malformed JSON from model: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMJSONError("Model returned JSON that is not an object")
    return value


def _extra_params(model: str, effort: str) -> dict:
    return {"reasoning_effort": effort} if effort and "gpt-oss" in model else {}


_TRY_AGAIN = re.compile(r"try again in ([\d.]+)(ms|s)")
_backoff = wait_exponential(multiplier=0.8, min=0.8, max=8)


def _wait(state) -> float:
    """Honour the provider's retry hint on 429s (free tiers have tight per-minute token limits)."""
    exc = state.outcome.exception() if state.outcome else None
    if isinstance(exc, openai.RateLimitError):
        header = exc.response.headers.get("retry-after") if exc.response is not None else None
        try:
            return min(float(header) + 0.3, 20)
        except (TypeError, ValueError):
            pass
        m = _TRY_AGAIN.search(str(exc))
        if m:
            secs = float(m.group(1)) / (1000 if m.group(2) == "ms" else 1)
            return min(secs + 0.3, 20)
        return 6.0
    return _backoff(state)


@retry(
    retry=retry_if_exception_type((*RETRYABLE, LLMJSONError)),
    stop=stop_after_attempt(5),
    wait=_wait,
    reraise=True,
)
async def _chat_json(model: str, effort: str, system: str, user: str, max_tokens: int, temperature: float) -> LLMResult:
    t0 = time.perf_counter()
    tokens = 0
    for budget in (max_tokens, max_tokens * 2):
        last = budget != max_tokens
        try:
            resp = await client().chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=budget,
                **_extra_params(model, effort),
            )
        except openai.BadRequestError as exc:
            # Groq rejects JSON-mode generations that were cut off or malformed.
            if "json_validate_failed" not in str(exc):
                raise
            if last:
                raise LLMJSONError(f"{model} could not produce valid JSON") from exc
            logger.debug(f"{model} JSON validation failed at max_tokens={budget}; retrying with a larger budget")
            continue
        tokens += resp.usage.total_tokens if resp.usage else 0
        content = resp.choices[0].message.content or ""
        try:
            data = parse_json(content)
            break
        except LLMJSONError:
            if resp.choices[0].finish_reason != "length" or last:
                raise
            logger.debug(f"{model} hit max_tokens={budget}; retrying with a larger budget")
    ms = int((time.perf_counter() - t0) * 1000)
    logger.debug(f"{model} {ms}ms {tokens}tok")
    return LLMResult(data=data, model=model, ms=ms, tokens=tokens)


async def call_nano(system: str, user: str, max_tokens: int = 1500, temperature: float = 0.2) -> LLMResult:
    try:
        return await _chat_json(settings.NANO_MODEL, settings.NANO_REASONING_EFFORT, system, user, max_tokens, temperature)
    except openai.APIError as exc:
        raise LLMError(f"Nano model call failed: {exc}") from exc


async def call_ultra(system: str, user: str, max_tokens: int = 3000, temperature: float = 0.2) -> LLMResult:
    try:
        return await _chat_json(settings.ULTRA_MODEL, settings.ULTRA_REASONING_EFFORT, system, user, max_tokens, temperature)
    except openai.APIError as exc:
        raise LLMError(f"Ultra model call failed: {exc}") from exc


@retry(
    retry=retry_if_exception_type(RETRYABLE),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.8, min=0.8, max=8),
    reraise=True,
)
async def call_vision(image_b64: str, mime: str = "image/png") -> str:
    """Transcribe all readable text in an image (screenshot of a forward, post, etc.)."""
    resp = await client().chat.completions.create(
        model=settings.VISION_MODEL,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": VISION_PROMPT,
                    },
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
                ],
            }
        ],
        temperature=0,
        max_tokens=1200,
    )
    return (resp.choices[0].message.content or "").strip()
