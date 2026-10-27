"""§FESUITE (2026-10-09) — a steady flow of trades must not starve the AGORA settlement worker's lighter batches.

The console suite's lifecycle 22 went red on the V0588 sandbox: a cancelled buy order's escrow residue (1.78) was still
held 30 s after the cancel. The refund rides `refund_terminal_buys`, one of the lighter batches the worker runs AFTER the
trades batch. Measured on sbx-beta: about 4 s per trade (two or three escrow moves of 1.2-2.2 s), a few trades arriving
every cycle, so the trades batch used the whole 12 s cycle budget and the lighter batches (refunds, funding sweeps, TTL
expiry, armed stops, repatriation) were skipped until a quiet cycle came: refunds ran with gaps of one to three minutes.
The worker's own docstring promises that one class never starves the others.

The fix gives the trades batch a SHARE of the budget (EXCHANGE_SETTLE_TRADES_SHARE, default 0.6) and keeps the rest for
the lighter batches. These tests drive the real `run_cycle` with a fake clock (the module's own `time` name, so the event
loop keeps the real one) and fake batches: the trades batch takes everything its deadline allows, and the refunds batch
must still run. Control: against V0588's worker (one deadline for both) `test_refunds_run_when_trades_fill_their_share`
is RED (refunds never called).
"""
from __future__ import annotations

import contextlib
import importlib

import pytest

from agentvault_registry.background_tasks import exchange_settlement as worker_mod
from agentvault_registry.services import exchange_passport as passport_mod
from agentvault_registry.services import exchange_service as svc_mod

LIGHTER = ("sweep_funding_orders", "sweep_funding_ipo", "refund_terminal_buys", "settle_ipo_purchases",
           "process_dividends", "settle_listing_fees", "expire_ttl_orders", "expire_stale_orders",
           "step_active_campaign", "run_peg_keeper", "repatriate_gateway_credits",
           "repatriate_gateway_credits_aggregated", "resume_expired_circuit_breakers", "trigger_armed_stops")


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def monotonic(self) -> float:
        return self.now


class FakeDb:
    async def rollback(self) -> None:
        return None


@contextlib.asynccontextmanager
async def _fake_db_context():
    yield FakeDb()


def _wire(monkeypatch, clock: FakeClock, trades_time: float):
    """The real cycle with fake batches; returns the list of lighter batches called and the trades deadline seen."""
    called: list[str] = []
    seen: dict = {}
    monkeypatch.setattr(worker_mod, "time", clock)
    monkeypatch.setattr(worker_mod, "get_db_context", _fake_db_context)

    async def fake_trades(db, deadline=None):
        seen["deadline"] = deadline
        # a steady flow: trades keep coming, the batch settles until its deadline lets it stop (the last trade started
        # just before the deadline and finished just after it)
        clock.now = min(clock.now + trades_time, (deadline if deadline is not None else clock.now) + 0.5)
        return 3, 0

    monkeypatch.setattr(svc_mod, "settle_pending_trades", fake_trades)

    def lighter(name):
        async def fn(db):
            called.append(name)
            clock.now += 0.1
            return 0
        return fn

    for n in LIGHTER:
        monkeypatch.setattr(svc_mod, n, lighter(n))
    monkeypatch.setattr(passport_mod, "sweep_foreign_funding", lambda d, deadline=None: lighter("passport_funding")(d))
    monkeypatch.setattr(passport_mod, "expire_stale_funding", lambda d, deadline=None: lighter("passport_stale")(d))

    async def no_metrics(self, db, svc):
        return None

    monkeypatch.setattr(worker_mod.ExchangeSettlementWorker, "_update_metrics", no_metrics)
    return called, seen


@pytest.mark.asyncio
async def test_refunds_run_when_trades_fill_their_share(monkeypatch):
    clock = FakeClock()
    called, seen = _wire(monkeypatch, clock, trades_time=60.0)   # more trades than any budget holds
    total, failures = await worker_mod.ExchangeSettlementWorker().run_cycle()
    assert (total, failures) == (3, 0)
    assert "refund_terminal_buys" in called, (
        f"the trades batch filled the cycle and the refunds batch never ran (lighter batches called: {called})")
    # every lighter batch had its turn in this cycle, in the worker's order
    assert called[:3] == ["sweep_funding_orders", "sweep_funding_ipo", "refund_terminal_buys"]
    assert "trigger_armed_stops" in called


@pytest.mark.asyncio
async def test_trades_stop_at_their_share_of_the_budget(monkeypatch):
    clock = FakeClock(start=500.0)
    _, seen = _wire(monkeypatch, clock, trades_time=60.0)
    await worker_mod.ExchangeSettlementWorker().run_cycle()
    expected = 500.0 + worker_mod.CYCLE_BUDGET_SEC * worker_mod.TRADES_BUDGET_SHARE
    assert seen["deadline"] == pytest.approx(expected), (seen, expected)
    assert seen["deadline"] < 500.0 + worker_mod.CYCLE_BUDGET_SEC, "the trades batch must not get the whole budget"


@pytest.mark.asyncio
async def test_a_quiet_cycle_still_runs_everything(monkeypatch):
    clock = FakeClock()
    called, _ = _wire(monkeypatch, clock, trades_time=0.5)       # few trades: the batch ends early
    await worker_mod.ExchangeSettlementWorker().run_cycle()
    assert "refund_terminal_buys" in called and "trigger_armed_stops" in called


def test_the_share_is_clamped(monkeypatch):
    try:
        for raw, want in (("0", 0.1), ("0.05", 0.1), ("0.6", 0.6), ("1", 1.0), ("5", 1.0)):
            monkeypatch.setenv("EXCHANGE_SETTLE_TRADES_SHARE", raw)
            assert importlib.reload(worker_mod).TRADES_BUDGET_SHARE == pytest.approx(want), raw
    finally:
        monkeypatch.delenv("EXCHANGE_SETTLE_TRADES_SHARE", raising=False)
        importlib.reload(worker_mod)
