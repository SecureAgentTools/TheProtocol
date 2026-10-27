"""§LEDGERGATE (V0598, 2026-10-11) — the payer of owed genesis grants (`genesis_grants_owed`, migration 0188).

Why it exists: onboarding's `mint_genesis_grant` turned any TEG failure into `initial_funding_status: failed` and nothing
retried it, so a developer's first grant was lost for good whenever the TEG could not pay at that moment. The ledger gate
(the TEG refusing new value movements while its ledger cannot record them) makes that moment an ordinary outage. The
creation now records the grant as owed and answers `deferred`; this worker pays it once the ledger records again.

Leader-elected through `_worker_base.BackgroundWorker` (vitals stamped by the base every cycle). Each cycle takes up to
`batch` due rows FOR UPDATE SKIP LOCKED and pays each through the same reward waterfall the creation uses, with the
SAME idempotency key (`genesis-{agent_did}`): a payment that landed but whose answer was lost replays the TEG's cached
result instead of paying twice, and the waterfall syncs the registry's cached balance from the TEG. A completed payment
closes the row (`granted_at`, `funding_status` completed); an exhausted waterfall closes it too (`partial`: the TEG
committed what it could, by design, and the shortfall is the treasury's, not the ledger's). A failure bumps `attempts`
with a growing wait (30 s, 1 min, 2 min, 5 min, then 10 min each); past the attempt budget the row is parked with
`dead_at` and logged `[GENESIS-DEAD]` with the agent and the last error, for a grant by hand (FLOW 4); nothing is
deleted. The 10 min ceiling keeps every retry inside the TEG's 24 h idempotency window of the attempt before it.

Env: GENESIS_GRANT_RETRY_ENABLED (default true), GENESIS_GRANT_RETRY_INTERVAL_SEC (30), GENESIS_GRANT_RETRY_BATCH (20),
GENESIS_GRANT_RETRY_MAX_ATTEMPTS (288: about two days at the ceiling).
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


def backoff_seconds(attempts: int) -> int:
    """The wait before the next attempt, by how many have failed: 30 s, 1, 2, 5, then 10 min each."""
    if attempts <= 0:
        return _BACKOFF_SEC[0]
    return _BACKOFF_SEC[min(attempts, len(_BACKOFF_SEC)) - 1]


def retry_enabled() -> bool:
    return (os.getenv("GENESIS_GRANT_RETRY_ENABLED") or "true").strip().lower() == "true"


def next_state(row_attempts: int, result: Dict[str, Any], max_attempts: int, now: datetime.datetime) -> Dict[str, Any]:
    """The pure decision of one payment attempt: what the row becomes. `result` is the waterfall's answer
    (`status` completed or exhausted, `first_transaction_id`) or {"error": "..."} when the call failed."""
    if result.get("status") in ("completed", "exhausted"):
        return {"granted_at": now, "funding_status": "completed" if result["status"] == "completed" else "partial",
                "transaction_id": str(result.get("first_transaction_id") or "unknown")[:255]}
    attempts = (row_attempts or 0) + 1
    err = str(result.get("error") or "no answer")[:500]
    if attempts >= max_attempts:
        return {"attempts": attempts, "last_error": err, "dead_at": now}
    return {"attempts": attempts, "last_error": err,
            "next_attempt_at": now + datetime.timedelta(seconds=backoff_seconds(attempts))}


try:
    from prometheus_client import Counter as _GC, Gauge as _GG

    GRANTS_PAID_TOTAL = _GC("registry_genesis_grants_owed_paid_total", "Owed genesis grants paid by the retry worker")
    GRANTS_DEAD_TOTAL = _GC("registry_genesis_grants_owed_dead_total", "Owed genesis grants parked past their attempt budget (grant by hand)")
    GRANTS_PENDING = _GG("registry_genesis_grants_owed_pending", "Genesis grants still owed", multiprocess_mode="max")
except Exception:  # pragma: no cover — a second registration in a test process, or no prometheus
    GRANTS_PAID_TOTAL = GRANTS_DEAD_TOTAL = GRANTS_PENDING = None


async def _pay(db, row) -> Dict[str, Any]:
    """One payment through the creation's own rail and key; a failure becomes {"error": ...}, never an exception."""
    from agentvault_registry.services.reward_funding import fund_reward_via_waterfall
    try:
        return await fund_reward_via_waterfall(
            db, target_agent_did=row.agent_did, amount=str(row.amount), reason="genesis_grant",
            reference_id=f"onboard-{row.agent_did}", idempotency_key=f"genesis-{row.agent_did}",
        )
    except Exception as e:  # noqa: BLE001 — TEGClientError (the gate's refusal among them) and the connection class
        return {"error": f"{type(e).__name__}: {e}"}


class GenesisGrantRetry(BackgroundWorker):
    worker_id = "genesis_grant_retry"
    leader_key = "genesis_grant_retry"
    interval_sec = int(os.getenv("GENESIS_GRANT_RETRY_INTERVAL_SEC", "30") or 30)
    cold_start_delay_sec = 20

    def __init__(self) -> None:
        super().__init__()
        self.batch = int(os.getenv("GENESIS_GRANT_RETRY_BATCH", "20") or 20)
        self.max_attempts = int(os.getenv("GENESIS_GRANT_RETRY_MAX_ATTEMPTS", "288") or 288)
        self._stats: Dict[str, Any] = {}

    def _should_run(self) -> bool:
        return retry_enabled()

    async def _cycle_once(self) -> None:
        paid = dead = retried = 0
        pending = 0
        async with get_db_context() as db:
            now = datetime.datetime.now(datetime.timezone.utc)
            M = models.GenesisGrantOwed
            rows = (await db.execute(
                select(M).where(M.granted_at.is_(None), M.dead_at.is_(None), M.next_attempt_at <= now)
                .order_by(M.created_at).limit(self.batch).with_for_update(skip_locked=True)
            )).scalars().all()
            for row in rows:
                result = await _pay(db, row)
                t = datetime.datetime.now(datetime.timezone.utc)
                for k, v in next_state(row.attempts, result, self.max_attempts, t).items():
                    setattr(row, k, v)
                if row.granted_at is not None:
                    paid += 1
                    logger.info("[genesis-retry] paid the owed grant of %s (%s, tx %s) after %d failed attempt(s)",
                                row.agent_did, row.funding_status, row.transaction_id, row.attempts)
                elif row.dead_at is not None:
                    dead += 1
                    logger.error("[GENESIS-DEAD] the owed grant of %s (%s) after %d attempt(s): %s (parked in "
                                 "genesis_grants_owed; grant by hand, FLOW 4)", row.agent_did, row.amount, row.attempts,
                                 row.last_error)
                else:
                    retried += 1
            pending = int((await db.execute(
                select(func.count()).select_from(M).where(M.granted_at.is_(None), M.dead_at.is_(None))
            )).scalar() or 0)
            await db.commit()
        if GRANTS_PAID_TOTAL is not None:
            try:
                if paid:
                    GRANTS_PAID_TOTAL.inc(paid)
                if dead:
                    GRANTS_DEAD_TOTAL.inc(dead)
                GRANTS_PENDING.set(pending)
            except Exception:  # noqa: BLE001
                pass
        if paid or dead or retried:
            logger.info("[genesis-retry] paid=%d retried=%d dead=%d pending=%d", paid, retried, dead, pending)
        self._stats = {"paid_this_cycle": paid, "retried_this_cycle": retried, "dead_this_cycle": dead, "pending_now": pending}

    def _last_stats(self) -> Dict[str, Any]:
        return dict(self._stats or {})


_worker: "GenesisGrantRetry | None" = None


def get_genesis_grant_retry() -> GenesisGrantRetry:
    global _worker
    if _worker is None:
        _worker = GenesisGrantRetry()
    return _worker
