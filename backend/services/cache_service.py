"""Redis reachability check for /health.

Verdict reuse is handled by the public registry (services/registry.py), which works
the same with or without Redis. Redis is only required for the Celery queue mode.
"""
from config import settings

try:
    import redis.asyncio as aioredis
except ImportError:  # pragma: no cover
    aioredis = None


async def redis_ping() -> bool:
    """True if Redis at REDIS_URL answers PING within one second."""
    if aioredis is None:
        return False
    client = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001 - any failure means "not reachable"
        return False
    finally:
        await client.aclose()
