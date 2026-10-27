"""
Cross-TEG 2PC coordination sweeper (§pass26 — 2026-05-17).

Periodic, leader-elected per TEG. Sweeps `cross_teg_transfers` source-side rows
that never reached a terminal state because the coordinator (or its participants)
crashed mid-flight or lost messages.

Closes the stuck-2PC class documented in
`memory/project_lock_leak_teg_metadata_class.md`. The architecture's persistence
machinery already exists — `coordination_store.save_source_coordination` writes
a row at PREPARE time. This sweeper just queries those rows when they expire
and routes them through the existing compensation primitives.

State transitions handled:

  INITIATED + expires_at < NOW()  →  call protocol._compensate_transfer()
    (releases the agent's `locked_balance`, marks row COMPENSATED).
    Emit `CrossTEGCoordinationAbortedByExpiry`.

  COMMITTED + expires_at < NOW()  →  mark row FAILED for operator review.
    (Auto-retry of the remote commit would require the original
    authorization_token which we don't persist; safer to flag than to risk
    double-debit. Operator inspects the event and uses
    `/cross-teg/abort/{transfer_id}` if needed.)
    Emit `CrossTEGCoordinationCommitResumed`.

Per-row errors are isolated and emit `CrossTEGSweepErrored`; the cycle
continues.

Leader election: Redis SETNX with 90s TTL on `teg_2pc_sweeper:{teg_id}`.
Multiple TEG workers run the sweeper module but only one holds the lease.
Fail-closed if Redis unreachable (no sweep) — preferable to multi-worker
emission storms.

Prometheus metrics (created lazily, best-effort):
  cross_teg_sweep_cycle_total{teg_id}
  cross_teg_sweep_aborted_total{teg_id}
  cross_teg_sweep_commit_resumed_total{teg_id}
  cross_teg_sweep_errors_total{teg_id,reason}
  cross_teg_pending_coordinations{teg_id,status}

§V0050 — stale-bookkeeping write-down. The async lock leg leaves source-side
FUNDS_LOCKED rows that nothing ever advances (value settles/refunds via the
escrow ledger; row stays). Each cycle additionally calls
`coordinator.sweep_stale_bookkeeping()` — a STATUS-ONLY bulk write-down of
rows expired > CROSS_TEG_STALE_SWEEP_AGE_HOURS to the terminal SWEPT status
(never touches balances). Emits one `CrossTEGStaleSwept` summary event per
cycle when rows were swept.

Env knobs:
  CROSS_TEG_SWEEPER_ENABLED          default: true
  CROSS_TEG_SWEEPER_INTERVAL_SEC     default: 60
  CROSS_TEG_SWEEPER_BATCH_LIMIT      default: 100
  CROSS_TEG_STALE_SWEEP_ENABLED      default: true   (§V0050)
  CROSS_TEG_STALE_SWEEP_AGE_HOURS    default: 24     (§V0050)
  CROSS_TEG_STALE_SWEEP_BATCH        default: 2000   (§V0050)
"""
from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from .coordinator import DistributedTransactionCoordinator

logger = logging.getLogger(__name__)

SWEEPER_ENABLED = os.getenv("CROSS_TEG_SWEEPER_ENABLED", "true").lower() == "true"
SWEEP_INTERVAL_SEC = int(os.getenv("CROSS_TEG_SWEEPER_INTERVAL_SEC", "60"))
SWEEP_BATCH_LIMIT = int(os.getenv("CROSS_TEG_SWEEPER_BATCH_LIMIT", "100"))
# §V0050 — stale-bookkeeping write-down knobs.
STALE_SWEEP_ENABLED = os.getenv("CROSS_TEG_STALE_SWEEP_ENABLED", "true").lower() == "true"
STALE_SWEEP_AGE_HOURS = int(os.getenv("CROSS_TEG_STALE_SWEEP_AGE_HOURS", "24"))
STALE_SWEEP_BATCH = int(os.getenv("CROSS_TEG_STALE_SWEEP_BATCH", "2000"))

# 2026-07-29 — stale cross-TEG fund-send write-down (status-only; see
# coordinator.sweep_stale_outflows for the safety argument). Age floor is
# deliberately longer than the stale-bookkeeping sweep because the transient
# peer-5xx path leaves rows pending ON PURPOSE for a retry.
OUTFLOW_SWEEP_ENABLED = os.getenv("CROSS_TEG_OUTFLOW_SWEEP_ENABLED", "true").lower() == "true"
OUTFLOW_SWEEP_AGE_HOURS = int(os.getenv("CROSS_TEG_OUTFLOW_SWEEP_AGE_HOURS", "72"))
OUTFLOW_SWEEP_BATCH = int(os.getenv("CROSS_TEG_OUTFLOW_SWEEP_BATCH", "500"))
# 2026-07-29 §ESCROWSCAR-2 — orphaned `exref:ord-...` deposit legs. The move endpoint
# only writes down a stale PENDING row when the SAME key is retried; a rejected order
# is terminal, so its leg is never revisited. Status-only, balances untouched.
EXREF_SWEEP_ENABLED = os.getenv("EXCHANGE_EXREF_SWEEP_ENABLED", "true").lower() == "true"
EXREF_SWEEP_AGE_HOURS = int(os.getenv("EXCHANGE_EXREF_SWEEP_AGE_HOURS", "24"))
EXREF_SWEEP_BATCH = int(os.getenv("EXCHANGE_EXREF_SWEEP_BATCH", "500"))
LEADER_KEY_PREFIX = "teg_2pc_sweeper"
LEADER_LEASE_SEC = 90


# Prometheus metrics — lazy import to support test environments without prom.
try:
    from prometheus_client import Counter as _C, Gauge as _G

    SWEEP_CYCLE_TOTAL = _C(
        "cross_teg_sweep_cycle_total",
        "Total sweeper cycles run (leader only)",
        labelnames=["teg_id"],
    )
    SWEEP_ABORTED_TOTAL = _C(
        "cross_teg_sweep_aborted_total",
        "Expired INITIATED coordinations aborted by sweeper",
        labelnames=["teg_id"],
    )
    SWEEP_COMMIT_RESUMED_TOTAL = _C(
        "cross_teg_sweep_commit_resumed_total",
        "Expired COMMITTED coordinations flagged by sweeper for operator review",
        labelnames=["teg_id"],
    )
    SWEEP_ERRORS_TOTAL = _C(
        "cross_teg_sweep_errors_total",
        "Errors during sweeper execution",
        labelnames=["teg_id", "reason"],
    )
    # §pass27 Phase 0 (2026-05-17): `multiprocess_mode='max'` so the per-pid
    # values across the 8-worker TEG container get aggregated as a single
    # max series at /metrics scrape time. Default Gauge multiprocess mode is
    # 'all' (one series per pid) — sum-by aggregation in PromQL then inflates
    # the count by N=workers. Max-of-pids matches the canonical "current
    # state count" semantic for this gauge.
    PENDING_COORDINATIONS = _G(
        "cross_teg_pending_coordinations",
        "Source-side cross_teg_transfers past expires_at, grouped by status",
        labelnames=["teg_id", "status"],
        multiprocess_mode="max",
    )
    # §V0050 — stale-bookkeeping write-down observability.
    SWEEP_SWEPT_TOTAL = _C(
        "cross_teg_sweep_swept_total",
        "Stale FUNDS_LOCKED bookkeeping rows written down to SWEPT",
        labelnames=["teg_id"],
    )
    STALE_BOOKKEEPING_GAUGE = _G(
        "cross_teg_stale_bookkeeping",
        "Stale FUNDS_LOCKED rows still awaiting write-down",
        labelnames=["teg_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    SWEEP_CYCLE_TOTAL = None
    SWEEP_ABORTED_TOTAL = None
    SWEEP_COMMIT_RESUMED_TOTAL = None
    SWEEP_ERRORS_TOTAL = None
    PENDING_COORDINATIONS = None
    SWEEP_SWEPT_TOTAL = None
    STALE_BOOKKEEPING_GAUGE = None


class CrossTegSweeper:
    """Periodic, leader-elected sweeper for stuck 2PC coordinations."""

    def __init__(self, coordinator: DistributedTransactionCoordinator):
        self.coordinator = coordinator
        self.teg_id = coordinator.teg_id
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self.worker_id = f"{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:6]}"
        self._last_stats: Dict[str, int] = {"checked": 0, "aborted": 0, "resumed": 0, "errors": 0}
        self._last_cycle_iso: Optional[str] = None
        self._last_duration_ms: int = 0
        self._is_leader_now: bool = False
        self._emitter = None  # Lazy

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        if not SWEEPER_ENABLED:
            logger.info("[CrossTegSweeper] disabled via CROSS_TEG_SWEEPER_ENABLED — skipping start")
            return
        if self.running:
            return
        # Force a fresh policy fetch so the 3 new event types are emit-able
        # immediately. Without this, the first sweep cycle (60s in) might hit
        # the 120s policy-cache TTL before refreshing and silently drop emits.
        try:
            from ...event_emitter import _fetch_teg_policies
            await _fetch_teg_policies()
        except Exception as e:
            logger.debug(f"[CrossTegSweeper] preflight policy fetch failed: {e}")
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[CrossTegSweeper] starting (teg_id={self.teg_id}, "
            f"interval={SWEEP_INTERVAL_SEC}s, batch={SWEEP_BATCH_LIMIT}, "
            f"worker={self.worker_id})"
        )

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        # Release the lease on shutdown so the next-elected worker can pick
        # up promptly without waiting for the 90s TTL to expire.
        try:
            from ...redis_client import get_redis
            redis = await get_redis()
            if redis is not None:
                key = f"{LEADER_KEY_PREFIX}:{self.teg_id}"
                current = await redis.get(key)
                if current == self.worker_id:
                    await redis.delete(key)
        except Exception:
            pass
        logger.info("[CrossTegSweeper] stopped")

    # ------------------------------------------------------------------ main loop
    async def _run_loop(self) -> None:
        # Cold-start delay: don't compete with the rails-for-AI smoke test in
        # the same lifespan, and let the policy fetch settle.
        await asyncio.sleep(5)
        while self.running:
            try:
                acquired = await self._acquire_leader()
                self._is_leader_now = acquired
                if acquired:
                    await self._cycle_once()
                else:
                    # Non-leaders still refresh the gauge — cheap, and means
                    # every TEG worker reports the same value even before
                    # leadership rotation. Use the gauge as truth-of-state.
                    await self._snapshot_pending_gauge()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[CrossTegSweeper] unexpected loop error: {e}", exc_info=True)
                if SWEEP_ERRORS_TOTAL is not None:
                    try:
                        SWEEP_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="loop").inc()
                    except Exception:
                        pass
            await asyncio.sleep(SWEEP_INTERVAL_SEC)

    # ------------------------------------------------------------------ leader
    async def _acquire_leader(self) -> bool:
        """Acquire or refresh the TEG-scoped leader lease."""
        try:
            from ...redis_client import get_redis
            redis = await get_redis()
            if redis is None:
                # No Redis = no leader election possible. Fail-closed: skip
                # the cycle to avoid duplicate emission from concurrent workers.
                return False
            key = f"{LEADER_KEY_PREFIX}:{self.teg_id}"
            current = await redis.get(key)
            if current is None:
                ok = await redis.set(key, self.worker_id, ex=LEADER_LEASE_SEC, nx=True)
                return bool(ok)
            if current == self.worker_id:
                await redis.expire(key, LEADER_LEASE_SEC)
                return True
            return False
        except Exception as e:
            logger.debug(f"[CrossTegSweeper] leader acquire failed: {e}")
            return False

    # ------------------------------------------------------------------ cycle
    async def _cycle_once(self) -> None:
        t0 = time.time()
        stats = await self.coordinator.sweep_expired_coordinations(
            batch_limit=SWEEP_BATCH_LIMIT,
            emit_audit=self._emit_audit_event,
        )
        dur_ms = int((time.time() - t0) * 1000)
        self._last_stats = stats
        self._last_duration_ms = dur_ms
        self._last_cycle_iso = datetime.now(timezone.utc).isoformat()

        if SWEEP_CYCLE_TOTAL is not None:
            try:
                SWEEP_CYCLE_TOTAL.labels(teg_id=self.teg_id).inc()
                if stats.get("aborted", 0):
                    SWEEP_ABORTED_TOTAL.labels(teg_id=self.teg_id).inc(stats["aborted"])
                if stats.get("resumed", 0):
                    SWEEP_COMMIT_RESUMED_TOTAL.labels(teg_id=self.teg_id).inc(stats["resumed"])
                if stats.get("errors", 0):
                    SWEEP_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="row").inc(stats["errors"])
            except Exception:
                pass

        # §V0050 — stale-bookkeeping write-down (status-only; see
        # coordinator.sweep_stale_bookkeeping docstring for the safety argument).
        if STALE_SWEEP_ENABLED:
            try:
                st = await self.coordinator.sweep_stale_bookkeeping(
                    batch_limit=STALE_SWEEP_BATCH,
                    age_hours=STALE_SWEEP_AGE_HOURS,
                )
                stats["swept"] = st.get("swept", 0)
                stats["stale_remaining"] = st.get("remaining", 0)
                self._last_stats = stats
                try:
                    if SWEEP_SWEPT_TOTAL is not None and st.get("swept", 0):
                        SWEEP_SWEPT_TOTAL.labels(teg_id=self.teg_id).inc(st["swept"])
                    if STALE_BOOKKEEPING_GAUGE is not None:
                        STALE_BOOKKEEPING_GAUGE.labels(teg_id=self.teg_id).set(st.get("remaining", 0))
                except Exception:
                    pass
                if st.get("swept", 0):
                    await self._emit_audit_event(
                        "CrossTEGStaleSwept",
                        f"stale-sweep:{self.teg_id}",
                        {
                            "swept": st["swept"],
                            "remaining": st.get("remaining", 0),
                            "age_hours": STALE_SWEEP_AGE_HOURS,
                            "batch_limit": STALE_SWEEP_BATCH,
                        },
                    )
            except Exception as e:
                logger.error(f"[CrossTegSweeper] stale-bookkeeping sweep failed: {e}", exc_info=True)
                if SWEEP_ERRORS_TOTAL is not None:
                    try:
                        SWEEP_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="stale_sweep").inc()
                    except Exception:
                        pass

        # 2026-07-29 — stale cross-TEG fund-send write-down (status-only).
        if OUTFLOW_SWEEP_ENABLED:
            try:
                ot = await self.coordinator.sweep_stale_outflows(
                    batch_limit=OUTFLOW_SWEEP_BATCH,
                    age_hours=OUTFLOW_SWEEP_AGE_HOURS,
                )
                stats["outflows_swept"] = ot.get("swept", 0)
                stats["outflows_remaining"] = ot.get("remaining", 0)
                self._last_stats = stats
                if ot.get("swept", 0):
                    logger.warning(
                        f"[CrossTegSweeper] stale fund-send write-down: "
                        f"swept={ot['swept']} remaining={ot.get('remaining', 0)} "
                        f"age_hours={OUTFLOW_SWEEP_AGE_HOURS} (status-only, balances untouched)"
                    )
                    await self._emit_audit_event(
                        "CrossTEGStaleOutflowSwept",
                        f"outflow-sweep:{self.teg_id}",
                        {
                            "swept": ot["swept"],
                            "remaining": ot.get("remaining", 0),
                            "age_hours": OUTFLOW_SWEEP_AGE_HOURS,
                            "batch_limit": OUTFLOW_SWEEP_BATCH,
                            "status_only": True,
                        },
                    )
            except Exception as e:
                logger.error(f"[CrossTegSweeper] stale outflow sweep failed: {e}", exc_info=True)
                if SWEEP_ERRORS_TOTAL is not None:
                    try:
                        SWEEP_ERRORS_TOTAL.labels(teg_id=self.teg_id, reason="outflow_sweep").inc()
                    except Exception:
                        pass

        # 2026-07-29 §ESCROWSCAR-2 — orphaned exref deposit-leg write-down (status-only).
        if EXREF_SWEEP_ENABLED:
            try:
                xt = await self.coordinator.sweep_stale_exchange_legs(
                    batch_limit=EXREF_SWEEP_BATCH,
                    age_hours=EXREF_SWEEP_AGE_HOURS,
                )
                stats["exref_legs_swept"] = xt.get("swept", 0)
                stats["exref_legs_remaining"] = xt.get("remaining", 0)
                self._last_stats = stats
                if xt.get("swept", 0):
                    logger.warning(
                        f"[CrossTegSweeper] orphaned exref leg write-down: "
                        f"swept={xt['swept']} remaining={xt.get('remaining', 0)} "
                        f"age_hours={EXREF_SWEEP_AGE_HOURS} (status-only, balances untouched)"
                    )
                    await self._emit_audit_event(
                        "ExchangeOrphanExrefLegSwept",
                        f"exref-sweep:{self.teg_id}",
                        {
                            "swept": xt["swept"],
                            "remaining": xt.get("remaining", 0),
                            "age_hours": EXREF_SWEEP_AGE_HOURS,
                            "status_only": True,
                        },
                    )
            except Exception as e:
                logger.error(f"[CrossTegSweeper] orphaned exref sweep failed: {e}", exc_info=True)


        await self._snapshot_pending_gauge()

        if any(stats.get(k, 0) for k in ("aborted", "resumed", "errors")):
            logger.warning(
                f"[CrossTegSweeper] cycle: checked={stats['checked']} aborted={stats['aborted']} "
                f"resumed={stats['resumed']} errors={stats['errors']} "
                f"swept={stats.get('swept', 0)} stale_remaining={stats.get('stale_remaining', 0)} "
                f"duration_ms={dur_ms}"
            )
        else:
            logger.info(
                f"[CrossTegSweeper] cycle: checked={stats['checked']} aborted=0 resumed=0 "
                f"errors=0 swept={stats.get('swept', 0)} "
                f"stale_remaining={stats.get('stale_remaining', 0)} duration_ms={dur_ms}"
            )

    async def _snapshot_pending_gauge(self) -> None:
        """Refresh the pending-coordinations gauge with a cheap count query."""
        if PENDING_COORDINATIONS is None:
            return
        try:
            from sqlalchemy import select, func as _func
            from ...database.models import CrossTEGTransfer, CrossTEGTransferStatus

            db_factory = self.coordinator.store._db_factory
            gen = db_factory()
            session = next(gen)
            try:
                cutoff = datetime.now(timezone.utc)
                result = session.execute(
                    select(CrossTEGTransfer.status, _func.count())
                    .where(
                        CrossTEGTransfer.role == "source",
                        CrossTEGTransfer.source_teg_id == self.teg_id,
                        CrossTEGTransfer.expires_at < cutoff,
                        CrossTEGTransfer.status.in_([
                            CrossTEGTransferStatus.INITIATED,
                            CrossTEGTransferStatus.COMMITTED,
                        ]),
                        CrossTEGTransfer.completed_at.is_(None),
                    )
                    .group_by(CrossTEGTransfer.status)
                )
                counts = {}
                for s, n in result.all():
                    key = s.value if hasattr(s, "value") else str(s)
                    counts[key] = n
                # Zero out missing labels so stale series drop out.
                for status_val in ("initiated", "committed"):
                    PENDING_COORDINATIONS.labels(teg_id=self.teg_id, status=status_val).set(
                        counts.get(status_val, 0)
                    )
            finally:
                try:
                    next(gen)
                except StopIteration:
                    pass
        except Exception as e:
            logger.debug(f"[CrossTegSweeper] gauge snapshot failed: {e}")

    # ------------------------------------------------------------------ audit
    async def _emit_audit_event(self, event_type: str, aggregate_id: str, data: Dict) -> None:
        """Best-effort audit emission to EventStore via TEG event emitter."""
        try:
            if self._emitter is None:
                from ...event_emitter import EventEmitter
                # Match the canonical TEG emitter wiring used by
                # `transfer_service_enhanced.py` / `staking_crud_enhanced.py`:
                # EventStore expects X-Internal-Key from EVENT_STORE_API_KEY,
                # not INTERNAL_API_KEY.
                self._emitter = EventEmitter(
                    event_store_url=os.getenv("EVENT_STORE_URL", "http://event-store:8200"),
                    internal_api_key=os.getenv("EVENT_STORE_API_KEY", ""),
                    source_service=f"teg-{self.teg_id}",
                )
            enriched = {**data, "teg_id": self.teg_id, "sweeper_worker": self.worker_id}
            await self._emitter.emit(
                event_type=event_type,
                aggregate_id=aggregate_id,
                aggregate_type="CrossTEGTransfer",
                data=enriched,
            )
        except Exception as e:
            logger.debug(f"[CrossTegSweeper] audit emit failed ({event_type}): {e}")

    # ------------------------------------------------------------------ inspection (for admin endpoints)
    def snapshot(self) -> Dict:
        """Return a copy of last-cycle state for /admin/cross-teg-sweeper/status."""
        return {
            "teg_id": self.teg_id,
            "worker_id": self.worker_id,
            "is_leader": self._is_leader_now,
            "last_cycle_iso": self._last_cycle_iso,
            "last_duration_ms": self._last_duration_ms,
            "last_stats": dict(self._last_stats),
            "interval_sec": SWEEP_INTERVAL_SEC,
            "batch_limit": SWEEP_BATCH_LIMIT,
            "enabled": SWEEPER_ENABLED,
        }


# ---------------------------------------------------------------------------
# Module-level singleton + start/stop helpers (mirrors background_tasks pattern)
# ---------------------------------------------------------------------------

_sweeper_singleton: Optional[CrossTegSweeper] = None


def get_sweeper() -> Optional[CrossTegSweeper]:
    return _sweeper_singleton


async def start_sweeper(coordinator: DistributedTransactionCoordinator) -> None:
    global _sweeper_singleton
    if _sweeper_singleton is not None:
        return
    _sweeper_singleton = CrossTegSweeper(coordinator)
    await _sweeper_singleton.start()


async def stop_sweeper() -> None:
    global _sweeper_singleton
    if _sweeper_singleton is None:
        return
    await _sweeper_singleton.stop()
    _sweeper_singleton = None
