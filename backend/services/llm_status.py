"""Why the AI part of an analysis did not run, and a breaker for an exhausted daily quota.

When the provider says the daily token quota is used up, every later model call would only wait
and fail. The breaker remembers that until the provider's retry time, so analyses go straight to
rules-only and say so (`llm_status.state = "quota_exhausted"`) instead of waiting on each email.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass

import openai

_RETRY_IN = re.compile(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", re.IGNORECASE)
_DAILY = re.compile(r"per day|\bTPD\b|\bRPD\b", re.IGNORECASE)


@dataclass(frozen=True)
class LLMProblem:
    state: str  # quota_exhausted | llm_unavailable
    reason: str
    retry_after_seconds: int | None = None


def _chain(exc: BaseException):
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        yield exc
        exc = exc.__cause__ or exc.__context__


def _retry_after(text: str) -> int | None:
    m = _RETRY_IN.search(text or "")
    if not m or not any(m.groups()):
        return None
    h, mins, secs = (float(g) if g else 0.0 for g in m.groups())
    return int(h * 3600 + mins * 60 + secs) + 1


def classify(exc: BaseException) -> LLMProblem:
    """Describe a failed model call in words a user can act on (no secrets in the text)."""
    for e in _chain(exc):
        if isinstance(e, openai.RateLimitError):
            text = str(e)
            if _DAILY.search(text):
                return LLMProblem("quota_exhausted", "the daily model quota is used up", _retry_after(text))
            return LLMProblem("llm_unavailable", "the model provider is rate-limiting requests", _retry_after(text))
        if isinstance(e, TimeoutError):
            return LLMProblem("llm_unavailable", "the model did not answer in time")
        if "GROQ_API_KEY is not set" in str(e):
            return LLMProblem("llm_unavailable", "no model API key is configured")
        if isinstance(e, (openai.APIConnectionError, openai.APITimeoutError)):
            return LLMProblem("llm_unavailable", "the model provider could not be reached")
    return LLMProblem("llm_unavailable", f"the model call failed ({type(exc).__name__})")


class QuotaBreaker:
    """Open while the daily quota is known to be exhausted."""

    DEFAULT_COOLDOWN = 600

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self._until = 0.0

    def trip(self, retry_after_seconds: int | None) -> None:
        self._until = max(self._until, self.clock() + (retry_after_seconds or self.DEFAULT_COOLDOWN))

    def remaining(self) -> int:
        """Seconds until model calls are tried again (0 = closed)."""
        return max(0, int(self._until - self.clock()))

    def reset(self) -> None:
        self._until = 0.0


breaker = QuotaBreaker()
