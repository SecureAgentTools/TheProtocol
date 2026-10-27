"""
AGORA settlement worker (2026-06-12).

Leader-elected drain loop for every deferred AGORA money/state transition.
All drained operations are exref-replay-idempotent on the TEG side, so a crash
at ANY point is recovered by simply running again — money is escrow-held in
the meantime (I-X3 accounts it; I-X4 alerts if we stall).

Batches per cycle (each its own try/except — one failing class never starves
the others):
  A  settle_pending_trades   escrow → seller/fee_collector/org-treasury legs
  B  sweep_funding_orders    deposit-replay + open + match for stuck buys
  B2 sweep_funding_ipo       deposit-replay + allocate-or-refund for stuck IPO buys
  C  refund_terminal_buys    residual escrow → buyer
  D  settle_ipo_purchases    escrow → org treasury (proceeds) / buyer (refund)
  E  process_dividends       pot leg + per-holder legs
  F  settle_listing_fees     parked listing fees → fee_collector
  G  expire_ttl_orders       TTL'd resting orders → expired (+share unlock)

Self-gated on EXCHANGE_ENABLED (canary_runner pattern): the worker starts
everywhere the image runs but sleeps unless the venue is enabled.
"""
import asyncio
import logging
import os
import time
from typing import Optional, Tuple

from ..core.exchange_metrics import agora_set_settlement_lag
from ..database import get_db_context

logger = logging.getLogger(__name__)

CYCLE_SEC = int(os.getenv("EXCHANGE_SETTLE_CYCLE_SEC", "2"))
IDLE_CYCLE_SEC = int(os.getenv("EXCHANGE_SETTLE_IDLE_SEC", "10"))
# §settlement-resilience (2026-06-13): a cycle must finish well inside the 30s
# leader lease (leader.py LOCK_TTL) so it can renew at the loop top BEFORE the
# lease expires — otherwise the lease lapses mid-batch, a second worker acquires
# and runs an OVERLAPPING batch, and both pile onto the single escrow hot row →
# TEG 502 convoy → throughput collapse (the frame-b stall, 2026-06-13). The
# budget + the short per-leg mover timeout keep a cycle bounded. On a failure
# storm (TEG convoyed) the worker BACKS OFF instead of re-hammering.
CYCLE_BUDGET_SEC = float(os.getenv("EXCHANGE_SETTLE_CYCLE_BUDGET_SEC", "12"))
# §FESUITE (2026-10-09): the trades batch may take this share of a cycle's budget; the rest is kept for the lighter
# batches. With the whole budget as the trades deadline, a steady flow of trades filled every cycle (on sbx-beta about
# 4 s per trade, two or three escrow moves of 1.2-2.2 s each) and every lighter batch was skipped until a quiet cycle:
# a cancelled buy's escrow residue came back one to three minutes late (the console suite's lifecycle 22, red on V0588
# with 1.78 still held after 30 s), and repatriation, TTL expiry and armed stops waited the same way. Clamped to
# [0.1, 1.0]; 1.0 restores the old behaviour.
TRADES_BUDGET_SHARE = min(max(float(os.getenv("EXCHANGE_SETTLE_TRADES_SHARE", "0.6")), 0.1), 1.0)
FAILURE_BACKOFF_N = int(os.getenv("EXCHANGE_SETTLE_FAILURE_BACKOFF_N", "8"))
BACKOFF_SEC = float(os.getenv("EXCHANGE_SETTLE_BACKOFF_SEC", "20"))
ENABLED = os.getenv("EXCHANGE_ENABLED", "false").lower() == "true"
# §V0064 metrics: invariant gauges (agora_escrow_balance / agora_invariant_delta)
# refresh on this period — compute_invariants is a multi-query + TEG-call pass,
# too heavy for every 2s drain cycle.
INVARIANT_REFRESH_SEC = int(os.getenv("EXCHANGE_METRICS_INVARIANT_SEC", "60"))


class ExchangeSettlementWorker:
    def __init__(self) -> None:
        self.running = False
        self.task: Optional[asyncio.Task] = None
        self._last_invariant_ts = 0.0

    async def run_cycle(self) -> Tuple[int, int]:
        """Returns (total ops, settle failures) — failures drive the backoff.

        The hot/high-volume `trades` batch is deadline-bounded so the cycle
        can't outlive the leader lease; the lighter batches run after and are
        budget-checked (skipped once the deadline passes — they settle next
        cycle, all exref-idempotent). The trades batch stops at its SHARE of the
        budget (TRADES_BUDGET_SHARE), so the lighter batches get the rest of every
        cycle instead of only the quiet ones."""
        from ..services import exchange_service as svc
        from ..services import exchange_passport as passport

        total = 0
        failures = 0
        start = time.monotonic()
        deadline = start + CYCLE_BUDGET_SEC
        trades_deadline = start + CYCLE_BUDGET_SEC * TRADES_BUDGET_SHARE
        async with get_db_context() as db:
            # A — trades (the bottleneck): bounded + failure-counted
            try:
                done, failed = await svc.settle_pending_trades(db, deadline=trades_deadline)
                failures += failed
                if done:
                    logger.info(f"[AGORA-settle] trades: {done} ops ({failed} failed)")
                    total += done
            except Exception as e:
                logger.error(f"[AGORA-settle] batch trades errored: {e}", exc_info=True)
                try:
                    await db.rollback()
                except Exception:
                    pass
            # B..I — lighter batches; stop starting new ones past the budget
            for name, fn in (
                ("funding", svc.sweep_funding_orders),
                ("ipo_funding", svc.sweep_funding_ipo),  # §2026-07-02 heal IPO rows stuck in 'funding' (deposit landed, allocate died) — exref replay-idempotent
                ("refunds", svc.refund_terminal_buys),
                ("ipo", svc.settle_ipo_purchases),
                ("dividends", svc.process_dividends),
                ("listing_fees", svc.settle_listing_fees),
                ("ttl", svc.expire_ttl_orders),
                ("stale_sweep", svc.expire_stale_orders),  # §2026-06-24 force-expire stale (incl GTC/passport) resting orders → refund_terminal_buys; DB-flag gated, default OFF
                ("campaign_step", svc.step_active_campaign),  # §2026-06-25 Director Campaign Engine v1 — drive demand_director from the active campaign; no-op when none active
                ("peg_keeper", svc.run_peg_keeper),  # §2026-06-25 adaptive equity peg-keeper — throttled (interval_sec), reg-a-only (env), DB-flag gated, defers to campaigns
                ("passport_funding", lambda d: passport.sweep_foreign_funding(d, deadline=deadline)),
                # §2026-06-17: cancel permanently-unfunded passport 'funding' orders (cross-frame
                # deposit never landed) AFTER the sweep above opens any genuinely-funded ones. Δ-neutral
                # (status→cancelled + escrow_refunded=escrow_amount; no escrow leg). Unblocks the FIFO.
                ("passport_stale", lambda d: passport.expire_stale_funding(d, deadline=deadline)),
                ("repatriation", svc.repatriate_gateway_credits),  # batch I (§V0064 P2)
                ("repatriation_agg", svc.repatriate_gateway_credits_aggregated),  # §CHATDESK C5b fragments
                ("cb_resume", svc.resume_expired_circuit_breakers),  # §#84 time-based breaker auto-resume
                ("stop_triggers", svc.trigger_armed_stops),  # §#86 fire armed stop/stop-limit orders on cross
            ):
                if time.monotonic() > deadline:
                    break  # yield the lease; remaining batches run next cycle
                try:
                    n = await fn(db)
                    if n:
                        logger.info(f"[AGORA-settle] {name}: {n} ops")
                        total += n
                except Exception as e:
                    logger.error(f"[AGORA-settle] batch {name} errored: {e}", exc_info=True)
                    try:
                        await db.rollback()
                    except Exception:
                        pass
            await self._update_metrics(db, svc)
        return total, failures

    async def _update_metrics(self, db, svc) -> None:
        """§V0064 telemetry — never lets a metrics failure touch settlement."""
        try:
            from sqlalchemy import func as _f, select as _sel

            from ..models import ExchangeTrade

            oldest = (
                await db.execute(
                    _sel(_f.min(ExchangeTrade.created_at)).where(
                        ExchangeTrade.settle_status == "pending_settlement"
                    )
                )
            ).scalar_one_or_none()
            if oldest is not None:
                from datetime import datetime, timezone

                agora_set_settlement_lag((datetime.now(timezone.utc) - oldest).total_seconds())
            else:
                agora_set_settlement_lag(0.0)

            now = time.monotonic()
            if now - self._last_invariant_ts >= INVARIANT_REFRESH_SEC:
                self._last_invariant_ts = now
                # compute_invariants sets agora_escrow_balance + agora_invariant_delta
                await svc.compute_invariants(db)
        except Exception as e:
            logger.debug(f"[AGORA-settle] metrics update skipped: {e}")
            try:
                await db.rollback()
            except Exception:
                pass

    async def run_forever(self) -> None:
        from .leader import try_acquire_leadership

        if not ENABLED:
            logger.info("[AGORA-settle] EXCHANGE_ENABLED is false — worker dormant")
            return
        from . import vitals as _vitals
        logger.info("[AGORA-settle] settlement worker started")
        self.running = True
        await _vitals.register(
            "exchange_settlement", module=__name__, pattern="hand-rolled",
            interval_sec=CYCLE_SEC, enabled=ENABLED,
        )
        while self.running:
            try:
                if not await try_acquire_leadership("exchange_settlement"):
                    await asyncio.sleep(IDLE_CYCLE_SEC)
                    continue
                async with _vitals.cycle("exchange_settlement") as _ctx:
                    did_work, failures = await self.run_cycle()
                    _ctx.note(ops=did_work, failures=failures)
                    if failures >= FAILURE_BACKOFF_N:
                        # The worker's OWN threshold for "this cycle went badly" —
                        # the same number that triggers its backoff below. Using the
                        # worker's judgement, not a second opinion invented here.
                        _ctx.fail(f"{failures} settle failures in one cycle")
                if failures >= FAILURE_BACKOFF_N:
                    # TEG is convoyed — re-hammering the escrow hot row makes it
                    # worse. Back off so the lock queue drains and the lease can
                    # change hands cleanly instead of overlapping.
                    logger.warning(
                        f"[AGORA-settle] {failures} settle failures this cycle — "
                        f"backing off {BACKOFF_SEC}s (TEG convoy relief)"
                    )
                    await asyncio.sleep(BACKOFF_SEC)
                else:
                    await asyncio.sleep(CYCLE_SEC if did_work else IDLE_CYCLE_SEC)
            except asyncio.CancelledError:
                logger.info("[AGORA-settle] cancelled")
                break
            except Exception as e:
                logger.error(f"[AGORA-settle] loop error: {e}", exc_info=True)
                await asyncio.sleep(30)

    async def start(self) -> None:
        if self.task and not self.task.done():
            return
        self.task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        self.running = False
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            self.task = None
        logger.info("[AGORA-settle] stopped")


_worker: Optional[ExchangeSettlementWorker] = None


def get_exchange_settlement_worker() -> ExchangeSettlementWorker:
    global _worker
    if _worker is None:
        _worker = ExchangeSettlementWorker()
    return _worker


async def start_exchange_settlement() -> None:
    await get_exchange_settlement_worker().start()


async def stop_exchange_settlement() -> None:
    await get_exchange_settlement_worker().stop()
