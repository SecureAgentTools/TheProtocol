"""§VITALS — the liveness contract every background worker owes the operator.

WHY THIS EXISTS (measured 2026-09-04, `scratchpad/vitals/CENSUS.md`)
--------------------------------------------------------------------
191 background launch statements, 111 modules. The 42 reactors carry a real
status rail. Of the ~69 remaining workers, **4 wrote any liveness stamp**, and
the one stamp that existed could only ever say ``ok``. Four different improvised
probes (the admin rail, a Redis lock scan, a log-prefix grep, a table count) each
returned at least one WRONG answer about the same fleet.

The defect that proved the point: ``velocity_snapshot`` failed its EventStore
read every cycle, logged the failure, then logged *"No transfer events in window;
skipping upsert"* — which reads like a healthy quiet cycle. ``velocity_metrics``
stayed empty, so the IRONKEY rolling-24h spend cap summed 0 forever and the
velocity-scaled fee had no input. Nothing alerted, because nothing was watching.

THE RULES THIS MODULE ENCODES
-----------------------------
1. **Attempt and success are different timestamps.** A worker that fails every
   cycle must not look alive. Alerts read ``worker_last_success_unixtime``.
2. **A worker that swallows its own failure can still report it** — call
   ``ctx.fail(reason)`` inside ``cycle()``. This is the velocity_snapshot case:
   no exception escapes, and the cycle is still not a success.
3. **State lives in Redis, not in the process.** registry-a runs 38 gunicorn
   workers; in-process state answers ``unknown`` from the other 37
   (the §SUPPORTBATCH1 class).
4. **The stamp outlives the worker.** A 30-day TTL means a dead worker reads
   STALE with its last known cycle, never NEVER-RAN (the §CARDPULLTICK class:
   an instrument that forgets cannot raise an alarm).
5. **Vitals must never break the worker it watches**, but its own failures are
   COUNTED, never swallowed silently (``worker_vitals_write_failures_total``).

USAGE
-----
Three choke points cover the fleet; individual workers need no plumbing:

    # class-based workers — already wired in _worker_base.BackgroundWorker
    # run_with_leadership — already wired in leader.py

    # hand-rolled loops:
    async with vitals.cycle("my_worker") as ctx:
        n = await do_work()
        ctx.note(processed=n)
        if not reachable:
            ctx.fail("event store unreachable")   # honest, no exception needed
"""
from __future__ import annotations

import json
import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, Optional

logger = logging.getLogger(__name__)

# --- Prometheus ------------------------------------------------------------
# PROMETHEUS_MULTIPROC_DIR is set on every registry, so a Gauge WITHOUT an
# explicit multiprocess_mode yields one series per pid — unusable for an alert.
# Timestamps take 'max' (the newest leader wins); the duration takes
# 'livemostrecent' (the pattern already used in routers/agent_mtls.py).
try:
    from prometheus_client import Counter as _VCounter, Gauge as _VGauge

    WORKER_CYCLES_TOTAL = _VCounter(
        "worker_cycles_total",
        "Background worker cycles by worker and outcome (ok|error|skipped)",
        labelnames=["worker", "outcome"],
    )
    WORKER_LAST_CYCLE_UNIXTIME = _VGauge(
        "worker_last_cycle_unixtime",
        "Unix time of the last cycle ATTEMPT (successful or not)",
        labelnames=["worker"],
        multiprocess_mode="max",
    )
    WORKER_LAST_SUCCESS_UNIXTIME = _VGauge(
        "worker_last_success_unixtime",
        "Unix time of the last SUCCESSFUL cycle — this is what alerts read",
        labelnames=["worker"],
        multiprocess_mode="max",
    )
    WORKER_LAST_TURN_UNIXTIME = _VGauge(
        "worker_last_turn_unixtime",
        "Unix time the LEADER's loop last turned (liveness, not health)",
        labelnames=["worker"],
        multiprocess_mode="max",
    )
    WORKER_LAST_CYCLE_DURATION_MS = _VGauge(
        "worker_last_cycle_duration_ms",
        "Wall-clock duration of the most recent cycle, ms",
        labelnames=["worker"],
        multiprocess_mode="livemostrecent",
    )
    VITALS_WRITE_FAILURES = _VCounter(
        "worker_vitals_write_failures_total",
        "Times the vitals stamp itself could not be written (never silent)",
        labelnames=["reason"],
    )
except Exception:  # pragma: no cover — prometheus_client absent
    WORKER_LAST_TURN_UNIXTIME = None  # type: ignore[assignment]
    WORKER_CYCLES_TOTAL = None  # type: ignore[assignment]
    WORKER_LAST_CYCLE_UNIXTIME = None  # type: ignore[assignment]
    WORKER_LAST_SUCCESS_UNIXTIME = None  # type: ignore[assignment]
    WORKER_LAST_CYCLE_DURATION_MS = None  # type: ignore[assignment]
    VITALS_WRITE_FAILURES = None  # type: ignore[assignment]

# --- Redis keys ------------------------------------------------------------
ROSTER_KEY = "workers:roster"          # HASH worker_id -> json(meta), declared at launch
STATE_PREFIX = "worker:"               # HASH worker:<id> -> the live stamp
STATE_TTL_SEC = 30 * 24 * 3600         # 30 days: a dead worker reads STALE, never absent

OUTCOME_OK = "ok"
OUTCOME_ERROR = "error"
OUTCOME_SKIPPED = "skipped"            # gate said no / not leader — NOT a failure


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _count_write_failure(reason: str) -> None:
    if VITALS_WRITE_FAILURES is not None:
        try:
            VITALS_WRITE_FAILURES.labels(reason=reason).inc()
        except Exception:
            pass


async def _redis():
    # Imported lazily: leader.py imports this module's siblings, and a module-level
    # import here would close the cycle.
    from .leader import get_redis
    return await get_redis()


# --- registration ----------------------------------------------------------
async def register(
    worker_id: str,
    *,
    module: Optional[str] = None,
    pattern: Optional[str] = None,
    interval_sec: Optional[float] = None,
    enabled: bool = True,
    gate: Optional[str] = None,
) -> None:
    """Declare a worker at launch, whether or not it will ever run.

    The roster is what makes the admin rail honest: a worker that is DISABLED or
    has NEVER RUN is a row, not an absence. The previous rail kept its list by
    hand and printed "(undocumented worker)" for 27 of the 50 it found.
    """
    meta = {
        "worker_id": worker_id,
        "module": module or "",
        "pattern": pattern or "",
        "interval_sec": interval_sec,
        "enabled": bool(enabled),
        "gate": gate or "",
        "registry_id": os.getenv("REGISTRY_NAME", "registry-a"),
        "registered_at": _now_iso(),
    }
    try:
        r = await _redis()
        if r is None:
            return
        await r.hset(ROSTER_KEY, worker_id, json.dumps(meta))
    except Exception as e:
        _count_write_failure("register")
        logger.debug(f"[vitals] register({worker_id}) failed (non-fatal): {e}")


# --- the stamp -------------------------------------------------------------
async def stamp(
    worker_id: str,
    outcome: str,
    *,
    duration_ms: Optional[int] = None,
    error: Optional[str] = None,
    stats: Optional[Dict[str, Any]] = None,
) -> None:
    """Record one cycle. Never raises."""
    now = time.time()
    if WORKER_CYCLES_TOTAL is not None:
        try:
            WORKER_CYCLES_TOTAL.labels(worker=worker_id, outcome=outcome).inc()
            if outcome != OUTCOME_SKIPPED:
                WORKER_LAST_CYCLE_UNIXTIME.labels(worker=worker_id).set(now)
            if outcome == OUTCOME_OK:
                WORKER_LAST_SUCCESS_UNIXTIME.labels(worker=worker_id).set(now)
            if duration_ms is not None:
                WORKER_LAST_CYCLE_DURATION_MS.labels(worker=worker_id).set(duration_ms)
        except Exception:
            _count_write_failure("prometheus")

    fields: Dict[str, str] = {
        "last_outcome": outcome,
        "last_cycle_at": _now_iso(),
    }
    if outcome == OUTCOME_OK:
        fields["last_success_at"] = fields["last_cycle_at"]
        fields["last_error"] = ""
    elif outcome == OUTCOME_ERROR:
        fields["last_error"] = (error or "unspecified")[:500]
    if duration_ms is not None:
        fields["last_duration_ms"] = str(int(duration_ms))
    if stats:
        try:
            fields["last_stats"] = json.dumps(stats, default=str)[:2000]
        except Exception:
            pass
    try:
        r = await _redis()
        if r is None:
            return
        key = f"{STATE_PREFIX}{worker_id}"
        pipe = r.pipeline()
        pipe.hset(key, mapping=fields)
        pipe.hincrby(key, "cycles", 1)
        if outcome == OUTCOME_ERROR:
            pipe.hincrby(key, "errors", 1)
        pipe.expire(key, STATE_TTL_SEC)
        await pipe.execute()
    except Exception as e:
        _count_write_failure("redis")
        logger.debug(f"[vitals] stamp({worker_id},{outcome}) failed (non-fatal): {e}")


def canonical_worker_id(name: str) -> str:
    """Collapse a LEADER KEY onto the worker it belongs to.

    Measured on the first live roster: five workers declare a `leader_key` that
    decorates their `worker_id` — `fx_reserve_keeper:leader`,
    `gateway_float_keeper:leader`, `leader:bundle_retention`, ... The cycle stamp
    is keyed on worker_id and the turn stamp on the leader key, so each of those
    appeared TWICE: one row ALIVE with no turn, one row turning with no cycles.
    ONE rule at the source (§SLUGCONVERGE), never a per-surface map.
    """
    if name.startswith("leader:"):
        name = name[len("leader:"):]
    if name.endswith(":leader"):
        name = name[: -len(":leader")]
    return name


# --- liveness (called from leader.try_acquire_leadership for the whole fleet) ---
_TURN_THROTTLE_SEC = 5.0
_last_turn_write: Dict[str, float] = {}


async def stamp_turn(worker_id: str) -> None:
    """Record that the leader's loop turned. Cheap, throttled, never raises.

    Throttled per process because a 5-second worker would otherwise write on
    every acquire; 5 s of resolution is far finer than any staleness alert.
    """
    worker_id = canonical_worker_id(worker_id)
    now = time.time()
    prev = _last_turn_write.get(worker_id, 0.0)
    if now - prev < _TURN_THROTTLE_SEC:
        return
    first_turn_here = worker_id not in _last_turn_write
    _last_turn_write[worker_id] = now
    if WORKER_LAST_TURN_UNIXTIME is not None:
        try:
            WORKER_LAST_TURN_UNIXTIME.labels(worker=worker_id).set(now)
        except Exception:
            _count_write_failure("prometheus_turn")
    try:
        r = await _redis()
        if r is None:
            return
        key = f"{STATE_PREFIX}{worker_id}"
        pipe = r.pipeline()
        pipe.hset(key, "last_turn_at", _now_iso())
        pipe.expire(key, STATE_TTL_SEC)
        await pipe.execute()
        if first_turn_here:
            # Self-registration: any leader-elected worker joins the roster on its
            # first turn, so a worker nobody remembered to declare is still a ROW.
            # HSETNX, so an explicit register() (which carries the real interval,
            # gate and module) always wins over this thin auto-entry.
            await r.hsetnx(ROSTER_KEY, worker_id, json.dumps({
                "worker_id": worker_id, "module": "", "pattern": "auto(leader)",
                "interval_sec": None, "enabled": True, "gate": "",
                "registry_id": os.getenv("REGISTRY_NAME", "registry-a"),
                "registered_at": _now_iso(),
            }))
    except Exception:
        _count_write_failure("redis_turn")


class CycleContext:
    """Handed to the body of :func:`cycle`. Lets a worker report a failure it
    handled itself, which is exactly the case no exception-based instrument
    can see (velocity_snapshot caught its own ConnectError and carried on)."""

    __slots__ = ("worker_id", "_failed", "_reason", "_stats")

    def __init__(self, worker_id: str) -> None:
        self.worker_id = worker_id
        self._failed = False
        self._reason: Optional[str] = None
        self._stats: Dict[str, Any] = {}

    def fail(self, reason: str) -> None:
        """Mark this cycle unsuccessful without raising."""
        self._failed = True
        self._reason = reason

    def note(self, **stats: Any) -> None:
        self._stats.update(stats)

    @property
    def failed(self) -> bool:
        return self._failed


@asynccontextmanager
async def cycle(worker_id: str) -> AsyncIterator[CycleContext]:
    """Wrap one unit of worker work. Stamps ok/error; re-raises on exception."""
    ctx = CycleContext(worker_id)
    t0 = time.time()
    try:
        yield ctx
    except Exception as e:
        await stamp(worker_id, OUTCOME_ERROR, duration_ms=int((time.time() - t0) * 1000),
                    error=f"{type(e).__name__}: {e}", stats=ctx._stats or None)
        raise
    else:
        await stamp(
            worker_id,
            OUTCOME_ERROR if ctx.failed else OUTCOME_OK,
            duration_ms=int((time.time() - t0) * 1000),
            error=ctx._reason,
            stats=ctx._stats or None,
        )


# --- reading ---------------------------------------------------------------
async def snapshot() -> Dict[str, Any]:
    """Roster joined with live stamps. The admin rail's single source."""
    out: Dict[str, Any] = {"workers": [], "roster_size": 0}
    try:
        r = await _redis()
        if r is None:
            out["error"] = "redis_unavailable"
            return out
        roster = await r.hgetall(ROSTER_KEY) or {}
        out["roster_size"] = len(roster)
        for wid, raw in roster.items():
            wid = wid.decode() if isinstance(wid, bytes) else wid
            try:
                meta = json.loads(raw.decode() if isinstance(raw, bytes) else raw)
            except Exception:
                meta = {"worker_id": wid}
            state = await r.hgetall(f"{STATE_PREFIX}{wid}") or {}
            state = {
                (k.decode() if isinstance(k, bytes) else k):
                (v.decode() if isinstance(v, bytes) else v)
                for k, v in state.items()
            }
            meta["state"] = state
            out["workers"].append(meta)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
    return out
