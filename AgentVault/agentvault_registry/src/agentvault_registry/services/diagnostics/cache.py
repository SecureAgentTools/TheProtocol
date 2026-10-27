"""Redis-backed result cache for Command Center diagnostic checks.

Cache key: diag:{check_id}:{target}
TTL:       30 seconds (overridable per call)
Format:    JSON-serialized CheckResult
"""

import json
import logging
from typing import Optional

from agentvault_registry.background_tasks.leader import get_redis

from .schemas import CheckResult

logger = logging.getLogger(__name__)

CACHE_TTL_SECONDS = 30
CACHE_KEY_PREFIX = "diag"


def _key(check_id: str, target: str) -> str:
    return f"{CACHE_KEY_PREFIX}:{check_id}:{target}"


async def get_cached(check_id: str, target: str) -> Optional[CheckResult]:
    """Return a cached CheckResult if fresh, else None."""
    r = await get_redis()
    if r is None:
        return None
    try:
        raw = await r.get(_key(check_id, target))
        if not raw:
            return None
        return CheckResult.model_validate_json(raw)
    except Exception as e:
        logger.debug(f"[diag-cache] get failed: {e}")
        return None


async def set_cached(result: CheckResult, ttl: int = CACHE_TTL_SECONDS) -> None:
    """Store a CheckResult in Redis with TTL."""
    r = await get_redis()
    if r is None:
        return
    try:
        payload = result.model_dump_json()
        await r.setex(_key(result.check_id, result.target), ttl, payload)
    except Exception as e:
        logger.debug(f"[diag-cache] set failed: {e}")


async def invalidate(check_id: str, target: str) -> None:
    """Drop a cache entry (used after remediation actions to force re-check)."""
    r = await get_redis()
    if r is None:
        return
    try:
        await r.delete(_key(check_id, target))
    except Exception:
        pass
