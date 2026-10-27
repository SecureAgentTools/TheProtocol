"""§LEDGERGATE (V0599, 2026-10-11) — the payer of owed fiat credits (fiat_purchases, migration 0189).

Why it exists: fiat_onramp's direct flow answers the provider's webhook 200 at once and credits the purchase in a
background task, so a credit that did not land (the TEG down, or the ledger gate refusing while the ledger cannot record)
was marked failed and only an admin replay recovered it. Now routers/fiat_onramp._credit_and_complete leaves such a
purchase OWED (status processing, failure_reason "credit_owed: <why>", credit_next_attempt_at) and this worker asks
again once it is due, through the same function, so the credit carries the purchase's own Idempotency-Key
(fiat-credit-<id>): a credit that landed but whose answer was lost replays the TEG's cached result instead of paying
twice. A completed credit finishes the purchase (the notice, the flare, the provisioning credit, FiatPurchaseSettled,
the receipt); an exhausted waterfall leaves it failed and partial for a human; past the attempt budget it is failed,
"reward_fund_failed", and logged [FIAT-CREDIT-DEAD]: the human path the forensic scanner and the stuck-funds board name.

Leader-elected through `_worker_base.BackgroundWorker`. Only the direct flow (routed = false): the routed flow has its own
reconcilers. The wait grows 30 s, 1, 2, 5, then 10 min; the 10 min ceiling keeps every retry inside the TEG's 24 h
idempotency window of the attempt before it.

Env: FIAT_CREDIT_RETRY_ENABLED (default true), FIAT_CREDIT_RETRY_INTERVAL_SEC (30), FIAT_CREDIT_RETRY_BATCH (20),
FIAT_CREDIT_MAX_ATTEMPTS (288: about two days at the ceiling).
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


def credit_backoff_seconds(attempts: int) -> int:
    """The wait before the next attempt, by how many have failed: 30 s, 1, 2, 5, then 10 min each."""
    if attempts <= 0:
        return _BACKOFF_SEC[0]
    return _BACKOFF_SEC[min(attempts, len(_BACKOFF_SEC)) - 1]


def credit_max_attempts() -> int:
    return int(os.getenv("FIAT_CREDIT_MAX_ATTEMPTS", "288") or 288)


def retry_enabled() -> bool:
    return (os.getenv("FIAT_CREDIT_RETRY_ENABLED") or "true").strip().lower() == "true"


try:
    from prometheus_client import Counter as _FC, Gauge as _FG

    CREDITS_TOTAL = _FC("registry_fiat_credits_total",
                        "Direct-flow fiat credit attempts by outcome (completed, owed, partial, dead)", ["outcome"])
    CREDITS_OWED = _FG("registry_fiat_credits_owed", "Direct-flow fiat purchases whose credit is still owed",
                       multiprocess_mode="max")
except Exception:  # pragma: no cover — a second registration in a test process, or no prometheus
    CREDITS_TOTAL = CREDITS_OWED = None


def count_credit(outcome: str) -> None:
    if CREDITS_TOTAL is not None:
        try:
            CREDITS_TOTAL.labels(outcome=outcome).inc()
        except Exception:  # noqa: BLE001
            pass


def _owed(M):
    return (M.routed.is_(False), M.status == models.FiatPurchaseStatus.PROCESSING.value,
            M.failure_reason.like("credit_owed:%"))


class FiatCreditRetry(BackgroundWorker):
    worker_id = "fiat_credit_retry"
    leader_key = "fiat_credit_retry"
    interval_sec = int(os.getenv("FIAT_CREDIT_RETRY_INTERVAL_SEC", "30") or 30)
    cold_start_delay_sec = 25

    def __init__(self) -> None:
        super().__init__()
        self.batch = int(os.getenv("FIAT_CREDIT_RETRY_BATCH", "20") or 20)
        self._stats: Dict[str, Any] = {}

    def _should_run(self) -> bool:
        return retry_enabled()

    async def _cycle_once(self) -> None:
        from agentvault_registry.routers.fiat_onramp import _credit_and_complete
        M = models.FiatPurchase
        now = datetime.datetime.now(datetime.timezone.utc)
        async with get_db_context() as db:
            due = (await db.execute(
                select(M.id, M.payment_provider, M.provider_event_id, M.provider_session_id)
                .where(*_owed(M), M.credit_next_attempt_at <= now)
                .order_by(M.credit_next_attempt_at).limit(self.batch)
            )).all()
        outcomes: Dict[str, int] = {}
        for row in due:
            try:
                st = await _credit_and_complete(row.id, provider=row.payment_provider or "stripe",
                                                event_id=row.provider_event_id, session_id=row.provider_session_id)
            except Exception as e:  # noqa: BLE001 — one purchase must not stop the others
                logger.error("[fiat-credit-retry] purchase %s: %s: %s", row.id, type(e).__name__, e)
                st = "error"
            outcomes[str(st)] = outcomes.get(str(st), 0) + 1
        async with get_db_context() as db:
            owed = int((await db.execute(select(func.count()).select_from(M).where(*_owed(M)))).scalar() or 0)
        if CREDITS_OWED is not None:
            try:
                CREDITS_OWED.set(owed)
            except Exception:  # noqa: BLE001
                pass
        if due:
            logger.info("[fiat-credit-retry] asked %d due: %s; %d still owed", len(due), outcomes, owed)
        self._stats = {"asked_this_cycle": len(due), "outcomes": outcomes, "owed_now": owed}

    def _last_stats(self) -> Dict[str, Any]:
        return dict(self._stats or {})


_worker: "FiatCreditRetry | None" = None


def get_fiat_credit_retry() -> FiatCreditRetry:
    global _worker
    if _worker is None:
        _worker = FiatCreditRetry()
    return _worker
