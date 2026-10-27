"""
collusion_worker.py — Economic Engine Sprint 10 §5.4

Daily background task that:
  1. Runs BayesianTrustService.run_decay_pass() (inactivity decay on peer discounts)
  2. Runs CollusionDetector.run() (SCC collusion ring detection)

§pass28 Phase 5 (2026-05-17) — refactored to inherit BackgroundWorker.
Adds 4 Prom metrics + snapshot stats for the Tier-3 modal at
`/admin/reactors` → Worker Tasks → Collusion Detection.

Registration in main.py startup_event:
    from agentvault_registry.background_tasks.collusion_worker import (
        start_collusion_worker, stop_collusion_worker
    )
    asyncio.create_task(start_collusion_worker())

Shutdown in main.py shutdown_event:
    await stop_collusion_worker()
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..database import get_db_context
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

# Default: run once every 24 hours; override with COLLUSION_WORKER_INTERVAL_SECONDS
_INTERVAL_SECONDS = int(
    float(os.environ.get("COLLUSION_WORKER_INTERVAL_SECONDS", str(24 * 3600)))
)


# §pass28 Phase 5 — Prometheus metrics (lazy, best-effort).
try:
    from prometheus_client import Counter as _CWCounter, Gauge as _CWGauge

    COLLUSION_CYCLE_TOTAL = _CWCounter(
        "collusion_cycle_total",
        "Collusion-worker cycles run (leader only)",
        labelnames=["registry_id"],
    )
    COLLUSION_DECAY_PASSES_TOTAL = _CWCounter(
        "collusion_decay_passes_total",
        "Bayesian trust decay passes completed",
        labelnames=["registry_id"],
    )
    COLLUSION_RINGS_DETECTED_TOTAL = _CWCounter(
        "collusion_rings_detected_total",
        "Collusion rings flagged (CollusionRingDetected rows)",
        labelnames=["registry_id"],
    )
    COLLUSION_ERRORS_TOTAL = _CWCounter(
        "collusion_errors_total",
        "Errors in collusion worker cycle, by stage and reason",
        labelnames=["registry_id", "stage", "reason"],
    )
    COLLUSION_LAST_CYCLE_DURATION_MS = _CWGauge(
        "collusion_last_cycle_duration_ms",
        "Wall-clock duration of the most recent cycle, ms",
        labelnames=["registry_id"],
        multiprocess_mode="max",
    )
except Exception:  # pragma: no cover
    COLLUSION_CYCLE_TOTAL = None
    COLLUSION_DECAY_PASSES_TOTAL = None
    COLLUSION_RINGS_DETECTED_TOTAL = None
    COLLUSION_ERRORS_TOTAL = None
    COLLUSION_LAST_CYCLE_DURATION_MS = None


_REGISTRY_ID_LABEL = os.getenv("REGISTRY_NAME", "registry-a")


# Most recent cycle stats — populated by _run_cycle, read by snapshot().
_LAST_CYCLE_STATS: Dict[str, Any] = {
    "last_cycle_iso": None,
    "last_duration_ms": 0,
    "decay_pass_status": "never_run",   # ok | error | never_run
    "decay_pass_error": None,
    "collusion_scan_status": "never_run",
    "collusion_scan_error": None,
    "rings_detected_last_cycle": 0,
}


class CollusionWorker(BackgroundWorker):
    """Daily collusion detection + Bayesian trust decay (§pass28 Phase 5)."""

    worker_id = "collusion_worker"
    leader_key = "collusion_worker"
    interval_sec = _INTERVAL_SECONDS
    # Stagger 120s after startup so DB is fully ready before the first cycle.
    cold_start_delay_sec = 120

    async def _cycle_once(self) -> None:
        await self._run_cycle()
        self._stats = dict(_LAST_CYCLE_STATS)

    async def _run_cycle(self):
        """Execute one full cycle: decay pass + collusion scan."""
        cycle_start = datetime.now(timezone.utc)
        logger.info(f"[CollusionWorker] Starting daily cycle at {cycle_start.isoformat()}")

        _LAST_CYCLE_STATS["last_cycle_iso"] = cycle_start.isoformat()
        _LAST_CYCLE_STATS["decay_pass_error"] = None
        _LAST_CYCLE_STATS["collusion_scan_error"] = None
        _LAST_CYCLE_STATS["rings_detected_last_cycle"] = 0

        if COLLUSION_CYCLE_TOTAL is not None:
            try:
                COLLUSION_CYCLE_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc()
            except Exception:
                pass

        # Step 1: Bayesian inactivity decay
        try:
            from ..services.bayesian_trust import get_bayesian_trust_service
            async with get_db_context() as db:
                svc = get_bayesian_trust_service()
                await svc.run_decay_pass(db)
            _LAST_CYCLE_STATS["decay_pass_status"] = "ok"
            if COLLUSION_DECAY_PASSES_TOTAL is not None:
                try:
                    COLLUSION_DECAY_PASSES_TOTAL.labels(registry_id=_REGISTRY_ID_LABEL).inc()
                except Exception:
                    pass
        except Exception as e:
            _LAST_CYCLE_STATS["decay_pass_status"] = "error"
            _LAST_CYCLE_STATS["decay_pass_error"] = str(e)[:240]
            if COLLUSION_ERRORS_TOTAL is not None:
                try:
                    COLLUSION_ERRORS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, stage="decay", reason="exception"
                    ).inc()
                except Exception:
                    pass
            logger.error(f"[CollusionWorker] Bayesian decay pass failed: {e}", exc_info=True)

        # Step 2: SCC collusion detection
        try:
            from ..services.collusion_detector import get_collusion_detector
            async with get_db_context() as db:
                detector = get_collusion_detector()
                rings = await detector.run(db)
                ring_count = len(rings or [])
                _LAST_CYCLE_STATS["rings_detected_last_cycle"] = ring_count
                _LAST_CYCLE_STATS["collusion_scan_status"] = "ok"
                if rings:
                    if COLLUSION_RINGS_DETECTED_TOTAL is not None:
                        try:
                            COLLUSION_RINGS_DETECTED_TOTAL.labels(
                                registry_id=_REGISTRY_ID_LABEL
                            ).inc(ring_count)
                        except Exception:
                            pass
                    logger.warning(
                        f"[CollusionWorker] {ring_count} ring(s) flagged: "
                        + ", ".join(
                            f"size={r['scc_size']} score={r['score']}"
                            for r in rings
                        )
                    )
                else:
                    logger.info("[CollusionWorker] No collusion rings detected this cycle")
        except Exception as e:
            _LAST_CYCLE_STATS["collusion_scan_status"] = "error"
            _LAST_CYCLE_STATS["collusion_scan_error"] = str(e)[:240]
            if COLLUSION_ERRORS_TOTAL is not None:
                try:
                    COLLUSION_ERRORS_TOTAL.labels(
                        registry_id=_REGISTRY_ID_LABEL, stage="scan", reason="exception"
                    ).inc()
                except Exception:
                    pass
            logger.error(f"[CollusionWorker] Collusion detection failed: {e}", exc_info=True)

        elapsed_ms = int((datetime.now(timezone.utc) - cycle_start).total_seconds() * 1000)
        _LAST_CYCLE_STATS["last_duration_ms"] = elapsed_ms
        if COLLUSION_LAST_CYCLE_DURATION_MS is not None:
            try:
                COLLUSION_LAST_CYCLE_DURATION_MS.labels(registry_id=_REGISTRY_ID_LABEL).set(elapsed_ms)
            except Exception:
                pass
        logger.info(f"[CollusionWorker] Cycle complete in {elapsed_ms/1000:.1f}s")


# Singleton
_worker: Optional[CollusionWorker] = None


def get_collusion_worker() -> CollusionWorker:
    global _worker
    if _worker is None:
        _worker = CollusionWorker()
    return _worker


async def start_collusion_worker():
    """Start the collusion / Bayesian decay worker."""
    worker = get_collusion_worker()
    await worker.start()


async def stop_collusion_worker():
    """Stop the collusion / Bayesian decay worker."""
    worker = get_collusion_worker()
    await worker.stop()


def get_last_cycle_stats() -> Dict[str, Any]:
    """Read-only access to most recent cycle stats (for admin endpoint)."""
    return dict(_LAST_CYCLE_STATS)


def get_interval_sec() -> int:
    return _INTERVAL_SECONDS
