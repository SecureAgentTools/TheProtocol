"""Self-healing janitor: reap stuck idle-in-transaction sessions and long
lock-waiters on the local registry DB.

§2026-06-15 — added after a federation card-upsert ``FOR UPDATE`` convoy plus
~60-min idle-in-transaction sessions (canary workers holding a DB transaction
open across a hung TEG RPC) pegged registry-a CPU and made login lag.

Defense in depth:
  * First line  = DB-level guards (``idle_in_transaction_session_timeout``,
    ``lock_timeout``) set via ALTER DATABASE / compose — Postgres auto-aborts.
  * This worker = the ACTIVE backstop *with observability*. It terminates any
    idle-in-transaction older than IDLE_TXN_REAPER_IDLE_SEC and cancels any
    lock-blocked query older than IDLE_TXN_REAPER_LOCK_SEC, emitting a metric +
    WARNING log each time so the condition is visible. Thresholds sit ABOVE the
    DB guards, so it only fires for connections that somehow escaped them
    (e.g. a pooled server connection that predates the setting).

Leader-elected (one reaper per cluster), env-gated (IDLE_TXN_REAPER_ENABLED,
default true). Connects to the local DB via the app session factory; the
SELECTs are quick autocommit statements, safe through pgbouncer.
"""
from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from sqlalchemy import text

from ..database import AsyncSessionLocal
from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

try:  # optional metric; guard against double-registration on re-import
    from prometheus_client import Counter

    IDLE_TXN_REAPED_TOTAL = Counter(
        "idle_txn_reaper_reaped_total",
        "Stuck DB sessions reaped by the idle-txn self-healing janitor",
        ["action"],
    )
except Exception:  # noqa: BLE001
    IDLE_TXN_REAPED_TOTAL = None


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


_TERMINATE_IDLE_SQL = text(
    """
    SELECT count(*) FROM (
        SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND state = 'idle in transaction'
          AND now() - state_change > make_interval(secs => :s)
    ) t
    """
)

_CANCEL_LOCK_SQL = text(
    """
    SELECT count(*) FROM (
        SELECT pg_cancel_backend(pid) FROM pg_stat_activity
        WHERE datname = current_database()
          AND pid <> pg_backend_pid()
          AND state = 'active'
          AND wait_event_type = 'Lock'
          AND now() - query_start > make_interval(secs => :s)
    ) t
    """
)


class IdleTxnReaper(BackgroundWorker):
    """Terminate stuck idle-in-transaction + cancel long lock-waiters."""

    worker_id = "idle_txn_reaper"
    leader_key = "idle_txn_reaper"
    interval_sec = _env_int("IDLE_TXN_REAPER_INTERVAL_SEC", 30)
    cold_start_delay_sec = 20

    def _should_run(self) -> bool:
        return os.getenv("IDLE_TXN_REAPER_ENABLED", "true").lower() == "true"

    async def _cycle_once(self) -> None:
        idle_sec = _env_int("IDLE_TXN_REAPER_IDLE_SEC", 120)
        lock_sec = _env_int("IDLE_TXN_REAPER_LOCK_SEC", 30)
        terminated = 0
        cancelled = 0
        async with AsyncSessionLocal() as db:
            res = await db.execute(_TERMINATE_IDLE_SQL, {"s": idle_sec})
            terminated = int(res.scalar() or 0)
            res = await db.execute(_CANCEL_LOCK_SQL, {"s": lock_sec})
            cancelled = int(res.scalar() or 0)
            await db.commit()

        if terminated or cancelled:
            logger.warning(
                "[IdleTxnReaper] self-heal: terminated %d idle-in-tx (>%ds), "
                "cancelled %d lock-waiters (>%ds)",
                terminated, idle_sec, cancelled, lock_sec,
            )
            if IDLE_TXN_REAPED_TOTAL is not None:
                try:
                    if terminated:
                        IDLE_TXN_REAPED_TOTAL.labels(
                            action="terminate_idle_in_tx"
                        ).inc(terminated)
                    if cancelled:
                        IDLE_TXN_REAPED_TOTAL.labels(
                            action="cancel_lock_wait"
                        ).inc(cancelled)
                except Exception:  # noqa: BLE001
                    pass

        self._stats = {
            "terminated_idle_in_tx": terminated,
            "cancelled_lock_waiters": cancelled,
            "idle_threshold_sec": idle_sec,
            "lock_threshold_sec": lock_sec,
        }


_reaper: Optional[IdleTxnReaper] = None


def get_idle_txn_reaper() -> IdleTxnReaper:
    global _reaper
    if _reaper is None:
        _reaper = IdleTxnReaper()
    return _reaper


async def start_idle_txn_reaper() -> None:
    """Called from main.py startup."""
    await get_idle_txn_reaper().start()


async def stop_idle_txn_reaper() -> None:
    """Called from main.py shutdown."""
    if _reaper is not None:
        await _reaper.stop()


def get_last_cycle_stats() -> Dict[str, Any]:
    """Read-only access to the most recent reap stats (for admin endpoints)."""
    if _reaper is None:
        return {}
    return dict(_reaper._stats)
