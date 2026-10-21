"""Per-request pipeline event log that SSE subscribers can replay and follow.

MemoryBus is used when the pipeline runs in the API process.
RedisBus is used when the pipeline runs in a Celery worker (USE_CELERY=true).
"""
import asyncio
import json
import time
from collections.abc import AsyncIterator

from config import settings

TERMINAL = {"result", "error", "withheld"}
RETENTION_SECONDS = 3600


class MemoryBus:
    def __init__(self) -> None:
        self._events: dict[str, list[dict]] = {}
        self._signals: dict[str, asyncio.Event] = {}
        self._touched: dict[str, float] = {}

    def _gc(self) -> None:
        cutoff = time.time() - RETENTION_SECONDS
        for rid in [r for r, t in self._touched.items() if t < cutoff]:
            self._events.pop(rid, None)
            self._signals.pop(rid, None)
            self._touched.pop(rid, None)

    def _signal(self, rid: str) -> asyncio.Event:
        return self._signals.setdefault(rid, asyncio.Event())

    async def publish(self, rid: str, event: dict) -> None:
        event = json.loads(json.dumps(event, default=str))  # snapshot: callers keep mutating their state
        self._events.setdefault(rid, []).append(event)
        self._touched[rid] = time.time()
        sig = self._signal(rid)
        sig.set()
        self._signals[rid] = asyncio.Event()
        self._gc()

    def has(self, rid: str) -> bool:
        return rid in self._events

    async def subscribe(self, rid: str, timeout: float = 180) -> AsyncIterator[dict]:
        idx = 0
        deadline = time.monotonic() + timeout
        while True:
            events = self._events.get(rid, [])
            while idx < len(events):
                ev = events[idx]
                idx += 1
                yield ev
                if ev["type"] in TERMINAL:
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            try:
                await asyncio.wait_for(self._signal(rid).wait(), timeout=min(remaining, 15))
            except asyncio.TimeoutError:
                yield {"type": "ping"}


class RedisBus:
    KEY = "nemesis:events:"

    def __init__(self) -> None:
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

    async def publish(self, rid: str, event: dict) -> None:
        key = self.KEY + rid
        await self._redis.rpush(key, json.dumps(event))
        await self._redis.expire(key, RETENTION_SECONDS)

    def has(self, rid: str) -> bool:  # existence is checked lazily in subscribe
        return True

    async def subscribe(self, rid: str, timeout: float = 180) -> AsyncIterator[dict]:
        key = self.KEY + rid
        idx = 0
        deadline = time.monotonic() + timeout
        last_ping = time.monotonic()
        while time.monotonic() < deadline:
            batch = await self._redis.lrange(key, idx, -1)
            for raw in batch:
                idx += 1
                ev = json.loads(raw)
                yield ev
                if ev["type"] in TERMINAL:
                    return
            if time.monotonic() - last_ping > 15:
                last_ping = time.monotonic()
                yield {"type": "ping"}
            await asyncio.sleep(0.25)


_bus: MemoryBus | RedisBus | None = None


def reset_bus() -> None:
    global _bus
    _bus = None


def get_bus() -> MemoryBus | RedisBus:
    global _bus
    if _bus is None:
        _bus = RedisBus() if settings.USE_CELERY else MemoryBus()
    return _bus
