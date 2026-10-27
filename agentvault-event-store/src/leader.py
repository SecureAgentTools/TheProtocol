"""
Redis-based leader election for EventStore background tasks.

Mirrors the registry's `background_tasks/leader.py` — same API, same Redis-NX
pattern, same fail-CLOSED semantics (§W0 2026-08-15): with REDIS_URL set, an
unreachable Redis means NO worker is leader until it returns — failing open
there crowns all N gunicorn workers leader at once and N-plies every
leader-gated poller for the duration of the blip. No REDIS_URL at all is
deliberate single-worker mode and stays fail-open; ES_LEADER_FAIL_OPEN=true
restores fail-open with REDIS_URL set. Lives separately because EventStore is
its own Python package and can't import the registry codebase.

When running multiple uvicorn workers (--workers N), each worker forks the same
process and starts the same background tasks. Without leader election, an
expensive periodic task (e.g., events_by_type GROUP BY) runs N times per cycle.
With leader election, only one worker runs it per cycle.

Usage:
    from src.leader import try_acquire_leadership

    if await try_acquire_leadership("eventstore_events_by_type_refresh"):
        # Only the leader gets here this cycle
        await do_expensive_query()
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# Unique worker ID — survives multiple task starts within the same process.
WORKER_ID = f"es-worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

LOCK_TTL = 90          # seconds — refresh loop runs every 60s, give 30s slack
RENEW_INTERVAL = 30
LEADER_CHECK_INTERVAL = 5

_redis_pool: Optional[aioredis.Redis] = None
_redis_available: Optional[bool] = None
_no_redis_url = False


def _fail_open_override() -> bool:
    """ES_LEADER_FAIL_OPEN=true restores the pre-§W0 fail-open behavior."""
    return os.getenv("ES_LEADER_FAIL_OPEN", "false").strip().lower() in ("1", "true", "yes")


async def get_redis() -> Optional[aioredis.Redis]:
    """Get shared Redis connection. Returns None if Redis is not configured.
    Retries on connection failure (handles startup race with Redis container)."""
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
        logger.info("[ES-Leader] REDIS_URL not set — leader election disabled (single-worker mode)")
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
            logger.info(f"[ES-Leader] Redis connected ({redis_url.rsplit('@', 1)[-1]}), worker_id={WORKER_ID}")
        return _redis_pool
    except Exception as e:
        was_available = _redis_available
        if was_available is not False:
            mode = "failing OPEN (ES_LEADER_FAIL_OPEN)" if _fail_open_override() else "leader-gated tasks pause (fail closed)"
            logger.warning(f"[ES-Leader] Redis connection failed ({e}) — {mode}, will retry")
        _redis_available = False
        _redis_pool = None
        return None


def _lock_key(task_name: str) -> str:
    return f"leader:eventstore:{task_name}"


async def try_acquire_leadership(task_name: str) -> bool:
    """Try to become the leader for a task. Non-blocking.
    Returns True if this worker is now the leader, False otherwise.

    Failure direction: with REDIS_URL set, an unreachable Redis fails CLOSED —
    no worker is leader until Redis returns (get_redis logs the transition, and
    each leader-gated consumer logs when it stops). No REDIS_URL is deliberate
    single-worker mode and fails open; ES_LEADER_FAIL_OPEN=true restores
    fail-open with REDIS_URL set."""
    r = await get_redis()
    if r is None:
        if _no_redis_url or _fail_open_override():
            return True  # Deliberate single-worker mode (or explicit override)
        return False  # REDIS_URL set but Redis unreachable — fail CLOSED

    key = _lock_key(task_name)
    try:
        # SET NX (only if not exists) with TTL.
        acquired = await r.set(key, WORKER_ID, nx=True, ex=LOCK_TTL)
        if acquired:
            logger.info(f"[ES-Leader] {WORKER_ID} acquired '{task_name}'")
            return True

        # Already holding it (renewal path within same process).
        current = await r.get(key)
        if current == WORKER_ID:
            await r.expire(key, LOCK_TTL)
            return True

        return False
    except Exception as e:
        if _no_redis_url or _fail_open_override():
            logger.warning(f"[ES-Leader] Redis error acquiring '{task_name}': {e} — failing open")
            return True
        logger.warning(f"[ES-Leader] Redis error acquiring '{task_name}': {e} — failing CLOSED")
        return False


# Atomic compare-and-extend. Renewing with a bare EXPIRE is WRONG: if our lock
# already lapsed and another worker took it, EXPIRE would extend THEIR lock while
# we carry on believing we hold it. Only extend when the value is still ours.
_RENEW_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] "
    "then return redis.call('expire', KEYS[1], ARGV[2]) "
    "else return 0 end"
)


async def _renew_leadership_loop(task_name: str) -> None:
    """Keep the lock alive for as long as the guarded work is still running."""
    key = _lock_key(task_name)
    while True:
        await asyncio.sleep(RENEW_INTERVAL)
        try:
            r = await get_redis()
            if r is None:
                continue  # No Redis = single-worker mode, nothing to renew.
            extended = await r.eval(_RENEW_LUA, 1, key, WORKER_ID, str(LOCK_TTL))
            if not extended:
                # We no longer own it. Someone else may now be running the same
                # work concurrently — the exact condition this loop exists to
                # prevent — so say so loudly rather than failing silently.
                logger.warning(
                    f"[ES-Leader] {WORKER_ID} LOST '{task_name}' while still working "
                    f"(lock reassigned or flushed) — concurrent execution possible"
                )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Never let a renewal failure kill the work it is guarding.
            logger.warning(f"[ES-Leader] Renewal of '{task_name}' failed: {e}")


@asynccontextmanager
async def hold_leadership(task_name: str):
    """Acquire leadership and HOLD it for the whole duration of the block.

    `try_acquire_leadership` alone only guards who STARTS. The caller then blocks
    inside its query and never renews, so any run that outlives LOCK_TTL frees the
    lock mid-flight and the next tick lets another worker start a SECOND concurrent
    copy of the same expensive work. Each extra copy makes the box slower, which
    makes the work take longer, which produces more overlap — self-amplifying.

    That is the 2026-07-31 EventStore incident: the 71 GB `events` GROUP BY runs in
    ~26s with warm page cache (inside the 90s TTL), but after a mass container
    restart evicted the cache it crossed 90s and piled up to 16 concurrent scans on
    frame-b, taking the host to load 428.

    This heartbeats the lock every RENEW_INTERVAL so a slow run keeps its lock and
    overlap becomes structurally impossible, however long the work takes.

    Failure direction follows try_acquire_leadership: no REDIS_URL means every
    worker is the leader (single-worker mode); an unreachable Redis with
    REDIS_URL set means NO worker is the leader until it returns.

        async with hold_leadership("my_task") as is_leader:
            if is_leader:
                await do_expensive_query()
    """
    is_leader = await try_acquire_leadership(task_name)
    heartbeat: Optional[asyncio.Task] = None
    if is_leader:
        heartbeat = asyncio.create_task(_renew_leadership_loop(task_name))
    try:
        yield is_leader
    finally:
        if heartbeat is not None:
            heartbeat.cancel()
            try:
                await heartbeat
            except (asyncio.CancelledError, Exception):
                pass


async def release_leadership(task_name: str) -> None:
    """Release leadership on shutdown. Best-effort."""
    r = await get_redis()
    if r is None:
        return

    key = _lock_key(task_name)
    try:
        # Only delete if we hold it (Lua script for atomicity).
        lua = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        await r.eval(lua, 1, key, WORKER_ID)
        logger.info(f"[ES-Leader] Released '{task_name}'")
    except Exception as e:
        logger.warning(f"[ES-Leader] Redis error releasing '{task_name}': {e}")


async def close_redis() -> None:
    """Close the Redis connection pool on shutdown."""
    global _redis_pool, _redis_available
    if _redis_pool:
        try:
            await _redis_pool.aclose()
        except Exception:
            pass
        _redis_pool = None
        _redis_available = None
