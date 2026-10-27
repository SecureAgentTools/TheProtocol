"""§SOVKIT K1 / V0372 (2026-09-14) — the drainer of the registry's durable ledger-emit outbox (`es_emit_outbox`, migration 0178).

Why it exists: K1 deleted the registry's Kafka producer (his word: Kafka is private to the event store), and agentvault2-85
measured what that producer had been doing besides bypassing the store's checks: BUFFERING the registry's writes through a
store restart. The emitter's three fast attempts (1 s, 2 s) then lost every emit during a store outage longer than ~4 s.
The emitter now DEFERS an emit the store could not take (connection errors, timeouts, 429, 5xx; never a 4xx) into this
table, and this worker re-emits it when the store answers again. The frame Redis holds nothing across a restart (no AOF,
no RDB), so the queue lives in the registry's own database.

Leader-elected through `_worker_base.BackgroundWorker` (vitals stamped by the base every cycle, `worker_errors_total` on a
cycle error). Each cycle takes up to `batch` due rows FOR UPDATE SKIP LOCKED, re-emits each through the same emitter with
deferral OFF and one attempt, closes a delivered row (`delivered_at`; the store answers 409 for a key it already holds,
which the emitter counts as success), and on a failure bumps `attempts` with a short backoff; a row past its attempt
budget, or refused with a non-retryable answer (a 4xx: the store will never take it), is parked with `dead_at` and logged
`[EMIT-DEAD]` with its type, aggregate and key for a re-emit by hand; nothing is deleted. Counters: drained, dead;
gauge: pending. Ordering: a deferred event reaches the store later than events emitted after it; the store's
projections read the event's own timestamp, the same property the TEG's outbox has.

Env: ES_EMIT_OUTBOX_ENABLED (default true; the emitter's deferral reads the same name), ES_EMIT_OUTBOX_INTERVAL_SEC (5),
ES_EMIT_OUTBOX_MAX_ATTEMPTS (720: with the 60 s ceiling about twelve hours), ES_EMIT_OUTBOX_BATCH (50).
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import func, select

from agentvault_registry import models
from agentvault_registry.database import get_db_context

from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

_BACKOFF_SEC = (5, 10, 20, 40, 60)


def backoff_seconds(attempts: int) -> int:
    """The wait before the next attempt, by how many have failed: 5, 10, 20, 40, then 60 s each."""
    if attempts <= 0:
        return _BACKOFF_SEC[0]
    return _BACKOFF_SEC[min(attempts, len(_BACKOFF_SEC)) - 1]


def outbox_enabled() -> bool:
    return (os.getenv("ES_EMIT_OUTBOX_ENABLED") or "true").strip().lower() == "true"


def next_state(row_attempts: int, ok: bool, outcome: Dict[str, Any], max_attempts: int, now: datetime.datetime) -> Dict[str, Any]:
    """The pure decision of one drain attempt: what the row becomes. `outcome` is what the emitter reported
    (`retryable`, `status`, `error`); an empty outcome (the emitter refused before any attempt, e.g. a payload that
    cannot serialise) is NOT retryable."""
    if ok:
        return {"delivered_at": now}
    attempts = (row_attempts or 0) + 1
    err = str(outcome.get("error") or "no answer")[:500]
    if attempts >= max_attempts or not outcome.get("retryable", False):
        return {"attempts": attempts, "last_error": err, "dead_at": now}
    return {"attempts": attempts, "last_error": err,
            "next_attempt_at": now + datetime.timedelta(seconds=backoff_seconds(attempts))}


try:
    from prometheus_client import Counter as _OC, Gauge as _OG

    OUTBOX_DRAINED_TOTAL = _OC("registry_es_emit_outbox_drained_total", "Deferred ledger emits delivered by the drainer")
    OUTBOX_DEAD_TOTAL = _OC("registry_es_emit_outbox_dead_total", "Deferred ledger emits parked past their attempt budget or refused for good (re-emit by hand)")
    OUTBOX_PENDING = _OG("registry_es_emit_outbox_pending", "Deferred ledger emits still open", multiprocess_mode="max")
except Exception:  # pragma: no cover — a second registration in a test process, or no prometheus
    OUTBOX_DRAINED_TOTAL = OUTBOX_DEAD_TOTAL = OUTBOX_PENDING = None


class EsEmitOutboxDrainer(BackgroundWorker):
    worker_id = "es_emit_outbox"
    leader_key = "es_emit_outbox"
    interval_sec = int(os.getenv("ES_EMIT_OUTBOX_INTERVAL_SEC", "5") or 5)
    cold_start_delay_sec = 10

    def __init__(self) -> None:
        super().__init__()
        self.batch = int(os.getenv("ES_EMIT_OUTBOX_BATCH", "50") or 50)
        self.max_attempts = int(os.getenv("ES_EMIT_OUTBOX_MAX_ATTEMPTS", "720") or 720)

    def _should_run(self) -> bool:
        return outbox_enabled()

    async def _cycle_once(self) -> None:
        from agentvault_registry.event_emitter import get_event_emitter
        emitter = get_event_emitter()
        drained = dead = retried = 0
        pending = 0
        async with get_db_context() as db:
            now = datetime.datetime.now(datetime.timezone.utc)
            M = models.EsEmitOutbox
            rows = (await db.execute(
                select(M).where(M.delivered_at.is_(None), M.dead_at.is_(None), M.next_attempt_at <= now)
                .order_by(M.id).limit(self.batch).with_for_update(skip_locked=True)
            )).scalars().all()
            for row in rows:
                outcome: Dict[str, Any] = {}
                p = row.payload or {}
                try:
                    ok = await emitter.emit(
                        event_type=row.event_type, aggregate_id=row.aggregate_id, data=p.get("data") or {},
                        aggregate_type=row.aggregate_type or "Agent", metadata=p.get("metadata") or None,
                        idempotency_key=row.idempotency_key, max_retries=1, defer=False, outcome=outcome,
                    )
                except Exception as e:  # noqa: BLE001 — one row's failure must not stop the batch
                    ok = False
                    outcome = {"retryable": True, "error": f"{type(e).__name__}: {e}"}
                t = datetime.datetime.now(datetime.timezone.utc)
                for k, v in next_state(row.attempts, ok, outcome, self.max_attempts, t).items():
                    setattr(row, k, v)
                if ok:
                    drained += 1
                elif row.dead_at is not None:
                    dead += 1
                    logger.error("[EMIT-DEAD] %s aggregate=%s key=%s after %d attempt(s): %s (parked in es_emit_outbox; re-emit by hand)",
                                 row.event_type, row.aggregate_id, row.idempotency_key, row.attempts, row.last_error)
                else:
                    retried += 1
            pending = int((await db.execute(
                select(func.count()).select_from(M).where(M.delivered_at.is_(None), M.dead_at.is_(None))
            )).scalar() or 0)
            await db.commit()
        if OUTBOX_DRAINED_TOTAL is not None:
            try:
                if drained:
                    OUTBOX_DRAINED_TOTAL.inc(drained)
                if dead:
                    OUTBOX_DEAD_TOTAL.inc(dead)
                OUTBOX_PENDING.set(pending)
            except Exception:  # noqa: BLE001
                pass
        if drained or dead or retried:
            logger.info("[es_emit_outbox] drained=%d retried=%d dead=%d pending=%d", drained, retried, dead, pending)
        self._stats = {"drained_this_cycle": drained, "retried_this_cycle": retried, "dead_this_cycle": dead, "pending_now": pending}

    def _last_stats(self) -> Dict[str, Any]:
        return dict(self._stats or {})


_drainer: Optional[EsEmitOutboxDrainer] = None


def get_es_emit_outbox_drainer() -> EsEmitOutboxDrainer:
    global _drainer
    if _drainer is None:
        _drainer = EsEmitOutboxDrainer()
    return _drainer
