"""
EventStore Reactor Framework
============================
Base class for event-driven cross-service reactions.

A reactor subscribes to one event type on the local EventStore via WebSocket,
runs leader-elected (one subscriber per registry process group), and dispatches
each received event to a concrete `handle_event` implementation.

CQRS line preserved: reactors react to events, but their *side effects* are still
HTTP commands against TEG / other registries. Do not emit further events from a
handler — that path leads to event-loop avalanches.

Usage:
    class MyReactor(EventStoreReactor):
        event_type = "MyEvent"
        leader_key = "reactor_my_event"
        name = "MyEvent"

        async def handle_event(self, event_data: dict) -> None:
            ...  # one event in, side effects out

    reactor = MyReactor()
    asyncio.create_task(reactor.start())

Instrumentation:
    Every reactor exposes a snapshot of its lifetime counters via
    `EventStoreReactor.snapshot_status()` (classmethod). Each instance tracks
    dispatch_count, error_count, last_event_at, last_event_id, last_dispatch_ms,
    last_error, leader_status, ws_connected. The `/admin/reactor/status`
    endpoint serializes this for the AdminReactors UI.
"""
from __future__ import annotations

import abc
import asyncio
import collections
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar, Dict, List, Optional, Set
from urllib.parse import quote

import aiohttp
import httpx

from .leader import try_acquire_leadership, renew_leadership, get_redis
from ..es_ssl_helper import get_es_ssl_context  # prod-aligned dual-mode SSL
from agentvault_registry.core.access_log_mask import mask_query_secrets
from agentvault_registry.core import ledger_names   # W4: an event's old and new names are one event

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------
# Prometheus instrumentation (added 2026-04-30 — for Grafana reactor dash)
#
# Per-worker counters; cross-worker aggregation is done by Prometheus
# `sum by (reactor, registry)` queries. Labels:
#   reactor  — the reactor's leader_key (stable identifier)
#   registry — REGISTRY_NAME env var (registry-a / frame-b-registry / sandbox)
#
# These are independent of the Redis-HASH counters used by /admin/reactor/status:
# Redis is for cross-worker UI views (single number per reactor); Prometheus
# is for time-series + dashboards (rates, latency histograms, leadership flips).
# ----------------------------------------------------------------------
try:
    from prometheus_client import Counter, Gauge, Histogram

    REACTOR_DISPATCHES_TOTAL = Counter(
        "reactor_dispatches_total",
        "Reactor handler dispatches by outcome",
        labelnames=["reactor", "registry", "outcome"],  # outcome: success|error|dedup
    )
    REACTOR_DISPATCH_DURATION = Histogram(
        "reactor_dispatch_duration_seconds",
        "Reactor handler dispatch latency",
        labelnames=["reactor", "registry"],
        buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    )
    REACTOR_IS_LEADER = Gauge(
        "reactor_is_leader",
        "1 if this worker holds the reactor leader lock; 0 otherwise",
        labelnames=["reactor", "registry"],
    )
    REACTOR_WS_CONNECTED = Gauge(
        "reactor_ws_connected",
        "1 if the leader's WebSocket to EventStore is connected; 0 otherwise",
        labelnames=["reactor", "registry"],
    )
    _PROM_AVAILABLE = True
except ImportError:  # pragma: no cover — prometheus_client is in requirements
    _PROM_AVAILABLE = False
    REACTOR_DISPATCHES_TOTAL = None  # type: ignore[assignment]
    REACTOR_DISPATCH_DURATION = None  # type: ignore[assignment]
    REACTOR_IS_LEADER = None  # type: ignore[assignment]
    REACTOR_WS_CONNECTED = None  # type: ignore[assignment]


def _registry_label() -> str:
    return os.getenv("REGISTRY_NAME", "registry")


# Track leader keys across all instantiated reactors so duplicates fail loudly
# at startup rather than silently letting one reactor steal another's lock.
_registered_leader_keys: Set[str] = set()

# Registry of all live reactor instances — used by /admin/reactor/status and tests.
_live_instances: List["EventStoreReactor"] = []

# Per-reactor in-memory dedup ring cap. EventStore replays the last 15 events on
# every reconnect; 256 entries gives ~17× safety margin and bounds memory at
# ≤ ~80KB per reactor instance.
_DEDUP_RING_CAP = 256

# R-1 (2026-07-24): handler-failure retry cap. On handler failure the event_id
# is EVICTED from the dedup ring (up to this many times) so an EventStore
# reconnect replay or the polling backstop can re-fire the handler. Past the
# cap the id stays in the ring as poison and is dropped for good.
_HANDLER_RETRY_CAP = int(os.getenv("REACTOR_HANDLER_RETRY_CAP", "3"))


class EventStoreReactor(abc.ABC):
    """Abstract base class for EventStore WebSocket-driven reactors."""

    # Subclass MUST set these:
    event_type: ClassVar[str] = ""        # e.g., "PeerRegistryDeactivated"
    leader_key: ClassVar[str] = ""        # e.g., "reactor_peer_deactivated"
    name: ClassVar[str] = ""              # short label used in log lines

    # Tunables (override per-reactor if needed):
    initial_delay_seconds: ClassVar[float] = 15.0  # let EventStore boot first
    reconnect_backoff_seconds: ClassVar[float] = 5.0
    renew_interval_seconds: ClassVar[float] = 10.0  # lock TTL is 30s in leader.py
    # 2026-05-03 Round 7c: env-tunable WS heartbeat. Default lowered from 30s
    # to 10s so silent half-closed connections (TCP wedge) get detected and
    # reconnected within ~10-20s instead of 30-60s. Saturation sims at sim-end
    # historically saw a "WS hung but leader still held" plateau (project
    # memory open follow-up #7) — shorter heartbeat materially mitigates.
    ws_heartbeat_seconds: ClassVar[float] = float(
        os.getenv("REACTOR_WS_HEARTBEAT_SEC", "10")
    )

    # 2026-05-03: dispatch handlers concurrently with bounded semaphore so
    # slow handlers (e.g. TEG HTTP roundtrip) don't stall the WS receive
    # loop. Without this, a handler taking 30ms caps reactor throughput at
    # ~33 events/s — causing ES per-client queue overflow under burst.
    handler_concurrency: ClassVar[int] = int(os.getenv("REACTOR_HANDLER_CONCURRENCY", "50"))

    # §reactor-cqrs (2026-06-24): dispatch_mode — how _dispatch_event runs the handler at the
    # single seam. 'concurrent' (default) = create_task fire-and-forget bounded by handler_concurrency
    # (today's behavior, byte-for-byte). 'serial' = await the handler inline → strict per-event
    # ordering + WS back-pressure (for ordering-sensitive reactors). Resolved once in __init__:
    # per-reactor env REACTOR_<KEY>_MODE (KEY = leader_key sans a 'reactor_' prefix, upper) >
    # global REACTOR_DISPATCH_MODE > this ClassVar; an unknown value falls back to 'concurrent'.
    # ('batched' + handle_batch is a Phase-2 follow-up.)
    dispatch_mode: ClassVar[str] = "concurrent"

    # 2026-05-02: polling backstop. Independent durable safety-net that scans
    # the local + foreign event tables for events of `self.event_type` since
    # the last poll, dispatches any not seen via WS (dedup ring catches
    # duplicates). Only the leader polls; same handler path; same handler_sem.
    # Failure modes covered: WS hiccup, peer slow-consumer disconnect,
    # aiohttp internal hang. WS stays the fast path; polling = guaranteed
    # eventual delivery within polling_backstop_interval_seconds.
    polling_backstop_enabled: ClassVar[bool] = os.getenv(
        "REACTOR_POLLING_BACKSTOP_ENABLED", "true"
    ).lower() in ("true", "1", "yes")
    polling_backstop_interval_seconds: ClassVar[int] = int(
        os.getenv("REACTOR_POLLING_BACKSTOP_INTERVAL_SEC", "30")
    )
    polling_backstop_initial_lookback_seconds: ClassVar[int] = int(
        os.getenv("REACTOR_POLLING_BACKSTOP_LOOKBACK_SEC", "300")
    )
    polling_backstop_limit: ClassVar[int] = int(
        os.getenv("REACTOR_POLLING_BACKSTOP_LIMIT", "1000")
    )
    # §BACKSTOPJITTER (2026-08-30) — ceiling for the failure backoff below.
    polling_backstop_backoff_cap_seconds: ClassVar[int] = int(
        os.getenv("REACTOR_POLLING_BACKSTOP_BACKOFF_CAP_SEC", "300")
    )

    @property
    def _event_names(self) -> tuple:
        """W4 phase 1 (agentvault2-aa, 2026-10-25): every name this reactor's event may be written under, the old name
        and its new one (core/ledger_names.live_names), so a reactor written for TokensTransferred also hears
        UnitsTransferred once an emitter writes it; an unrenamed event is a one-tuple of itself, as before."""
        return ledger_names.live_names(self.event_type)

    def __init__(self) -> None:
        if not self.event_type or not self.leader_key:
            raise RuntimeError(
                f"{type(self).__name__} must define class attrs event_type and leader_key"
            )
        if self.leader_key in _registered_leader_keys:
            raise RuntimeError(
                f"Reactor leader_key collision: '{self.leader_key}' already registered. "
                f"Each reactor must use a unique leader_key."
            )
        _registered_leader_keys.add(self.leader_key)
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._last_polled_ts: Optional[datetime] = None
        self._label: str = self.name or self.event_type or type(self).__name__

        # §reactor-cqrs (2026-06-24): resolve the effective dispatch mode ONCE.
        # per-reactor env > global env > ClassVar default; unknown → concurrent.
        _mode_key = self.leader_key.upper()
        if _mode_key.startswith("REACTOR_"):
            _mode_key = _mode_key[len("REACTOR_"):]
        _mode = (
            os.getenv(f"REACTOR_{_mode_key}_MODE")
            or os.getenv("REACTOR_DISPATCH_MODE")
            or self.dispatch_mode
            or "concurrent"
        ).strip().lower()
        self._dispatch_mode: str = _mode if _mode in ("concurrent", "serial") else "concurrent"

        # Instrumentation — counters + last-event probes
        self._dispatch_count: int = 0
        self._error_count: int = 0
        self._dedup_count: int = 0
        self._last_event_at: Optional[float] = None      # monotonic time for delta math
        self._last_event_iso: Optional[str] = None       # display-friendly for UI
        self._last_event_id: Optional[str] = None
        self._last_dispatch_ms: Optional[float] = None
        self._last_error: Optional[str] = None
        self._is_leader: bool = False
        self._ws_connected: bool = False
        self._started_at: Optional[str] = None

        # In-memory ring of recently-seen event_ids for backlog-replay dedup.
        # EventStore replays last 15 events on reconnect. Without dedup, every
        # reconnect re-sends emails / re-fires webhooks for those 15 events.
        # FIFO eviction at 256 entries; per-instance is sufficient because
        # leader election guarantees one consumer per reactor at a time.
        self._seen_event_ids: collections.OrderedDict[str, float] = collections.OrderedDict()

        # R-1: per-event handler-failure counts backing the capped retry net.
        self._event_fail_counts: Dict[str, int] = {}

        # Bounded handler concurrency. New handler tasks `await` on this
        # semaphore so the WS loop never blocks on a slow handler — events
        # can be dispatched concurrently up to handler_concurrency.
        self._handler_sem: asyncio.Semaphore = asyncio.Semaphore(self.handler_concurrency)

        _live_instances.append(self)

    # ------------------------------------------------------------------ public API

    async def start(self) -> None:
        """Start the reactor. Idempotent — second call is a no-op.

        Launches the WS loop AND the polling backstop loop in parallel.
        The polling backstop is a durable safety net: even if the WS path
        misses an event (network blip, consumer disconnect, aiohttp hang),
        the polling task will fetch it within polling_backstop_interval_seconds.
        """
        if self._running:
            return
        self._running = True
        self._started_at = datetime.now(timezone.utc).isoformat()
        # Restore dedup state BEFORE the WS loop can process EventStore's replay
        # backlog, so a restart does not re-fire handler side effects for events
        # already processed by the prior process (FINDING_2026-05-29).
        await self._warm_dedup_from_redis()
        self._task = asyncio.create_task(self._ws_loop(), name=f"reactor:{self._label}")
        if self.polling_backstop_enabled:
            self._poll_task = asyncio.create_task(
                self._polling_backstop_loop(),
                name=f"reactor-poll:{self._label}",
            )
        logger.info(
            f"[Reactor:{self._label}] Task started (channel=events:{self.event_type}, "
            f"polling_backstop={'on' if self.polling_backstop_enabled else 'off'})"
        )

    async def stop(self) -> None:
        """Stop the reactor. Cancels both the WS loop and the polling backstop."""
        self._running = False
        self._is_leader = False
        self._ws_connected = False
        for task_attr in ("_task", "_poll_task"):
            t = getattr(self, task_attr, None)
            if t is not None:
                t.cancel()
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
                setattr(self, task_attr, None)
        logger.info(f"[Reactor:{self._label}] Task stopped")

    # ------------------------------------------------------------------ subclass contract

    @abc.abstractmethod
    async def handle_event(self, event_data: dict) -> None:
        """React to one event payload. Must be idempotent — EventStore replays
        the last 15 events on every reconnect (backlog replay), so handlers will
        see duplicates after restart. Errors raised here are caught by the
        dispatcher and logged; the WS loop continues on the next event."""
        raise NotImplementedError

    # ------------------------------------------------------------------ instrumentation API

    def status(self) -> Dict[str, Any]:
        """Return a snapshot of this reactor's lifetime counters."""
        return {
            "name": self._label,
            "event_type": self.event_type,
            "leader_key": self.leader_key,
            "running": self._running,
            "is_leader": self._is_leader,
            "leader_worker": None,
            "ws_connected": self._ws_connected,
            "started_at": self._started_at,
            "dispatch_count": self._dispatch_count,
            "error_count": self._error_count,
            "dedup_count": self._dedup_count,
            "last_event_at": self._last_event_iso,
            "last_event_id": self._last_event_id,
            "last_dispatch_ms": (
                round(self._last_dispatch_ms, 2)
                if self._last_dispatch_ms is not None
                else None
            ),
            "last_error": self._last_error,
            "dispatch_mode": self._dispatch_mode,                      # §reactor-cqrs
            "cursor": self._last_polled_ts.isoformat() if self._last_polled_ts else None,
        }

    @classmethod
    def snapshot_status(cls) -> List[Dict[str, Any]]:
        """Return per-worker status snapshots (no Redis merge).

        Kept sync for backwards compat (tests, sync callers). The
        `/admin/reactor/status` endpoint uses `snapshot_status_async()` which
        unifies counters across uvicorn workers via Redis. See Phase C3."""
        return [r.status() for r in _live_instances]

    @classmethod
    async def snapshot_status_async(cls) -> List[Dict[str, Any]]:
        """Return cross-worker-unified status for every live reactor.

        Counter + last-event fields come from Redis HASH (HGETALL); per-worker
        fields (running, is_leader, ws_connected, started_at) come from this
        worker's local instance. Falls back to local view when Redis is None /
        unreachable."""
        if not _live_instances:
            return []
        return list(await asyncio.gather(*(r.status_async() for r in _live_instances)))

    @classmethod
    def reset_registry(cls) -> None:
        """Reset the live-instance + leader-key registries.

        ONLY for tests — callers must stop all reactors first."""
        _live_instances.clear()
        _registered_leader_keys.clear()

    # ------------------------------------------------------------------ Phase C3 — Redis-backed counter unification

    @property
    def _redis_status_key(self) -> str:
        """Redis HASH key for cross-worker counter aggregation."""
        registry_name = os.getenv("REGISTRY_NAME", "registry")
        return f"reactor_status:{registry_name}:{self.leader_key}"

    @property
    def _redis_seen_key(self) -> str:
        """Redis ZSET (member=event_id, score=wall-clock) — DURABLE backing for the
        in-memory dedup ring.

        Root fix for the restart-replay class (FINDING_2026-05-29): the in-memory
        ring is empty after a process restart, so EventStore's last-15 WS replay (and
        the polling-backstop initial lookback) get re-dispatched, re-firing handler
        side effects (e.g. notification emails) for months-old events. Persisting the
        seen-id ring to Redis lets a restart WARM the ring and skip that replay window
        — for every reactor, not just the notification ones. Fail-open throughout."""
        registry_name = os.getenv("REGISTRY_NAME", "registry")
        return f"reactor_seen:{registry_name}:{self.leader_key}"

    async def _warm_dedup_from_redis(self) -> None:
        """Load the most-recent seen event_ids from Redis into the in-memory ring at
        startup, so a restart resumes dedup state and does not re-dispatch the
        backlog-replay window. Fail-open: any Redis issue leaves the ring empty
        (identical to pre-fix behavior)."""
        try:
            r = await get_redis()
            if r is None:
                return
            # Newest CAP ids, most-recent first (decode_responses=True → str members).
            ids = await r.zrevrange(self._redis_seen_key, 0, _DEDUP_RING_CAP - 1)
            if not ids:
                return
            now = time.monotonic()
            # Insert oldest-first so the OrderedDict FIFO order matches recency.
            for eid in reversed(ids):
                self._seen_event_ids[str(eid)] = now
            while len(self._seen_event_ids) > _DEDUP_RING_CAP:
                self._seen_event_ids.popitem(last=False)
            logger.info(
                f"[Reactor:{self._label}] Warmed dedup ring from Redis "
                f"({len(self._seen_event_ids)} ids) — restart replays will be skipped"
            )
        except Exception as e:
            logger.debug(
                f"[Reactor:{self._label}] dedup warm-from-Redis failed (fail-open): {e}"
            )

    # §reactor-cqrs (2026-06-24): durable polling-backstop cursor. Persisting the
    # watermark lets a restart RESUME from where polling left off instead of only
    # looking back `polling_backstop_initial_lookback_seconds` — closing P19-001
    # (events missed during an outage longer than the lookback). Mirrors the dedup
    # ring's Redis backing; fail-open everywhere (no/failed cursor → today's lookback).
    @property
    def _redis_cursor_key(self) -> str:
        registry_name = os.getenv("REGISTRY_NAME", "registry")
        return f"reactor_cursor:{registry_name}:{self.leader_key}"

    async def _load_cursor_from_redis(self) -> Optional[datetime]:
        try:
            r = await get_redis()
            if r is None:
                return None
            val = await r.get(self._redis_cursor_key)
            if not val:
                return None
            ts = datetime.fromisoformat(str(val).replace("Z", "+00:00"))
            return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] cursor load failed (fail-open): {e}")
            return None

    async def _save_cursor_to_redis(self, ts: datetime) -> None:
        # 7-day TTL: a long-dead reactor's stale cursor self-expires (→ lookback)
        # rather than replaying ancient history on a much-later restart.
        try:
            r = await get_redis()
            if r is None:
                return
            await r.set(self._redis_cursor_key, ts.isoformat(), ex=7 * 24 * 3600)
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] cursor save failed (fail-open): {e}")

    async def _record_dedup(self) -> None:
        """Increment dedup_count locally and (best-effort) in Redis."""
        self._dedup_count += 1
        if _PROM_AVAILABLE:
            REACTOR_DISPATCHES_TOTAL.labels(
                reactor=self.leader_key, registry=_registry_label(), outcome="dedup"
            ).inc()
        r = await get_redis()
        if r is None:
            return
        try:
            await r.hincrby(self._redis_status_key, "dedup_count", 1)
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] dedup_count Redis write failed: {e}")

    async def _record_event_received(self, event_id: Optional[str]) -> None:
        """Update last-event probes locally and (best-effort) in Redis."""
        event_iso = datetime.now(timezone.utc).isoformat()
        self._last_event_id = event_id
        self._last_event_iso = event_iso
        self._last_event_at = time.monotonic()
        r = await get_redis()
        if r is None:
            return
        try:
            mapping: Dict[str, str] = {"last_event_iso": event_iso}
            if event_id:
                mapping["last_event_id"] = event_id
            await r.hset(self._redis_status_key, mapping=mapping)
            # Durable dedup backing: persist this seen id so a restart can warm the
            # ring and skip EventStore's replay window (FINDING_2026-05-29). Capped
            # to the ring size + 24h TTL so it self-bounds. Best-effort (fail-open).
            if event_id:
                seen_key = self._redis_seen_key
                await r.zadd(seen_key, {event_id: time.time()})
                await r.zremrangebyrank(seen_key, 0, -(_DEDUP_RING_CAP + 1))
                await r.expire(seen_key, 86400)
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] last_event Redis write failed: {e}")

    async def _record_dispatch_success(self, elapsed_ms: float) -> None:
        """Increment dispatch_count + record last_dispatch_ms locally and in Redis."""
        self._dispatch_count += 1
        self._last_dispatch_ms = elapsed_ms
        # §FRAMELIC (2026-09-07, findings row 166) — a reactor is a worker to whoever is on
        # call, and `/admin/workers/status` listed all ~50 of them with `last_run_at: null`
        # forever because only `BackgroundWorker` and the legacy leadership path ever stamped
        # vitals. For a SUBSCRIBER the cycle is a dispatch, so that is what gets stamped.
        # ⚠ An idle reactor still reads null here, and that is CORRECT — it has done no work.
        # What says it is alive is `last_turn_at`, stamped inside `try_acquire_leadership`,
        # which the same rail now shows beside this. Stamping a heartbeat as if it were work
        # would make a dead handler indistinguishable from a busy one.
        try:
            from . import vitals as _v
            await _v.stamp(self.leader_key, _v.OUTCOME_OK, duration_ms=int(elapsed_ms))
        except Exception:  # never let instrumentation break a handler
            pass
        if _PROM_AVAILABLE:
            REACTOR_DISPATCHES_TOTAL.labels(
                reactor=self.leader_key, registry=_registry_label(), outcome="success"
            ).inc()
            REACTOR_DISPATCH_DURATION.labels(
                reactor=self.leader_key, registry=_registry_label()
            ).observe(elapsed_ms / 1000.0)
        r = await get_redis()
        if r is None:
            return
        try:
            async with r.pipeline(transaction=False) as pipe:
                pipe.hincrby(self._redis_status_key, "dispatch_count", 1)
                pipe.hset(self._redis_status_key, "last_dispatch_ms", f"{elapsed_ms:.4f}")
                await pipe.execute()
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] dispatch_success Redis write failed: {e}")

    async def _record_error(self, reason: str, count: bool = True) -> None:
        """Set last_error locally + Redis; optionally increment error_count."""
        if count:
            self._error_count += 1
            if _PROM_AVAILABLE:
                REACTOR_DISPATCHES_TOTAL.labels(
                    reactor=self.leader_key, registry=_registry_label(), outcome="error"
                ).inc()
        self._last_error = reason
        r = await get_redis()
        if r is None:
            return
        try:
            async with r.pipeline(transaction=False) as pipe:
                if count:
                    pipe.hincrby(self._redis_status_key, "error_count", 1)
                pipe.hset(self._redis_status_key, "last_error", reason)
                await pipe.execute()
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] error Redis write failed: {e}")

    async def _record_ws_connected(self) -> None:
        """Mark this reactor as WS-connected locally + cross-worker via Redis HASH.

        Phase C4 (2026-04-28): only the leader writes ws_connected to the HASH.
        Followers don't reach this — they continue past the lease check before
        ever attempting a connect. The cross-worker status_async() reads this
        field and surfaces it as the cluster's WS state for the reactor."""
        self._ws_connected = True
        if _PROM_AVAILABLE:
            REACTOR_WS_CONNECTED.labels(
                reactor=self.leader_key, registry=_registry_label()
            ).set(1)
        r = await get_redis()
        if r is None:
            return
        try:
            await r.hset(self._redis_status_key, "ws_connected", "1")
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] ws_connected=1 write failed: {e}")

    async def _record_ws_disconnected(self) -> None:
        """Mark this reactor as WS-disconnected locally + cross-worker via Redis HASH."""
        self._ws_connected = False
        if _PROM_AVAILABLE:
            REACTOR_WS_CONNECTED.labels(
                reactor=self.leader_key, registry=_registry_label()
            ).set(0)
        r = await get_redis()
        if r is None:
            return
        try:
            await r.hset(self._redis_status_key, "ws_connected", "0")
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] ws_connected=0 write failed: {e}")

    async def status_async(self) -> Dict[str, Any]:
        """Return a snapshot with cross-worker counters + leadership + WS state
        merged from Redis.

        Phase C3 (2026-04-27): counters merged from Redis HASH.
        Phase C4 (2026-04-28): is_leader + leader_worker derived from the
            `leader:<key>` lease key (cluster truth, not snapshot-worker view);
            ws_connected merged from the HASH (written by the leader's WS loop).
        Falls back to the local in-memory view when Redis is unconfigured /
        unreachable or the HASH key has no data yet (cold reactor)."""
        local = self.status()
        r = await get_redis()
        if r is None:
            return local

        # Pipeline the lease GET and the HASH HGETALL so each status_async call
        # is a single round-trip per reactor.
        lease_owner: Optional[str] = None
        raw: Dict[str, str] = {}
        try:
            async with r.pipeline(transaction=False) as pipe:
                pipe.get(f"leader:{self.leader_key}")
                pipe.hgetall(self._redis_status_key)
                lease_owner, raw = await pipe.execute()
        except Exception as e:
            logger.debug(f"[Reactor:{self._label}] status pipeline failed: {e}")
            return local

        # Phase C4 — cross-worker is_leader: lease key existence is the truth.
        # If the lease exists, *some* worker holds it; the cluster has a leader
        # for this reactor regardless of which worker handled this request.
        if lease_owner:
            local["is_leader"] = True
            local["leader_worker"] = lease_owner
        else:
            local["is_leader"] = False
            local["leader_worker"] = None
            # No leader → no live WS connection by definition.
            local["ws_connected"] = False

        if not raw:
            return local

        def _to_int(s: Optional[str], default: int) -> int:
            try:
                return int(s) if s is not None else default
            except (ValueError, TypeError):
                return default

        def _to_float(s: Optional[str]) -> Optional[float]:
            try:
                return float(s) if s is not None else None
            except (ValueError, TypeError):
                return None

        local["dispatch_count"] = _to_int(raw.get("dispatch_count"), local["dispatch_count"])
        local["error_count"] = _to_int(raw.get("error_count"), local["error_count"])
        local["dedup_count"] = _to_int(raw.get("dedup_count"), local["dedup_count"])
        if raw.get("last_event_id") is not None:
            local["last_event_id"] = raw.get("last_event_id")
        if raw.get("last_event_iso") is not None:
            local["last_event_at"] = raw.get("last_event_iso")
        last_dms = _to_float(raw.get("last_dispatch_ms"))
        if last_dms is not None:
            local["last_dispatch_ms"] = round(last_dms, 2)
        if raw.get("last_error") is not None:
            local["last_error"] = raw.get("last_error")

        # Phase C4 — ws_connected: only meaningful when a leader exists. The
        # leader's _ws_loop writes "1" on connect and "0" in finally; abrupt
        # leader death leaves a stale "1" but the next leader corrects it (or
        # the lease itself disappears, forcing False above).
        if lease_owner:
            ws_str = raw.get("ws_connected")
            if ws_str is not None:
                local["ws_connected"] = ws_str == "1"
        return local

    # ------------------------------------------------------------------ internals

    @staticmethod
    def _ws_url() -> str:
        """Build the WS URL, including the auth token query param.

        Phase 12.1 (2026-04-28): when `EVENTSTORE_WS_AUTH_MODE=jwt-svid`,
        mint a JWT-SVID via the local SPIRE workload API and pass it as the
        token. ES validates against the registry's /api/v1/spire/jwks endpoint.
        Falls back to the legacy shared-secret path on mint failure (mock SVID,
        missing pyspiffe, workload API unreachable).

        Default mode is `shared-secret` (Phase 10 #5 stepping stone) so existing
        clients keep working without env churn. Audience is configurable via
        `EVENTSTORE_JWT_AUDIENCE`, defaulting to a SPIFFE-style ID.
        """
        es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
        base = (
            es_url.rstrip("/")
            .replace("http://", "ws://")
            .replace("https://", "wss://")
            + "/ws/events"
        )

        token = ""
        mode = os.getenv("EVENTSTORE_WS_AUTH_MODE", "shared-secret").lower()
        if mode == "jwt-svid":
            try:
                from agentvault_registry.identity.svid_client import svid_client
                audience = os.getenv(
                    "EVENTSTORE_JWT_AUDIENCE",
                    "spiffe://sandbox-a.test/eventstore",
                )
                jwt_token = svid_client.get_jwt_svid(audience=audience)
                if jwt_token:
                    token = jwt_token
                    logger.info(
                        f"[Reactor] minted JWT-SVID for audience={audience} "
                        f"(token len={len(token)})"
                    )
                else:
                    logger.warning(
                        "[Reactor] EVENTSTORE_WS_AUTH_MODE=jwt-svid but mint "
                        "returned None — falling back to shared-secret"
                    )
            except Exception as e:
                logger.warning(f"[Reactor] JWT-SVID mint failed: {e} — falling back")

        if not token:
            # shared-secret path (default + JWT mint failure fallback)
            token = (
                os.getenv("EVENT_STORE_INTERNAL_API_KEY")
                or os.getenv("EVENT_STORE_API_KEY")
                or os.getenv("INTERNAL_API_KEY")
                or ""
            )

        if token:
            from urllib.parse import quote
            return f"{base}?token={quote(token, safe='')}"
        return base

    async def _ws_loop(self) -> None:
        await asyncio.sleep(self.initial_delay_seconds)

        while self._running:
            # Phase C4 — track whether THIS iteration crossed the leader gate.
            # Only the leader writes ws_connected to the cross-worker HASH;
            # followers must not clobber the leader's value.
            became_leader = False
            try:
                if not await try_acquire_leadership(self.leader_key):
                    self._is_leader = False
                    self._ws_connected = False
                    if _PROM_AVAILABLE:
                        REACTOR_IS_LEADER.labels(
                            reactor=self.leader_key, registry=_registry_label()
                        ).set(0)
                    await asyncio.sleep(10)
                    continue
                self._is_leader = True
                became_leader = True
                if _PROM_AVAILABLE:
                    REACTOR_IS_LEADER.labels(
                        reactor=self.leader_key, registry=_registry_label()
                    ).set(1)

                # Phase A (2026-04-28): build the URL freshly on each connect
                # attempt so JWT-SVID tokens (5-min TTL) are minted right before
                # use. Shared-secret path is unaffected (same value each time).
                ws_url = self._ws_url()

                # §SOVKIT V0369 (agentvault2-85, 2026-09-14): ws_url carries `?token=<the store's internal key or a
                # JWT-SVID>`; this line logged it whole into the container log (60-120 lines a day per registry,
                # the live store key, readable in Dozzle). The query secrets are masked with the ONE masker the
                # access log uses (core/access_log_mask), never a second regex.
                logger.info(f"[Reactor:{self._label}] Connecting to {mask_query_secrets(ws_url)}")
                # SSL context: prod (public hostname) → system CAs;
                # sandbox (internal hostname) → SPIRE bundle from /certs.
                # Single source of truth: agentvault_registry/es_ssl_helper.py
                _ssl_ctx = get_es_ssl_context()
                _connector = aiohttp.TCPConnector(ssl=_ssl_ctx) if _ssl_ctx else None
                async with aiohttp.ClientSession(connector=_connector) as session:
                    async with session.ws_connect(
                        ws_url, heartbeat=self.ws_heartbeat_seconds
                    ) as ws:
                        await self._record_ws_connected()
                        # Successful reconnect clears any stale last_error so
                        # the UI doesn't show resolved transient connection
                        # errors as if they were current. Redis is the cross-
                        # worker source of truth — always HDEL, regardless of
                        # whether THIS worker's local _last_error was set.
                        # Otherwise a fresh worker (post-rebuild) won't clear
                        # an error that another worker recorded into Redis.
                        self._last_error = None
                        try:
                            r = await get_redis()
                            if r is not None:
                                await r.hdel(self._redis_status_key, "last_error")
                        except Exception as e:
                            logger.debug(
                                f"[Reactor:{self._label}] last_error HDEL failed: {e}"
                            )
                        # W4: one channel per name the event may be written under (TokensTransferred and
                        # UnitsTransferred); an unrenamed event subscribes to its one channel, as before
                        for _channel in (f"events:{n}" for n in self._event_names):
                            await ws.send_json({"action": "subscribe", "channel": _channel})
                        logger.info(f"[Reactor:{self._label}] Subscribed to "
                                    f"{', '.join(f'events:{n}' for n in self._event_names)}")

                        last_renew = asyncio.get_event_loop().time()

                        while self._running:
                            try:
                                msg = await asyncio.wait_for(
                                    ws.receive(), timeout=self.renew_interval_seconds
                                )
                            except asyncio.TimeoutError:
                                if not await renew_leadership(self.leader_key):
                                    logger.info(
                                        f"[Reactor:{self._label}] Leadership lost — disconnecting"
                                    )
                                    self._is_leader = False
                                    break
                                continue

                            if msg.type == aiohttp.WSMsgType.TEXT:
                                await self._on_event(msg.data)
                            elif msg.type in (aiohttp.WSMsgType.ERROR, aiohttp.WSMsgType.CLOSED):
                                logger.warning(
                                    f"[Reactor:{self._label}] WS {msg.type.name}"
                                )
                                break

                            now = asyncio.get_event_loop().time()
                            if now - last_renew > self.renew_interval_seconds:
                                if not await renew_leadership(self.leader_key):
                                    logger.info(
                                        f"[Reactor:{self._label}] Leadership lost — disconnecting"
                                    )
                                    self._is_leader = False
                                    break
                                last_renew = now

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"[Reactor:{self._label}] WS error: {e}")
                await self._record_error(f"ws: {e}", count=False)
            finally:
                if became_leader:
                    # Leader exit (clean, leadership-loss, or exception).
                    # Write ws_connected=0 to HASH so followers see the
                    # cluster as disconnected until the next leader connects.
                    await self._record_ws_disconnected()
                    if _PROM_AVAILABLE:
                        REACTOR_IS_LEADER.labels(
                            reactor=self.leader_key, registry=_registry_label()
                        ).set(0)
                else:
                    self._ws_connected = False

            if self._running:
                await asyncio.sleep(self.reconnect_backoff_seconds)

    async def _on_event(self, raw: str) -> None:
        try:
            msg = json.loads(raw)
            if msg.get("type") != "event":
                return
            event = msg.get("event", {}) or {}
            await self._dispatch_event(event)
        except json.JSONDecodeError:
            logger.debug(f"[Reactor:{self._label}] Non-JSON WS payload, ignoring")
        except Exception as e:
            # Swallow — one bad event must not kill the loop. Polling backstop
            # remains the safety net for missed reactions.
            await self._record_error(f"dispatch: {type(e).__name__}: {e}")

    async def _dispatch_event(self, event: dict) -> None:
        """Common event-dispatch path used by BOTH the WS loop and the polling
        backstop. Owns dedup-ring check + handler dispatch via the shared
        handler_sem. Idempotent — duplicates from the two paths are caught here.
        """
        if event.get("event_type") not in self._event_names:
            return
        data = event.get("data", {}) or {}

        # §pass63 follow-up (2026-05-22) — inject envelope-level timestamp as a
        # fallback under `_envelope_timestamp`. Notification reactors that use
        # `is_notification_stale` can detect boot-replays of old events even
        # when the payload's own `recorded_at` / `timestamp` / `detected_at`
        # fields are missing or stamped with placeholder values (some
        # hand-crafted historical events lack those entirely). Single
        # underscore prefix marks it as ES-injected meta, not handler payload.
        if "_envelope_timestamp" not in data:
            ts = event.get("timestamp")
            if ts:
                data = {**data, "_envelope_timestamp": str(ts)}

        # §TRUSTWIRE (2026-09-10) — SAY WHETHER THIS EVENT IS OURS OR A PEER'S COPY.
        # Every event a peer emits also lands here: the replicator stores it in `foreign_events`
        # and (for CROSS_FRAME_BROADCAST_TYPES) bridges it onto the local WS bus. Both delivery
        # paths already KNOW which frame it came from — the WS bridge stamps `source_frame` on
        # the envelope and the /events/foreign endpoint returns `frame_id` — and both dropped it
        # here, so a handler could not tell a settlement it took part in from one it merely
        # overheard between two peers. Injected under an underscore like `_envelope_timestamp`
        # (ES meta, not handler payload) and NOT as `source_frame`, which several payloads
        # already use for their own meaning (FxSwapSettled's is the swap's source trust domain).
        # Absent ⇒ locally emitted.
        _foreign = event.get("source_frame") or event.get("frame_id")
        if _foreign and "_foreign_frame_id" not in data:
            data = {**data, "_foreign_frame_id": str(_foreign)}

        event_id = event.get("event_id") or event.get("id")

        # Backlog-replay dedup: EventStore replays the last 15 events on
        # every reconnect. Without this guard, every reactor restart
        # re-fires emails / webhooks for those 15 events. We dedup by
        # event_id (server-assigned, unique). Idempotency_key would also
        # work but is caller-supplied and not always set.
        # 2026-05-02: dedup ring is also shared with the polling backstop —
        # so a WS-delivered event followed by a polling-delivered event with
        # the same id won't double-dispatch.
        if event_id and event_id in self._seen_event_ids:
            await self._record_dedup()
            # Move to end so FIFO eviction keeps it warm (touch-on-hit)
            self._seen_event_ids.move_to_end(event_id)
            logger.debug(
                f"[Reactor:{self._label}] Skipping duplicate event_id={event_id} "
                f"(dedup_count={self._dedup_count})"
            )
            return

        await self._record_event_received(event_id)

        # Add to dedup ring BEFORE dispatch so concurrent WS replays
        # (e.g. reconnect backlog) don't double-fire the handler.
        # R-1 (2026-07-24): on handler FAILURE the id is evicted again (capped
        # at _HANDLER_RETRY_CAP) so a reconnect replay / polling backstop can
        # retry; only after the cap does it stay seen (poison drop).
        if event_id:
            self._seen_event_ids[event_id] = time.monotonic()
            if len(self._seen_event_ids) > _DEDUP_RING_CAP:
                self._seen_event_ids.popitem(last=False)

        # Dispatch handler as a concurrent task (bounded by semaphore).
        # WS receive loop is NOT blocked while the handler runs. Multiple
        # events processed in parallel up to handler_concurrency. This
        # prevents the WS-overflow → force-disconnect cascade observed
        # under burst on async cross-frame transfers (2026-05-03).
        async def _dispatch():
            async with self._handler_sem:
                t0 = time.monotonic()
                try:
                    await self.handle_event(data)
                    elapsed_ms = (time.monotonic() - t0) * 1000.0
                    await self._record_dispatch_success(elapsed_ms)
                    if event_id:
                        self._event_fail_counts.pop(event_id, None)
                except Exception as e:
                    await self._record_error(f"handler: {type(e).__name__}: {e}")
                    # §FRAMELIC row 166 — separate clocks: this moves `last_run_at` but NOT
                    # `last_success_at`, which is the whole point of keeping both.
                    try:
                        from . import vitals as _v
                        await _v.stamp(self.leader_key, _v.OUTCOME_ERROR,
                                       error=f"{type(e).__name__}: {e}")
                    except Exception:
                        pass
                    # R-1: capped retry net — evict the id so a replay/backstop
                    # redelivery re-fires the handler, up to _HANDLER_RETRY_CAP.
                    if event_id:
                        fails = self._event_fail_counts.get(event_id, 0) + 1
                        if fails < _HANDLER_RETRY_CAP:
                            self._event_fail_counts[event_id] = fails
                            self._seen_event_ids.pop(event_id, None)
                            logger.warning(
                                f"[Reactor:{self._label}] Handler error "
                                f"(attempt {fails}/{_HANDLER_RETRY_CAP}, will retry on "
                                f"redelivery): {e}"
                            )
                        else:
                            self._event_fail_counts.pop(event_id, None)
                            logger.error(
                                f"[Reactor:{self._label}] Handler failed "
                                f"{_HANDLER_RETRY_CAP}x for event_id={event_id} — "
                                f"poison-dropped: {e}"
                            )
                        if len(self._event_fail_counts) > 1024:
                            self._event_fail_counts.clear()
                    else:
                        logger.warning(f"[Reactor:{self._label}] Handler error: {e}")

        # §reactor-cqrs dispatch_mode: 'serial' awaits inline (strict ordering + WS
        # back-pressure); 'concurrent' (default) fires a bounded task (today's behavior).
        if self._dispatch_mode == "serial":
            await _dispatch()
        else:
            asyncio.create_task(_dispatch())

    # ------------------------------------------------------------------ polling backstop

    async def _polling_backstop_loop(self) -> None:
        """Periodic polling backstop. Runs in parallel with the WS loop.

        Independent durable safety-net that scans local + foreign event tables
        for events of self.event_type since the last poll and dispatches any
        not seen via WS (dedup ring catches duplicates).

        Only the WS-leader runs the actual queries. Non-leaders sleep and
        recheck. The leader-acquire is owned by the WS loop; this task
        observes self._is_leader.

        Failure modes covered:
          - WS connection silently half-closed (TCP-level wedge)
          - ES-side per-client send queue overflow + force-disconnect
          - aiohttp WS internal hang
          - Pub/Sub broadcast race with subscribe
        WS stays the fast path (sub-second). Polling = guaranteed eventual
        delivery within polling_backstop_interval_seconds (default 30s).
        """
        # Mirror the WS loop's startup delay so we don't race ES boot.
        await asyncio.sleep(self.initial_delay_seconds)

        consec_failures = 0
        while self._running:
            cycle_ok = True
            try:
                # Leader-only — non-leaders sleep cheaply.
                if not self._is_leader:
                    await asyncio.sleep(self.polling_backstop_interval_seconds)
                    continue

                # None (a future override forgetting the contract) counts as
                # success — only an explicit False or a raise backs off.
                cycle_ok = (await self._do_polling_backstop_cycle()) is not False
            except asyncio.CancelledError:
                break
            except Exception as e:
                cycle_ok = False
                logger.warning(
                    f"[Reactor:{self._label}] Polling backstop cycle error: {e}"
                )
                await self._record_error(f"polling: {type(e).__name__}: {e}", count=False)

            if cycle_ok:
                consec_failures = 0
            else:
                consec_failures = min(consec_failures + 1, 8)
                if consec_failures == 1:
                    logger.info(
                        f"[Reactor:{self._label}] Polling backstop backing off — "
                        f"EventStore unreachable/degraded (§BACKSTOPJITTER)"
                    )

            try:
                await asyncio.sleep(self._backstop_delay(
                    float(self.polling_backstop_interval_seconds),
                    consec_failures,
                    float(self.polling_backstop_backoff_cap_seconds),
                ))
            except asyncio.CancelledError:
                break

    @staticmethod
    def _backstop_delay(base: float, consec_failures: int, cap: float) -> float:
        """§BACKSTOPJITTER (2026-08-30) — next sleep for the polling backstop.

        Healthy (0 failures): SPREAD — base * uniform(0.85, 1.15), so the
        fleet's reactors (~40 per registry x 16 registries) stop polling the
        EventStore in phase-locked waves.

        Failing: FULL-JITTER exponential backoff — uniform(base, min(cap,
        base * 2^n)). During the 2026-08-30 swap-thrash incident every
        reactor's WS dropped at once and the backstops kept hammering
        /events/{export,foreign} at full fixed cadence on the exact ES that
        was drowning (pool exhausted, 239 QueuePool timeouts in one night).
        Backing off sheds load from a degraded ES instead of piling on; the
        first successful cycle resets to the spread cadence. Pure function —
        unit-drivable without asyncio.
        """
        import random
        base = max(1.0, base)
        cap = max(base, cap)
        if consec_failures <= 0:
            return base * random.uniform(0.85, 1.15)
        ceiling = min(cap, base * (2 ** min(consec_failures, 8)))
        return random.uniform(base, ceiling)

    async def _do_polling_backstop_cycle(self) -> bool:
        """One poll cycle: fetch events of self.event_type since
        self._last_polled_ts from BOTH /events/export (local) and
        /events/foreign (replicated), dispatch any not seen via WS.

        Returns False only when the EventStore looked DOWN/degraded (neither
        endpoint answered 200) — the loop uses that to back off with jitter
        (§BACKSTOPJITTER). Config-off paths return True: they are not ES
        health signals and must not trigger backoff.

        Auth — mirrors the SF-4 replicator's `_fetch_remote_events` pattern
        (proven in production). Order:
          1. mTLS via SPIRE SVID (preferred). Operators connect to
             https://events.theprotocol.cloud — the nginx-event-store
             sidecar terminates mTLS and injects X-SSL-Client-* headers
             that ES's verify_event_auth reads.
          2. X-Federation-License / X-Internal-Key headers (fallback when
             no SVID is mounted, e.g. dev / sandbox / mainframe-internal).
        """
        cert_dir = os.getenv("SVID_CERT_DIR", os.getenv("CERT_DIR", "/certs"))
        cert_file = os.path.join(cert_dir, "svid.0.pem")
        key_file = os.path.join(cert_dir, "svid.0.key")
        bundle_file = os.path.join(cert_dir, "bundle.0.pem")

        client_kwargs: Dict[str, Any] = {"timeout": 10}
        headers: Dict[str, str] = {}

        es_url = os.getenv("EVENT_STORE_URL", "http://event-store:8200")
        es_uses_https = es_url.startswith("https://")

        # ALWAYS attach header auth as defense in depth. ES's verify_event_auth
        # prioritizes mTLS over headers — if mTLS works, the header is ignored;
        # if mTLS isn't actually negotiated (e.g., URL is plain HTTP and no
        # nginx-event-store sidecar terminates TLS), the header authenticates.
        # 2026-05-04: previously the cert path was mutually exclusive with the
        # header path, so registry-a (HTTP URL + certs present) sent neither
        # working credential and got 403'd by ES. Defense-in-depth fixes that
        # without changing EVENT_STORE_URL (which would break _ws_loop, see
        # `feedback_event_store_url_https_breaks_reactors.md`).
        federation_license = os.getenv("FEDERATION_LICENSE_KEY", "")
        api_key = (
            os.getenv("EVENT_STORE_INTERNAL_API_KEY")
            or os.getenv("INTERNAL_API_KEY")
            or os.getenv("EVENT_STORE_API_KEY")
            or ""
        )
        if api_key:
            headers["X-Internal-Key"] = api_key
        if federation_license:
            headers["X-Federation-License"] = federation_license

        # Add cert-based auth on top, but only when URL is HTTPS — the cert
        # cannot be presented over plain HTTP, so loading it would be wasted
        # work that also masks the auth failure (current bug).
        if es_uses_https and os.path.exists(cert_file) and os.path.exists(key_file):
            from ..core.tls_client import client_cert_verify  # §DEPS: httpx 0.28 drops `cert` beside a bundle PATH
            client_kwargs["cert"] = (cert_file, key_file)
            client_kwargs["verify"] = client_cert_verify(bundle_file if os.path.exists(bundle_file) else True,
                                                         client_kwargs["cert"])

        # Skip polling only if NO auth method is available
        if not headers and "cert" not in client_kwargs:
            return True  # config state, not an ES failure — no backoff

        # Initialize watermark on first cycle: look back N seconds to absorb
        # any events that may have been missed during a brief WS hiccup
        # (e.g., if reactor just took leadership). Subsequent cycles advance
        # via observed event timestamps.
        if self._last_polled_ts is None:
            # §reactor-cqrs: resume from the DURABLE cursor if present (closes the
            # restart-resets-to-lookback gap, P19-001); else fall back to the lookback.
            cur = await self._load_cursor_from_redis()
            if cur is not None:
                self._last_polled_ts = cur
                logger.info(
                    f"[Reactor:{self._label}] resumed polling from durable cursor "
                    f"{cur.isoformat()}"
                )
            else:
                self._last_polled_ts = datetime.now(timezone.utc) - timedelta(
                    seconds=self.polling_backstop_initial_lookback_seconds
                )

        since_iso = self._last_polled_ts.isoformat()
        params = {
            "since": since_iso,
            "limit": self.polling_backstop_limit,
            "event_type": self.event_type,
        }

        local_events: list = []
        foreign_events: list = []

        async with httpx.AsyncClient(**client_kwargs) as client:
            # Parallel fetch from both endpoints — no serial wait.
            # W4: each name the event may be written under, local and foreign (an older store answers one name
            # per request, so the names are asked one by one; an unrenamed event makes the two requests it made)
            coros = []
            for _name in self._event_names:
                _params = dict(params, event_type=_name)
                coros.append(client.get(f"{es_url}/api/v1/events/export", params=_params, headers=headers))
                coros.append(client.get(f"{es_url}/api/v1/events/foreign", params=_params, headers=headers))
            results = await asyncio.gather(*coros, return_exceptions=True)

        # Parse each response, swallow individual failures. §BACKSTOPJITTER:
        # track whether the ES answered AT ALL — if neither endpoint gave a
        # 200 this cycle, the loop backs off instead of re-polling at full
        # cadence against a degraded ES.
        es_answered = False
        for resp in results:
            if isinstance(resp, Exception):
                logger.debug(f"[Reactor:{self._label}] Polling fetch failed: {resp}")
                continue
            if resp.status_code != 200:
                logger.debug(
                    f"[Reactor:{self._label}] Polling endpoint returned "
                    f"{resp.status_code}"
                )
                continue
            es_answered = True
            try:
                events = resp.json()
                if isinstance(events, list):
                    if "/foreign" in str(resp.request.url):
                        foreign_events.extend(events)
                    else:
                        local_events.extend(events)
            except Exception as e:
                logger.debug(f"[Reactor:{self._label}] Polling parse error: {e}")

        all_events = local_events + foreign_events
        if not all_events:
            return es_answered  # empty poll on a live ES is success

        # Dispatch each event via shared _dispatch_event (which dedups).
        # Track the new watermark from the latest event timestamp seen.
        latest_ts = self._last_polled_ts
        new_dispatched = 0
        for ev in all_events:
            event_id = ev.get("id") or ev.get("event_id")
            # Pre-check dedup ring to count "new dispatches" accurately
            # (the dispatch call itself also dedups but we want a
            # log-friendly "polling backstop dispatched N events" count).
            already_seen = bool(event_id and event_id in self._seen_event_ids)
            try:
                # Synthesise the WS-style payload shape so _dispatch_event's
                # event_type-match check works identically for both paths.
                synthetic_event = {
                    "id": event_id,
                    "event_type": ev.get("event_type") or self.event_type,
                    "aggregate_id": ev.get("aggregate_id", ""),
                    "data": ev.get("data", {}) or {},
                    "timestamp": ev.get("timestamp"),
                    "version": ev.get("version", 1),
                    # §TRUSTWIRE: the /foreign endpoint returns the emitting frame as
                    # `frame_id`; carry it under the SAME envelope key the WS bridge uses so a
                    # handler sees one convention whichever path delivered the event. Rows from
                    # /events/export have no frame_id and stay unmarked (= local).
                    "source_frame": ev.get("frame_id"),
                }
                await self._dispatch_event(synthetic_event)
                if not already_seen:
                    new_dispatched += 1
            except Exception as e:
                logger.debug(f"[Reactor:{self._label}] Polling dispatch error: {e}")

            ts_str = ev.get("timestamp", "")
            try:
                ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts > latest_ts:
                    latest_ts = ts
            except (ValueError, AttributeError, TypeError):
                pass

        if latest_ts > self._last_polled_ts:
            self._last_polled_ts = latest_ts
            await self._save_cursor_to_redis(self._last_polled_ts)  # §reactor-cqrs persist cursor

        if new_dispatched > 0:
            logger.info(
                f"[Reactor:{self._label}] Polling backstop dispatched "
                f"{new_dispatched} missed events (watermark → "
                f"{self._last_polled_ts.isoformat()})"
            )
        return es_answered
