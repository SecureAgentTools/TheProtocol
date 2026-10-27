"""§LEDGERGATE (V0599, 2026-10-11) — the drainer of owed account-deletion forfeitures (forfeitures_owed, migration 0190).

Why it exists: an account's anonymization drains each agent's liquid balance to the treasury best-effort (the GDPR clock
must not stall on the TEG), and a drain that failed left the balance on the revoked agent with nothing to retry it. The
anonymization now records such a forfeiture as owed in its own transaction; this worker drains it with the deletion's
own key (the row's id, acctdel-forfeit-<deletion>-<agent>), so a drain that landed but whose answer was lost replays the
TEG's cached result instead of draining twice.

Leader-elected through `_worker_base.BackgroundWorker`. A drained row closes with `done_at`. A refusal that says the money
is not there to take (400, 404, 422: the balance moved, the agent is gone, the request is not one the TEG takes) parks the
row at once with `dead_at`; everything else (the ledger gate's refusal, a 409 while the same key is in flight, a 403 while
the identity fabric recovers, a 5xx, the transport class) waits longer each time (30 s, 1, 2, 5, then 10 min) until the
attempt budget, which parks it too. A parked row is logged [FORFEIT-DEAD] with the agent and the reason (money_verify's
stranded report names its balance), never deleted.

Env: FORFEITURE_RETRY_ENABLED (default true), FORFEITURE_RETRY_INTERVAL_SEC (60), FORFEITURE_RETRY_BATCH (20),
FORFEITURE_RETRY_MAX_ATTEMPTS (288).
"""
from __future__ import annotations

import datetime
import logging
import os
from typing import Any, Dict

from sqlalchemy import func, select

from agentvault_registry import models
from agentvault_registry.database import get_db_context

from ._worker_base import BackgroundWorker

logger = logging.getLogger(__name__)

_BACKOFF_SEC = (30, 60, 120, 300, 600)
_FINAL_STATUSES = (400, 404, 422)   # the TEG says the money is not there to take: retrying cannot change it


def backoff_seconds(attempts: int) -> int:
    if attempts <= 0:
        return _BACKOFF_SEC[0]
    return _BACKOFF_SEC[min(attempts, len(_BACKOFF_SEC)) - 1]


def retry_enabled() -> bool:
    return (os.getenv("FORFEITURE_RETRY_ENABLED") or "true").strip().lower() == "true"


def next_state(row_attempts: int, outcome: Dict[str, Any], max_attempts: int, now: datetime.datetime) -> Dict[str, Any]:
    """The pure decision of one drain: outcome {"moved": True} | {"status": <http status or None>, "why": ..., "error": ...}."""
    if outcome.get("moved"):
        return {"done_at": now}
    attempts = (row_attempts or 0) + 1
    err = str(outcome.get("error") or "no answer")[:500]
    status = outcome.get("status")
    final = outcome.get("why") == "teg_refused" and status is not None and int(status) in _FINAL_STATUSES
    if final or attempts >= max_attempts:
        return {"attempts": attempts, "last_error": err, "dead_at": now}
    return {"attempts": attempts, "last_error": err,
            "next_attempt_at": now + datetime.timedelta(seconds=backoff_seconds(attempts))}


async def _drain(row) -> Dict[str, Any]:
    from agentvault_registry.services.escrow import EscrowError, escrow_deposit
    from agentvault_registry.services.ledger_unavailable import refusal_from_error
    try:
        await escrow_deposit(row.agent_did, row.amount, row.id, reason="account_deletion_forfeit")
        return {"moved": True}
    except EscrowError as e:
        why = "ledger_unavailable" if refusal_from_error(e) is not None else "teg_refused"
        return {"status": e.status_code, "why": why, "error": f"{e.status_code}: {e.message}"}
    except Exception as e:  # noqa: BLE001 — the transport class
        return {"status": None, "why": "transport", "error": f"{type(e).__name__}: {e}"}


try:
    from prometheus_client import Counter as _XC, Gauge as _XG

    FORFEITS_TOTAL = _XC("registry_forfeitures_owed_total", "Owed forfeiture drains by outcome (drained, retried, dead)",
                         ["outcome"])
    FORFEITS_OWED = _XG("registry_forfeitures_owed_open", "Account-deletion forfeitures still owed", multiprocess_mode="max")
except Exception:  # pragma: no cover
    FORFEITS_TOTAL = FORFEITS_OWED = None


class ForfeitureRetry(BackgroundWorker):
    worker_id = "forfeiture_retry"
    leader_key = "forfeiture_retry"
    interval_sec = int(os.getenv("FORFEITURE_RETRY_INTERVAL_SEC", "60") or 60)
    cold_start_delay_sec = 30

    def __init__(self) -> None:
        super().__init__()
        self.batch = int(os.getenv("FORFEITURE_RETRY_BATCH", "20") or 20)
        self.max_attempts = int(os.getenv("FORFEITURE_RETRY_MAX_ATTEMPTS", "288") or 288)
        self._stats: Dict[str, Any] = {}

    def _should_run(self) -> bool:
        return retry_enabled()

    async def _cycle_once(self) -> None:
        drained = dead = retried = 0
        async with get_db_context() as db:
            now = datetime.datetime.now(datetime.timezone.utc)
            M = models.ForfeitureOwed
            rows = (await db.execute(
                select(M).where(M.done_at.is_(None), M.dead_at.is_(None), M.next_attempt_at <= now)
                .order_by(M.created_at).limit(self.batch).with_for_update(skip_locked=True)
            )).scalars().all()
            for row in rows:
                outcome = await _drain(row)
                for k, v in next_state(row.attempts, outcome, self.max_attempts,
                                       datetime.datetime.now(datetime.timezone.utc)).items():
                    setattr(row, k, v)
                if row.done_at is not None:
                    drained += 1
                    logger.info("[forfeiture-retry] drained the owed forfeiture %s (%s from %s) after %d failed attempt(s)",
                                row.id, row.amount, row.agent_did, row.attempts)
                elif row.dead_at is not None:
                    dead += 1
                    logger.error("[FORFEIT-DEAD] the owed forfeiture %s (%s from the revoked %s) after %d attempt(s): %s "
                                 "(parked in forfeitures_owed; money_verify names the stranded balance)",
                                 row.id, row.amount, row.agent_did, row.attempts, row.last_error)
                else:
                    retried += 1
            open_now = int((await db.execute(
                select(func.count()).select_from(M).where(M.done_at.is_(None), M.dead_at.is_(None))
            )).scalar() or 0)
            await db.commit()
        if FORFEITS_TOTAL is not None:
            try:
                for name, n in (("drained", drained), ("retried", retried), ("dead", dead)):
                    if n:
                        FORFEITS_TOTAL.labels(outcome=name).inc(n)
                FORFEITS_OWED.set(open_now)
            except Exception:  # noqa: BLE001
                pass
        if drained or dead or retried:
            logger.info("[forfeiture-retry] drained=%d retried=%d dead=%d open=%d", drained, retried, dead, open_now)
        self._stats = {"drained_this_cycle": drained, "retried_this_cycle": retried, "dead_this_cycle": dead,
                       "open_now": open_now}

    def _last_stats(self) -> Dict[str, Any]:
        return dict(self._stats or {})


_worker: "ForfeitureRetry | None" = None


def get_forfeiture_retry() -> ForfeitureRetry:
    global _worker
    if _worker is None:
        _worker = ForfeitureRetry()
    return _worker
