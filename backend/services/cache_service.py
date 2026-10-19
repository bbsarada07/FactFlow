"""Verdict cache: Redis when reachable, otherwise an in-process TTL cache."""
import json

from cachetools import TTLCache
from loguru import logger

from config import settings

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None


class CacheService:
    PREFIX = "nemesis:verdict:"

    def __init__(self) -> None:
        self.ttl = settings.CACHE_TTL_HOURS * 3600
        self._local: TTLCache = TTLCache(maxsize=2048, ttl=self.ttl)
        self._redis = None
        self._checked = False

    async def _backend(self):
        if not self._checked:
            self._checked = True
            if aioredis is not None:
                try:
                    r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1, decode_responses=True)
                    await r.ping()
                    self._redis = r
                    logger.info("Verdict cache: Redis")
                except Exception as exc:  # noqa: BLE001
                    logger.info(f"Verdict cache: in-memory (Redis unavailable: {exc.__class__.__name__})")
        return self._redis

    def reset(self) -> None:
        """Drop the Redis client (it is bound to the event loop that created it)."""
        self._redis = None
        self._checked = False

    @property
    def backend_name(self) -> str:
        return "redis" if self._redis is not None else "memory"

    async def get(self, key: str) -> dict | None:
        r = await self._backend()
        if r is not None:
            try:
                raw = await r.get(self.PREFIX + key)
                return json.loads(raw) if raw else None
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Redis get failed: {exc}")
        return self._local.get(key)

    async def set(self, key: str, value: dict) -> None:
        self._local[key] = value
        r = await self._backend()
        if r is not None:
            try:
                await r.set(self.PREFIX + key, json.dumps(value), ex=self.ttl)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Redis set failed: {exc}")

    async def ping(self) -> bool:
        r = await self._backend()
        if r is None:
            return False
        try:
            return bool(await r.ping())
        except Exception:  # noqa: BLE001
            return False


cache = CacheService()
