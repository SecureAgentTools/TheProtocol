"""
Redis-based leader election for background tasks.

When running multiple uvicorn workers (--workers N), each worker forks the same
process and starts the same background tasks. This module ensures only ONE worker
runs each singleton task (e.g., staking distributor, supply auditor).

Pattern:
    1. On startup, each worker tries to acquire a Redis lock for each task.
    2. Only the worker that gets the lock runs the task.
    3. The lock has a TTL (30s) and is renewed every 15s.
    4. If the leader dies, the lock expires and another worker takes over.

Usage:
    from agentvault_registry.background_tasks.leader import (
        get_redis, is_leader, run_with_leadership,
    )

    async def my_task_loop():
        async for _ in run_with_leadership("my_task", interval=60):
            await do_work()

⚠ `is_leader()` DOES NOT ACQUIRE — it only reports whether THIS process already
holds the lock. A loop gated on it never becomes leader and therefore never runs
(that is how `recent_events_ring` sat deployed, healthy and idle). Class-based
tasks use `BackgroundWorker` (background_tasks/_worker_base.py), which calls
`try_acquire_leadership` for you and stamps §VITALS.
"""
import asyncio
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import AsyncIterator, Optional

import redis.asyncio as aioredis

from time import monotonic as _monotonic
from agentvault_registry.services.pubsub_backoff import (
    jittered as _jittered,
    spread as _spread,
)

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Prometheus instrumentation (added 2026-04-30 — Grafana Workers dashboard)
#
# We track:
#   worker_leader_acquisitions_total{task,registry,outcome}
#       outcome ∈ {acquired, not_acquired, renewed, lost, fail_open}
#   worker_is_leader{task,registry}  — 0/1 gauge per worker; sum across workers
#       is the cluster leader count (should be 0 or 1).
#
# Per-cycle work duration is *not* instrumented at this layer because too
# many workers don't pass through this module. A per-task helper in
# `worker_metrics.py` provides `record_worker_run()` for tasks that opt in.
# ----------------------------------------------------------------------
try:
    from prometheus_client import Counter as _LCounter, Gauge as _LGauge

    WORKER_LEADER_ACQUISITIONS_TOTAL = _LCounter(
        "worker_leader_acquisitions_total",
        "Background-task leader-election outcomes",
        labelnames=["task", "registry", "outcome"],
    )
    WORKER_IS_LEADER = _LGauge(
        "worker_is_leader",
        "1 if this worker holds the leader lock for the task; 0 otherwise",
        labelnames=["task", "registry"],
    )
    _LEADER_PROM_AVAILABLE = True
except ImportError:  # pragma: no cover
    _LEADER_PROM_AVAILABLE = False
    WORKER_LEADER_ACQUISITIONS_TOTAL = None  # type: ignore[assignment]
    WORKER_IS_LEADER = None  # type: ignore[assignment]


def _worker_registry_label() -> str:
    return os.getenv("REGISTRY_NAME", "registry")

# Unique ID for this worker process (survives across task restarts within same process)
WORKER_ID = f"worker-{os.getpid()}-{uuid.uuid4().hex[:8]}"

# Global Redis connection pool (lazy init)
_redis_pool: Optional[aioredis.Redis] = None
_redis_available: Optional[bool] = None

LOCK_TTL = 30          # Lock expires after 30 seconds if not renewed
RENEW_INTERVAL = 15    # Renew lock every 15 seconds
LEADER_CHECK_INTERVAL = 5  # How often non-leaders check if they can become leader

# §JITTER-2 — dial cooldown while Redis is known-unavailable, and spread for the poll loop.
_REDIS_DIAL_BACKOFF = float(os.getenv("LEADER_REDIS_DIAL_BACKOFF", "10"))
_redis_retry_at = 0.0


_no_redis_url = False  # True if REDIS_URL is genuinely not configured


async def get_redis() -> Optional[aioredis.Redis]:
    """Get shared Redis connection. Returns None if Redis is not configured.
    Retries on connection failure (handles startup race with Redis container)."""
    global _redis_pool, _redis_available, _no_redis_url

    if _no_redis_url:
        return None

    if _redis_pool is not None:
        # Verify the pool is still alive
        try:
            await _redis_pool.ping()
            return _redis_pool
        except Exception:
            _redis_pool = None
            # NOT None: resetting to None re-arms the "connection failed" warning below on the
            # very next call, which is why a short DNS blip produced a warning per worker per
            # 5s cycle instead of one per outage.
            _redis_available = False

    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        _no_redis_url = True
        logger.info("[Leader] REDIS_URL not set — leader election disabled (single-worker mode)")
        return None

    # §JITTER-2 — do not re-dial on EVERY call while Redis is known-unavailable.
    # Leader election is the highest-volume Redis client in the process: ~43 background tasks
    # per worker, 38 gunicorn workers per registry, 16 registries. Each call did a fresh
    # from_url()+ping(), so one DNS hiccup turned into thousands of connection attempts per
    # second, fleet-wide, all arriving in lockstep — the herd IS the outage. Hold a jittered
    # cooldown between dial attempts so retry pressure is spread instead of spiked.
    global _redis_retry_at
    if _redis_available is False:
        now = _monotonic()
        if now < _redis_retry_at:
            return None
        _redis_retry_at = now + _jittered(_REDIS_DIAL_BACKOFF)

    try:
        _redis_pool = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
        # Verify connection
        await _redis_pool.ping()
        was_available = _redis_available
        _redis_available = True
        _redis_retry_at = 0.0
        if was_available is not True:
            # §MTLSHOPS G3: REDIS_URL carries this client's Redis password; log the host part only
            logger.info(f"[Leader] Redis connected ({redis_url.rsplit('@', 1)[-1]}), worker_id={WORKER_ID}")
        return _redis_pool
    except Exception as e:
        was_available = _redis_available
        if was_available is not False:
            logger.warning(f"[Leader] Redis connection failed ({e}) — single-worker mode, will retry")
        _redis_available = False
        _redis_pool = None
        return None


async def close_redis():
    """Close Redis connection pool on shutdown."""
    global _redis_pool, _redis_available
    if _redis_pool:
        await _redis_pool.aclose()
        _redis_pool = None
        _redis_available = None
        logger.info("[Leader] Redis connection closed")


def _lock_key(task_name: str) -> str:
    """Redis key for a task's leader lock."""
    return f"leader:{task_name}"


def _emit_leader_metric(task_name: str, outcome: str, is_leader: bool) -> None:
    """Best-effort metric emission for try_acquire_leadership outcomes."""
    if not _LEADER_PROM_AVAILABLE:
        return
    try:
        registry = _worker_registry_label()
        WORKER_LEADER_ACQUISITIONS_TOTAL.labels(
            task=task_name, registry=registry, outcome=outcome
        ).inc()
        WORKER_IS_LEADER.labels(task=task_name, registry=registry).set(
            1 if is_leader else 0
        )
    except Exception:
        pass  # never break a worker because of a metric failure


# §pass47 S1 — fail-closed by default (was fail-open / P20-002).
#
# Distinguish two "no Redis" cases:
#   (a) REDIS_URL never set → legitimate single-worker mode → fail-OPEN safe.
#   (b) REDIS_URL set but Redis unreachable → multi-worker risk of N-way
#       leadership ("everyone is leader") → fail-CLOSED by default.
#
# Opt back to fail-OPEN globally with LEADER_FAIL_OPEN=true (emits a startup
# warning once). Use this only on single-worker deployments or test boxes
# where Redis is intentionally optional.

_LEADER_FAIL_OPEN_LOGGED = False


def _leader_fail_open_env() -> bool:
    return (os.getenv("LEADER_FAIL_OPEN") or "").lower() in ("1", "true", "yes")


def _should_fail_open(task_name: str, reason: str) -> bool:
    """Return True when it's safe for this worker to assume leadership without Redis.

    Always safe when REDIS_URL is genuinely absent (single-worker mode).
    Otherwise gated by LEADER_FAIL_OPEN=true; without it, fail-CLOSED.
    """
    global _LEADER_FAIL_OPEN_LOGGED
    if _no_redis_url:
        return True
    if _leader_fail_open_env():
        if not _LEADER_FAIL_OPEN_LOGGED:
            logger.warning(
                "[Leader] LEADER_FAIL_OPEN=true honored — workers will assume "
                "leadership when Redis is unreachable. Risk: multiple workers "
                "may simultaneously become leader for the same task."
            )
            _LEADER_FAIL_OPEN_LOGGED = True
        return True
    logger.warning(
        f"[Leader] Redis unavailable while attempting '{task_name}' ({reason}); "
        f"fail-CLOSED (this worker will NOT run the task this cycle). "
        f"Set LEADER_FAIL_OPEN=true to restore legacy fail-open behavior."
    )
    return False


async def _stamp_turn(task_name: str) -> None:
    """§VITALS liveness: record that the LEADER's loop turned.

    Every hand-rolled worker loop in the fleet has the same shape — acquire,
    work, sleep, acquire — so an acquire by the process that already holds the
    lock proves the previous turn finished. That makes a HANG visible (a worker
    stuck in its work never comes back to acquire) without editing 32 files.

    It proves LIVENESS, never HEALTH: a loop that turns while every cycle fails
    still stamps a turn. Health is `vitals.stamp`/`vitals.cycle`, which the
    worker calls with its own outcome. Both, or you get velocity_snapshot again:
    a loop that turned faithfully for months and wrote nothing.

    Only the leader stamps — a non-leader turning its loop is not evidence that
    the work is happening anywhere.
    """
    try:
        from . import vitals as _vitals
        await _vitals.stamp_turn(task_name)
    except Exception:
        pass


async def try_acquire_leadership(task_name: str) -> bool:
    """
    Try to become the leader for a task. Non-blocking.
    Returns True if this worker is now the leader.

    §pass47 S1 — fail-closed by default when Redis is unreachable. Set
    LEADER_FAIL_OPEN=true to restore legacy single-worker assumption.

    §29 (2026-07-28) READONLY_MODE: refusing leadership HERE freezes EVERY leader-elected
    background worker in one place — `run_with_leadership`, `leadership_context` and
    `with_leader_election` all funnel through this function, so no worker needs editing and the
    next one added is covered for free. A refused worker simply skips its cycle and retries,
    which is the ordinary non-leader path it already handles. Exempt observability tasks keep
    running; see `middleware.readonly_mode._EXEMPT_TASKS_DEFAULT`.
    """
    # Lazy import: leader.py loads very early in startup and readonly_mode pulls in ..errors, so a
    # module-level import risks a cycle for no benefit. This runs on a timer, not per request —
    # the module-cache lookup is free.
    try:
        from agentvault_registry.middleware.readonly_mode import task_frozen
        if task_frozen(task_name):
            return False
    except Exception:
        pass   # the freeze must never break leader election if the helper is unavailable

    r = await get_redis()
    if r is None:
        decision = _should_fail_open(task_name, "redis_unreachable")
        _emit_leader_metric(task_name, "fail_open" if decision else "fail_closed", decision)
        return decision

    key = _lock_key(task_name)
    try:
        # SET NX (only if not exists) with TTL
        acquired = await r.set(key, WORKER_ID, nx=True, ex=LOCK_TTL)
        if acquired:
            logger.info(f"[Leader] {WORKER_ID} acquired leadership for '{task_name}'")
            _emit_leader_metric(task_name, "acquired", True)
            await _stamp_turn(task_name)
            return True

        # Check if we already hold it (e.g., after restart within same process)
        current = await r.get(key)
        if current == WORKER_ID:
            await r.expire(key, LOCK_TTL)  # Renew
            _emit_leader_metric(task_name, "renewed", True)
            await _stamp_turn(task_name)
            return True

        _emit_leader_metric(task_name, "not_acquired", False)
        return False
    except Exception as e:
        decision = _should_fail_open(task_name, f"redis_error: {e}")
        _emit_leader_metric(task_name, "fail_open" if decision else "fail_closed", decision)
        return decision


async def renew_leadership(task_name: str) -> bool:
    """Renew the lock atomically. Returns False if we lost leadership.

    §pass47 S1 — when Redis is unreachable, fail-closed (return False) so the
    caller knows it cannot prove it's still leader. Set LEADER_FAIL_OPEN=true
    to keep the legacy behavior of pretending to still hold leadership.
    """
    r = await get_redis()
    if r is None:
        return _should_fail_open(task_name, "renew_redis_unreachable")

    key = _lock_key(task_name)
    try:
        # Atomic check-and-renew via Lua script (prevents race between GET and EXPIRE)
        result = await r.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) else return 0 end",
            1, key, WORKER_ID, str(LOCK_TTL)
        )
        if result:
            return True
        else:
            current = await r.get(key)
            logger.warning(f"[Leader] Lost leadership for '{task_name}' (held by {current})")
            _emit_leader_metric(task_name, "lost", False)
            return False
    except Exception as e:
        logger.warning(f"[Leader] Redis error renewing '{task_name}': {e}")
        return False


async def release_leadership(task_name: str):
    """Release leadership on shutdown."""
    r = await get_redis()
    if r is None:
        return

    key = _lock_key(task_name)
    try:
        # Only delete if we hold it (Lua script for atomicity)
        lua = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
        await r.eval(lua, 1, key, WORKER_ID)
        logger.info(f"[Leader] Released leadership for '{task_name}'")
    except Exception as e:
        logger.warning(f"[Leader] Redis error releasing '{task_name}': {e}")


async def is_leader(task_name: str) -> bool:
    """Check if this worker is the leader for a task. Does NOT acquire.

    §pass47 S1 — fail-closed by default when Redis is unreachable. Set
    LEADER_FAIL_OPEN=true to restore legacy single-worker assumption.
    """
    r = await get_redis()
    if r is None:
        return _should_fail_open(task_name, "is_leader_redis_unreachable")

    try:
        current = await r.get(_lock_key(task_name))
        return current == WORKER_ID
    except Exception as e:
        return _should_fail_open(task_name, f"is_leader_redis_error: {e}")


async def _sleep_holding_lease(task_name: str, seconds: float) -> bool:
    """Sleep `seconds`, renewing the lease every RENEW_INTERVAL. False when leadership was lost on the way.

    §LEASE (2026-09-18): the loop used to renew once after the cycle and then sleep the WHOLE interval with
    nothing renewing, so any interval longer than LOCK_TTL left the lock free after 30 s and a non-leader
    poller (LEADER_CHECK_INTERVAL, 5 s) ran the task early. Measured on ASIA over 20.78 h: peer_revival_prober
    declared 120 s and acquired the lease every 34 s, federation_card_gc declared 24 h and acquired 6 times.
    Failover is unchanged: a leader that dies stops renewing and the lock expires within LOCK_TTL.
    """
    deadline = _monotonic() + seconds
    while True:
        remaining = deadline - _monotonic()
        if remaining <= 0:
            return True
        await asyncio.sleep(min(RENEW_INTERVAL, remaining))
        if _monotonic() >= deadline:
            return True
        if not await renew_leadership(task_name):
            logger.info(f"[Leader] '{task_name}' lost leadership while waiting out its interval")
            return False


async def run_with_leadership(task_name: str, interval: float) -> AsyncIterator[None]:
    """
    Async generator that yields control only when this worker is the leader.
    Handles acquisition, renewal, and failover.

    Usage:
        async for _ in run_with_leadership("my_task", interval=60):
            await do_work()
    """
    while True:
        # Try to become leader
        if await try_acquire_leadership(task_name):
            # We're the leader — run the task.
            # §VITALS: the pre-2026-09-04 version stamped "ok" AFTER the yield and
            # nowhere else, so a body that raised stamped nothing at all — which
            # reads exactly like a worker that never ran. Outcome is recorded on
            # BOTH paths now, and the failure is re-raised unchanged.
            from . import vitals as _vitals
            _t0 = _monotonic()
            try:
                yield
            except Exception as _e:
                await _vitals.stamp(
                    task_name, _vitals.OUTCOME_ERROR,
                    duration_ms=int((_monotonic() - _t0) * 1000),
                    error=f"{type(_e).__name__}: {_e}",
                )
                raise
            await _vitals.stamp(
                task_name, _vitals.OUTCOME_OK,
                duration_ms=int((_monotonic() - _t0) * 1000),
            )

            # P5.2 (2026-05-08): the legacy flat keys, still read by the current
            # /admin/workers/status rail. Kept until S3 moves that rail onto the
            # vitals roster. Best-effort; Redis errors are non-fatal.
            try:
                redis = await get_redis()
                if redis is not None:
                    iso_now = datetime.now(timezone.utc).isoformat()
                    await redis.set(f"worker:{task_name}:last_run_at", iso_now, ex=86400)
                    await redis.set(f"worker:{task_name}:last_status", "ok", ex=86400)
            except Exception as e:
                logger.debug(f"[Leader] {task_name} last-run write failed (non-fatal): {e}")

            # After task execution, renew lock and sleep
            if not await renew_leadership(task_name):
                logger.info(f"[Leader] '{task_name}' lost leadership after execution, backing off")
                await asyncio.sleep(_spread(LEADER_CHECK_INTERVAL))
                continue

            if not await _sleep_holding_lease(task_name, _spread(interval)):
                continue
        else:
            # Not leader — wait and check again. SPREAD, not full jitter: these workers
            # are polling, not backing off, so the mean cadence must be preserved while
            # the wakeups decorrelate. Workers that boot together otherwise poll together
            # forever, which is what turned one DNS blip into a self-sustaining storm.
            await asyncio.sleep(_spread(LEADER_CHECK_INTERVAL))


@asynccontextmanager
async def leadership_context(task_name: str):
    """
    Context manager for task leadership. Acquires on enter, releases on exit.

    Usage:
        async with leadership_context("staking_distributor") as am_leader:
            if am_leader:
                await run_task()
    """
    acquired = await try_acquire_leadership(task_name)
    try:
        yield acquired
    finally:
        if acquired:
            await release_leadership(task_name)


# Convenience: wrap an existing background task loop with leader election
def with_leader_election(task_name: str):
    """
    Decorator for background task loop functions.
    The decorated function only executes if this worker holds the lock.
    Must be applied to the inner loop body, not the outer while loop.

    Example:
        @with_leader_election("supply_auditor")
        async def _do_audit():
            ...  # This only runs on the leader worker
    """
    def decorator(func):
        async def wrapper(*args, **kwargs):
            if await try_acquire_leadership(task_name):
                try:
                    return await func(*args, **kwargs)
                finally:
                    await renew_leadership(task_name)
            else:
                logger.debug(f"[Leader] Skipping '{task_name}' — not leader")
                return None
        wrapper.__name__ = func.__name__
        wrapper.__qualname__ = func.__qualname__
        return wrapper
    return decorator
