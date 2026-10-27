"""
TEG-side Redis client (lazy singleton).

Mirrors the registry's `background_tasks/leader.py:get_redis()` pattern so cross-
worker state (cache invalidation channels, the external blocklist SET, etc.)
shares one connection per uvicorn worker.

REDIS_URL is the only required env. When unset or unreachable, callers fall
back to in-memory state — TTL refresh / next admin call is the safety net.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

_redis_pool: Optional[aioredis.Redis] = None
_redis_available: Optional[bool] = None
_no_redis_url: bool = False


async def get_redis() -> Optional[aioredis.Redis]:
    """Return the shared Redis connection, or None if Redis isn't configured
    or is unreachable. Verifies pool health on every call so a transient
    drop self-heals on the next request."""
    global _redis_pool, _redis_available, _no_redis_url

    if _no_redis_url:
        return None

    if _redis_pool is not None:
        try:
            await _redis_pool.ping()
            return _redis_pool
        except Exception:
            _redis_pool = None
            _redis_available = None

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        _no_redis_url = True
        logger.info("[TEG-Redis] REDIS_URL not set — module-level fallback only")
        return None

    try:
        _redis_pool = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        await _redis_pool.ping()
        was_available = _redis_available
        _redis_available = True
        if was_available is not True:
            # §MTLSHOPS G3: REDIS_URL carries this client's Redis password; log the host part only
            logger.info(f"[TEG-Redis] connected ({redis_url.rsplit('@', 1)[-1]})")
        return _redis_pool
    except Exception as e:
        was_available = _redis_available
        if was_available is not False:
            logger.warning(f"[TEG-Redis] connection failed ({e}) — falling back")
        _redis_available = False
        _redis_pool = None
        return None


async def close_redis() -> None:
    """Close the pool on shutdown."""
    global _redis_pool, _redis_available
    if _redis_pool is not None:
        try:
            await _redis_pool.aclose()
        except Exception:
            pass
        _redis_pool = None
        _redis_available = None
        logger.info("[TEG-Redis] connection closed")
