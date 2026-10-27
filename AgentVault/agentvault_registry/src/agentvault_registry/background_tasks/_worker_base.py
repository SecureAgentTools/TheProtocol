"""Shared base for leader-elected periodic registry-side background workers.

§pass27 Phase 0 (2026-05-17). Extracts the duplicated lifecycle boilerplate
from the 3 registry-side workers that ship a Tier-3 observability modal:

  - canary_judge          (registry-a only)
  - canary_rebalancer     (registry-a only)
  - saga_timeout_checker  (registry-a + frame-b-registry, default-on)

§pass26's `core/cross_teg/sweeper.CrossTegSweeper` is the original template for
this pattern but lives in the TEG codebase (no cross-package import), so it
does NOT inherit from this base — it ships its own lifecycle with the same
contract. The `multiprocess_mode='max'` gauge fix the handover calls for is
applied to that sweeper in-place, not via inheritance.

What the base captures
----------------------
  - start / stop lifecycle (asyncio.Task, cancellation-safe)
  - cold-start jitter to dodge canary warmup blips
  - leader election via the canonical `leader.try_acquire_leadership`
    (Redis SETNX 30s TTL, fail-OPEN on Redis unreach for single-worker)
  - per-cycle timing (duration_ms, last_cycle_iso)
  - generic `worker_errors_total{worker_id,reason}` Prometheus counter so
    operators see worker-level error spikes without per-worker plumbing
  - snapshot contract for `/admin/{worker_id}/status` admin endpoints

What subclasses provide
-----------------------
  - `worker_id` (class attr)              — used as Prom label + log prefix
  - `leader_key` (class attr)             — Redis lock name, namespaced
  - `interval_sec` / `cold_start_delay_sec`
  - `_should_run()`                       — env-flag gate (return False to skip)
  - `_cycle_once()`                       — the actual work (called when leader)
  - `_last_stats()`                       — per-worker stats dict for snapshot
  - optional `_non_leader_tick()`         — runs when worker is NOT leader (rare)

The snapshot contract (consumed by admin routers):

  {
    "worker_id": str,
    "registry_id": str,             # REGISTRY_NAME or "registry-a" default
    "is_leader_now": bool,
    "last_cycle_iso": Optional[str],
    "last_duration_ms": int,
    "last_stats": Dict[str, Any],   # subclass-defined shape
    "interval_sec": int,
    "enabled": bool,
  }
"""
from __future__ import annotations

import asyncio
import datetime
import logging
import os
import time
from typing import Any, Dict, Optional

from .leader import try_acquire_leadership, is_leader as _is_leader
from . import vitals as _vitals

logger = logging.getLogger(__name__)


# Generic worker-errors counter shared across all workers built on this base.
# Subclass-specific metrics (Counter/Gauge/Histogram) stay in the subclass file.
try:
    from prometheus_client import Counter as _BWCounter

    WORKER_ERRORS_TOTAL = _BWCounter(
        "worker_errors_total",
        "Background worker errors by worker_id and reason (base-class instrumented)",
        labelnames=["worker_id", "reason"],
    )
except Exception:  # pragma: no cover
    WORKER_ERRORS_TOTAL = None  # type: ignore[assignment]


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


class BackgroundWorker:
    """Leader-elected periodic worker base.

    Subclasses override `worker_id`, `leader_key`, `interval_sec`, `_should_run`,
    `_cycle_once`, and (optionally) `_last_stats` + `_non_leader_tick`.
    """

    # --- subclass-overridable class attrs --------------------------------
    worker_id: str = "_base"
    leader_key: str = "_base"
    interval_sec: int = 60
    cold_start_delay_sec: int = 5

    # --- lifecycle -------------------------------------------------------
    def __init__(self) -> None:
        self.running: bool = False
        self.task: Optional[asyncio.Task] = None
        self._last_cycle_at: Optional[datetime.datetime] = None
        self._last_duration_ms: int = 0
        self._is_leader_now: bool = False
        # Cached per-subclass stats — overwritten on every _cycle_once.
        # Subclasses populate via `self._stats = {...}` inside _cycle_once.
        self._stats: Dict[str, Any] = {}
        self._registry_id: str = os.getenv("REGISTRY_NAME", "registry-a")

    async def start(self) -> None:
        if self.running:
            return
        # §VITALS: declare BEFORE the gate. A worker switched off by env is a row
        # reading DISABLED; an absent row used to be indistinguishable from a
        # worker nobody ever wrote down (27 of 50 read "(undocumented worker)").
        enabled = self._should_run()
        try:
            await _vitals.register(
                self.worker_id, module=type(self).__module__,
                pattern="BackgroundWorker", interval_sec=self.interval_sec,
                enabled=enabled,
                # §FRAMELIC row 167 — `gate` is a roster field nothing ever filled, so a
                # DISABLED row said "off" and never "off because of THIS". Subclasses that
                # name their flag get it printed; the rest are unchanged.
                gate=getattr(self, "gate_label", "") or "",
            )
        except Exception:  # never let the declaration stop the worker
            pass
        if not enabled:
            logger.info(f"[{self.worker_id}] disabled via env gate; skipping start")
            return
        self.running = True
        self.task = asyncio.create_task(self._run_loop())
        logger.info(
            f"[{self.worker_id}] starting (interval={self.interval_sec}s, "
            f"registry={self._registry_id})"
        )

    async def stop(self) -> None:
        self.running = False
        if self.task is not None:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info(f"[{self.worker_id}] stopped")

    # --- run loop --------------------------------------------------------
    async def _run_loop(self) -> None:
        # Cold-start jitter: avoid all workers racing in the same tick after
        # a fresh container start. Also dodges canary warmup blips.
        if self.cold_start_delay_sec:
            await asyncio.sleep(self.cold_start_delay_sec)

        while self.running:
            try:
                if not self._should_run():
                    await asyncio.sleep(self.interval_sec)
                    continue
                acquired = await try_acquire_leadership(self.leader_key)
                self._is_leader_now = acquired
                if acquired:
                    t0 = time.time()
                    _outcome, _err = _vitals.OUTCOME_OK, None
                    try:
                        await self._cycle_once()
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        _outcome, _err = _vitals.OUTCOME_ERROR, f"{type(e).__name__}: {e}"
                        logger.error(
                            f"[{self.worker_id}] cycle error: {e}", exc_info=True
                        )
                        if WORKER_ERRORS_TOTAL is not None:
                            try:
                                WORKER_ERRORS_TOTAL.labels(
                                    worker_id=self.worker_id, reason="cycle"
                                ).inc()
                            except Exception:
                                pass
                    self._last_duration_ms = int((time.time() - t0) * 1000)
                    self._last_cycle_at = _utcnow()
                    # §VITALS: cross-worker stamp. `_last_cycle_at` above is this
                    # PROCESS's memory — on a 38-worker gunicorn the other 37 answer
                    # `unknown`, which is how a worker's death stayed invisible.
                    await _vitals.stamp(
                        self.worker_id, _outcome,
                        duration_ms=self._last_duration_ms, error=_err,
                        stats=dict(self._stats) if self._stats else None,
                    )
                else:
                    try:
                        await self._non_leader_tick()
                    except Exception as e:
                        logger.debug(f"[{self.worker_id}] non-leader tick error: {e}")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(
                    f"[{self.worker_id}] unexpected loop error: {e}", exc_info=True
                )
                if WORKER_ERRORS_TOTAL is not None:
                    try:
                        WORKER_ERRORS_TOTAL.labels(
                            worker_id=self.worker_id, reason="loop"
                        ).inc()
                    except Exception:
                        pass
            await asyncio.sleep(self.interval_sec)

    # --- subclass override points ----------------------------------------
    def _should_run(self) -> bool:
        """Return False to disable the worker (env-flag gate)."""
        return True

    async def _cycle_once(self) -> None:
        """Subclass: do one unit of leader-only work. Set `self._stats`."""
        raise NotImplementedError

    async def _non_leader_tick(self) -> None:
        """Subclass hook for work the non-leader can do (e.g. local metric refresh)."""
        return None

    # --- inspection ------------------------------------------------------
    async def is_leader(self) -> bool:
        """Live leadership check — calls into Redis. Avoid in hot loops."""
        try:
            return await _is_leader(self.leader_key)
        except Exception:
            return self._is_leader_now

    def snapshot(self) -> Dict[str, Any]:
        """Public state contract consumed by /admin/{worker_id}/status."""
        return {
            "worker_id": self.worker_id,
            "registry_id": self._registry_id,
            "is_leader_now": self._is_leader_now,
            "last_cycle_iso": self._last_cycle_at.isoformat()
            if self._last_cycle_at
            else None,
            "last_duration_ms": self._last_duration_ms,
            "last_stats": dict(self._stats),
            "interval_sec": self.interval_sec,
            "enabled": self._should_run(),
        }
