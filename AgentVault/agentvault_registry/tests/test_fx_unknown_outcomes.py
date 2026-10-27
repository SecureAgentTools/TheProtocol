"""§REPATLANE-2 (V0603): a parked FX route whose paying leg's outcome is not known is never refunded on its own.

The booth (`_fx_cross_currency_swap`) and the route hop (`_fx_route_hop_execute_inner`) used to refund the payer after
an answer that did not prove the paying leg never ran: a read timeout, a 5xx or a 409 "in flight" after the credit or
the egress may have committed. A refund then pays twice (the receiver holds the payment and the payer holds it back).
Since V0603 such a leg is asked again under its own idempotency key until its outcome is known, and a route whose
outcome stays unknown is parked HELD: phase `swap_unknown` (a swap: it waits for a ledger read) or `egress_unknown` (a
local egress: the keeper finishes it under the same key) or `egress_2pc_unknown` (a two-phase egress to a leaf
operator, which is not asked again: it holds for a read of its 2PC transfer, and while it does, the far keeper does not
re-deliver the route; tests/test_fx_remote_recovery.py). These tests pin the keeper's half:

  * the dead-letter pass reads an ALLOWLIST of phases (`pre_conversion` refunded, `egress_unknown` finished forward),
    so a held swap, a far frame's parking and any phase written after this code are never refunded from here;
  * an `egress_unknown` row is asked again under `fxroute:<route>:egress-local` (the hop's own key): a 200 is the
    delivery, a refusal that proves the egress never ran returns the row to the refund path, anything else retries
    and, at the retry limit, holds for a ledger read; a row older than the TEG keeps its key (24 h, the keeper stops
    at FX_EGRESS_UNKNOWN_MAX_AGE_HOURS, default 20) or without a receiver is never asked;
  * the FX desk lists both held phases as `held` and never as locally refundable.

The router's half (the booth's and the hop's refusals, each leg's replays) is in tests/test_payout_outcome.py.
"""
from __future__ import annotations

import asyncio
import datetime
import inspect
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

ROUTER = "did:theprotocol:fx-router-sbxa"
RID = "4a8c2f1e-7b3d-4e5f-9a1b-2c3d4e5f6a7b"


class _Res:
    def __init__(self, rows=None, one=None):
        self._rows, self._one = rows or [], one

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def scalar_one_or_none(self):
        return self._one


class _DB:
    """The dead-letter pass's two reads: the pending rows, then the frame's @fx_router. Keeps the statements."""

    def __init__(self, rows):
        self._answers = [_Res(rows=rows), _Res(one=SimpleNamespace(id=9, did=ROUTER))]
        self.statements, self.commits = [], 0

    async def execute(self, stmt, params=None):
        self.statements.append(stmt)
        return self._answers.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _row(phase="egress_unknown", *, age_h=0.1, receiver="did:theprotocol:trader-1", retries=0, amount="1.990000"):
    now = datetime.datetime.now(datetime.timezone.utc)
    return SimpleNamespace(route_id=RID, origin_did="did:theprotocol:agora-gateway-sbxalphaop-sbxa",
                           origin_teg_id="teg-sbxalphaop", origin_registry_id="registry-sbxalphaop",
                           amount=Decimal(amount), currency="SBXA", parked_at_did=ROUTER, phase=phase,
                           status="pending", retries=retries, last_error=None, resolution_tx=None, resolved_at=None,
                           receiver_did=receiver, created_at=now - datetime.timedelta(hours=age_h))


def _drive(monkeypatch, row, egress, *, max_retries=8):
    """One dead-letter pass over `row`, the local egress answering `egress` (ok, err, credited, tx). Returns the pass's
    stats, the egress calls, the refund legs attempted and the deliveries recorded."""
    from agentvault_registry.background_tasks import fx_router_keeper as fk
    from agentvault_registry.routers import teg_integration as ti
    seen = SimpleNamespace(egress=[], refunds=[], deliveries=[], topups=[])

    async def _egress(db, router_agent, router_did, receiver_did, amount, route_id):
        seen.egress.append((router_did, receiver_did, amount, route_id))
        return egress

    async def _two_pc(db, **kw):
        seen.refunds.append(kw)
        return True, None, kw.get("amount"), "tx-refund"

    async def _delivery(db, **kw):
        seen.deliveries.append(kw)

    async def _resolve(db, did):
        return "teg-sbxalphaop", "registry-sbxalphaop"

    async def _peer(db, rid):
        return SimpleNamespace(trust_domain="sbxalphaop")

    async def _ccy(db, target_peer=None, trust_domain=None):
        return "SBXA"

    async def _distribute(idem, target_did, amount, reference_id, reason="route_refund_fee"):
        seen.topups.append((idem, target_did, amount))
        return "tx-fees", False, ""
    monkeypatch.setattr(ti, "_fee_collector_distribute", _distribute)
    monkeypatch.setattr(ti, "_fx_route_local_egress", _egress)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_record_fx_delivery", _delivery)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setenv("FX_ROUTER_DID", ROUTER)
    monkeypatch.delenv("FX_EGRESS_UNKNOWN_MAX_AGE_HOURS", raising=False)
    db = _DB([row])
    out = asyncio.run(fk.FxRouterKeeper()._process_dead_letters(db, SimpleNamespace(dead_letter_max_retries=max_retries)))
    return out, seen, db


def _unknown(text="ReadTimeout: 15 s (outcome not known)"):
    from agentvault_registry.routers import teg_integration as ti
    return ti._LegError(text, nothing_moved=False)


def _never_ran(text="TEG 402: Insufficient balance"):
    from agentvault_registry.routers import teg_integration as ti
    return ti._LegError(text, nothing_moved=True)


# ── the pass reads an allowlist of phases ───────────────────────────────────────────────────────────────────────────

def test_the_dead_letter_pass_reads_only_the_phases_it_can_act_on(monkeypatch):
    _out, _seen, db = _drive(monkeypatch, _row(), (True, None, "1.99", "tx-1"))
    sql = str(db.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "fx_route_dead_letters.phase IN ('pre_conversion', 'egress_unknown')" in sql, sql
    assert "NOT IN" not in sql, "a deny-list refunds every phase it does not name, held ones included"


# ── an egress whose outcome was not known is finished under its own key ─────────────────────────────────────────────

def test_a_held_egress_that_lands_now_or_landed_then_is_delivered_and_never_refunded(monkeypatch):
    row = _row()
    out, seen, db = _drive(monkeypatch, row, (True, None, "1.99", "tx-egress"))
    assert seen.egress == [(ROUTER, "did:theprotocol:trader-1", "1.990000", RID)], seen.egress
    assert seen.refunds == [], "a delivered route is never refunded"
    assert [d["kind"] for d in seen.deliveries] == ["egress-local"] and seen.deliveries[0]["tx_id"] == "tx-egress"
    assert (row.status, row.resolution_tx, row.last_error) == ("delivered", "tx-egress", None)
    assert row.resolved_at is not None and out["delivered"] == 1 and db.commits >= 1


def test_a_held_egress_the_teg_proves_never_ran_goes_back_to_the_refund_path(monkeypatch):
    row = _row()
    out, seen, _db = _drive(monkeypatch, row, (False, _never_ran(), None, None))
    assert seen.refunds == [], "this pass only reclassifies: the refund runs on the next pass, through its own path"
    assert (row.phase, row.status) == ("pre_conversion", "pending")
    assert "provably never ran" in row.last_error and out["delivered"] == 0


@pytest.mark.parametrize("err", [_unknown, lambda: "TEG 504: gateway timeout (an error nobody classified)"])
def test_a_held_egress_still_not_known_waits_and_is_never_refunded(monkeypatch, err):
    row = _row(retries=2)
    out, seen, _db = _drive(monkeypatch, row, (False, err(), None, None))
    assert seen.refunds == [] and seen.deliveries == []
    assert (row.phase, row.status, row.retries) == ("egress_unknown", "pending", 3)
    assert row.last_error and out["failed"] == 0


def test_at_the_retry_limit_a_held_egress_holds_for_a_ledger_read(monkeypatch):
    row = _row(retries=7)
    out, seen, _db = _drive(monkeypatch, row, (False, _unknown(), None, None), max_retries=8)
    assert seen.refunds == []
    assert (row.phase, row.status, row.retries) == ("egress_unknown", "failed", 8) and out["failed"] == 1


@pytest.mark.parametrize("row,why", [
    (_row(age_h=21.0), "older than 20 h"),
    (_row(receiver=None), "without a receiver"),
])
def test_a_held_egress_past_the_keys_life_or_without_a_receiver_is_never_asked(monkeypatch, row, why):
    out, seen, _db = _drive(monkeypatch, row, (True, None, "1.99", "tx-would-pay"))
    assert seen.egress == [], "past the TEG's 24 h key a replay could pay a second time"
    assert seen.refunds == [] and row.status == "failed" and why in row.last_error
    assert f"fxroute:{RID}:egress-local" in row.last_error and out["failed"] == 1


def test_the_age_limit_is_tunable(monkeypatch):
    row = _row(age_h=21.0)
    monkeypatch.setenv("FX_EGRESS_UNKNOWN_MAX_AGE_HOURS", "22")
    from agentvault_registry.background_tasks import fx_router_keeper as fk
    from agentvault_registry.routers import teg_integration as ti
    calls = []

    async def _egress(db, *a):
        calls.append(a)
        return True, None, "1.99", "tx"

    async def _delivery(db, **kw):
        pass
    monkeypatch.setattr(ti, "_fx_route_local_egress", _egress)
    monkeypatch.setattr(ti, "_record_fx_delivery", _delivery)
    out = asyncio.run(fk.FxRouterKeeper()._finish_unknown_egress(_DB([]), row, SimpleNamespace(id=9), ROUTER, 8))
    assert out == "delivered" and len(calls) == 1


def test_control_a_pre_conversion_row_is_still_refunded(monkeypatch):
    from agentvault_registry.routers import teg_integration as ti
    row = _row(phase="pre_conversion")
    out, seen, _db = _drive(monkeypatch, row, (True, None, "1.99", "tx-never"))
    assert seen.egress == [], "a refund row is not delivered forward"
    assert len(seen.refunds) == 1 and seen.refunds[0]["receiver_did"] == row.origin_did
    assert row.status == "refunded" and out["refunded"] == 1
    # §REPATLANE-6 (V0606): made whole, its fees topped up first (tests/test_fx_dead_letter_refund_whole.py)
    send, top_up = ti._fx_dead_letter_refund_amounts(row.amount)
    assert seen.refunds[0]["amount"] == str(send) and seen.topups == [(f"fxroute:{RID}:dead-letter-fees", ROUTER, top_up)]


# ── the FX desk ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("phase,refundable,held", [
    ("pre_conversion", True, False),
    ("post_conversion_remote", False, False),
    ("egress_unknown", False, True),
    ("swap_unknown", False, True),
    ("egress_2pc_unknown", False, True),
    ("redelivery_unknown", False, True),
    ("refund_unknown", False, True),
])
def test_the_fx_desk_lists_a_held_row_as_held_and_never_as_refundable_here(phase, refundable, held):
    from agentvault_registry.routers import teg_integration as ti
    row = _row(phase=phase)
    row.id = "dl-1"

    class _ListDB:
        async def execute(self, stmt, params=None):
            return _Res(rows=[row])
    listing = inspect.unwrap(ti.fx_dead_letters_list)  # the route's own body, under its rate limit's wrapper
    out = asyncio.run(listing(request=None, status_filter="pending", limit=50, db=_ListDB(), admin=None))
    (r,) = out["rows"]
    assert (r["locally_refundable"], r["held"]) == (refundable, held)
    assert set(ti.FX_HELD_PHASES) == {"swap_unknown", "egress_unknown", "egress_2pc_unknown", "redelivery_unknown",
                                      "refund_unknown"}
