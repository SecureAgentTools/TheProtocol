"""§REPATLANE-6 (V0606): a payment an FX route's gateway returns LATER, from a dead letter, costs its payer nothing, and
no refund whose outcome was not known is ever sent again.

Before: the gateway's keeper refunded a pre-conversion dead letter with what its @fx_router held, the ingress leg's
credited amount, over a cross-TEG leg that took its own fee: the payer got back about 99% (drill 3 on V0603: a 0.5
payment came back as 0.495012). V0605 returns the fees when the ORIGIN learns of the refund at once (§REPATLANE-4); a
keeper's later refund has no origin there to do it. And a refund leg that timed out was refunded again on the keeper's
next pass (retries counted every failure alike), and the hop recorded every failed refund as refundable.

Now the keeper's refund sends X = _cross_teg_gross_for(G), G = _cross_teg_gross_for(held) being the payer's own payment,
after this frame's fee collector pays the router X - held under the route's own key; a refund leg (the hop's or the
keeper's) whose outcome is not known holds as `refund_unknown` for a read of the leg.
"""
from __future__ import annotations

import asyncio
import random
from decimal import Decimal
from types import SimpleNamespace

import pytest

from tests.test_fx_unknown_outcomes import RID, ROUTER, _DB, _row

D = Decimal


def _ti():
    from agentvault_registry.routers import teg_integration as ti
    return ti


# ── the arithmetic ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_drill_3s_payment_comes_back_whole():
    """Route 6fd9b396 (2026-10-12 14:27Z): 0.5 sent, the ingress credited 0.4975 at the gateway, 0.495012 came back."""
    ti = _ti()
    assert ti._cross_teg_gross_for(D("0.4975")) == D("0.5")
    send, top_up = ti._fx_dead_letter_refund_amounts(D("0.4975"))
    assert send - ti._cross_teg_fee(send) == D("0.5"), "the payer's TEG credits the whole payment"
    assert (send, top_up) == (D("0.502513"), D("0.005013"))
    assert top_up == (D("0.5") - D("0.4975")) + ti._cross_teg_fee(send), "the ingress fee and the refund leg's"


def test_the_payment_is_recovered_from_what_the_ingress_credited_whatever_its_precision():
    ti = _ti()
    rnd = random.Random(606)
    for _ in range(3000):
        places = rnd.choice([2, 6, 9, 18])
        g = D(rnd.randrange(1, 10 ** (places + 6))) / D(10 ** places)  # up to a million, with `places` decimals
        held = g - ti._cross_teg_fee(g)
        back = ti._cross_teg_gross_for(held)
        assert back - ti._cross_teg_fee(back) == held, (g, held, back)
        assert D("0") <= back - g <= D("0.000001"), "never short, at most one fee quantum over"
        send, top_up = ti._fx_dead_letter_refund_amounts(held)
        assert send - ti._cross_teg_fee(send) >= back and top_up == send - held


# ── the keeper's refund ──────────────────────────────────────────────────────────────────────────────────────────────

def _keeper(monkeypatch, row, *, topups, legs):
    """One dead-letter pass over a pre-conversion `row`: the fee collector's distribute answers `topups` in turn, the
    refund leg `legs` in turn. Returns (stats, distributes asked, legs sent)."""
    from agentvault_registry.background_tasks import fx_router_keeper as fk
    ti = _ti()
    asked, sent = [], []

    async def _distribute(idem, target_did, amount, reference_id, reason="route_refund_fee"):
        asked.append((idem, target_did, amount, reference_id))
        return topups[min(len(asked), len(topups)) - 1]

    async def _two_pc(db, **kw):
        sent.append(kw)
        return legs[min(len(sent), len(legs)) - 1]

    async def _resolve(db, did):
        return "teg-sbxalphaop", "registry-sbxalphaop"

    async def _peer(db, rid):
        return SimpleNamespace(trust_domain="sbxalphaop")

    async def _ccy(db, target_peer=None, trust_domain=None):
        return "SBXA"
    monkeypatch.setattr(ti, "_fee_collector_distribute", _distribute)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setenv("FX_ROUTER_DID", ROUTER)
    out = asyncio.run(fk.FxRouterKeeper()._process_dead_letters(_DB([row]), SimpleNamespace(dead_letter_max_retries=8)))
    return out, asked, sent


def test_the_keepers_refund_tops_up_the_fees_first_and_sends_the_whole_payment(monkeypatch):
    ti = _ti()
    row = _row(phase="pre_conversion", amount="0.4975")
    out, asked, sent = _keeper(monkeypatch, row, topups=[("tx-fees", False, "")], legs=[(True, None, "0.5", "tx-refund")])
    assert asked == [(f"fxroute:{RID}:dead-letter-fees", ROUTER, D("0.005013"), f"dead-letter-fees:route-{RID}")]
    assert [s["amount"] for s in sent] == ["0.502513"] and sent[0]["receiver_did"] == row.origin_did
    assert sent[0]["memo"] == f"fxroute:{RID}:dead-letter-refund"
    assert (row.status, row.resolution_tx, row.last_error) == ("refunded", "tx-refund", None) and out["refunded"] == 1


def test_a_top_up_not_answered_sends_nothing_this_pass_and_is_asked_again_under_its_key(monkeypatch):
    row = _row(phase="pre_conversion", amount="0.4975")
    out, asked, sent = _keeper(monkeypatch, row, topups=[(None, False, "TEG unreachable: ReadTimeout")],
                               legs=[(True, None, "0.5", "tx-refund")])
    assert sent == [], "a refund before its top-up is known could send the fees from the router's float"
    assert (row.phase, row.status, row.retries) == ("pre_conversion", "pending", 0)
    assert f"fxroute:{RID}:dead-letter-fees" in row.last_error and out["refunded"] == 0


def test_a_top_up_the_teg_refused_leaves_the_refund_as_it_was(monkeypatch):
    row = _row(phase="pre_conversion", amount="0.4975")
    out, asked, sent = _keeper(monkeypatch, row, topups=[(None, True, "TEG 400: insufficient fee collector balance")],
                               legs=[(True, None, "0.495012", "tx-refund")])
    assert [s["amount"] for s in sent] == ["0.4975"], "the money goes back without its fees"
    assert row.status == "refunded" and "its fees did not go back" in row.last_error


def test_a_refund_leg_whose_outcome_is_not_known_holds_and_is_never_sent_again(monkeypatch):
    ti = _ti()
    row = _row(phase="pre_conversion", amount="0.4975", retries=2)
    out, asked, sent = _keeper(monkeypatch, row, topups=[("tx-fees", False, "")],
                               legs=[(False, ti._LegError("2pc leg: ReadTimeout (outcome not known)"), None, None)])
    assert len(sent) == 1
    assert (row.phase, row.status, row.retries) == ("refund_unknown", "pending", 2)
    assert f"fxroute:{RID}:dead-letter-refund" in row.last_error and out["held"] == 1
    assert "refund_unknown" in ti.FX_HELD_PHASES, "the desk shows it held and the far keeper's guard reads it"


@pytest.mark.parametrize("err", [lambda ti: ti._LegError("2pc leg 402: Insufficient balance", nothing_moved=True)])
def test_a_refund_leg_that_provably_never_ran_retries_and_asks_the_same_top_up_again(monkeypatch, err):
    ti = _ti()
    row = _row(phase="pre_conversion", amount="0.4975")
    _keeper(monkeypatch, row, topups=[("tx-fees", False, "")], legs=[(False, err(ti), None, None)])
    assert (row.phase, row.status, row.retries) == ("pre_conversion", "pending", 1)
    out, asked, sent = _keeper(monkeypatch, row, topups=[("tx-fees", False, "")], legs=[(True, None, "0.5", "tx-2")])
    assert asked[0][0] == f"fxroute:{RID}:dead-letter-fees", "the second pass asks the same key: the TEG replays it"
    assert row.status == "refunded" and sent[0]["amount"] == "0.502513"


def test_an_unresolvable_origin_sends_nothing_and_retries(monkeypatch):
    from agentvault_registry.background_tasks import fx_router_keeper as fk
    ti = _ti()
    row = _row(phase="pre_conversion", amount="0.4975")
    row.origin_teg_id = None
    asked, sent = [], []

    async def _distribute(*a, **k):
        asked.append(a)
        return "tx-fees", False, ""

    async def _two_pc(db, **kw):
        sent.append(kw)
        return True, None, "x", "tx"

    async def _resolve(db, did):
        return None, None

    async def _ccy(db, target_peer=None, trust_domain=None):
        return None
    monkeypatch.setattr(ti, "_fee_collector_distribute", _distribute)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setenv("FX_ROUTER_DID", ROUTER)
    asyncio.run(fk.FxRouterKeeper()._process_dead_letters(_DB([row]), SimpleNamespace(dead_letter_max_retries=8)))
    assert asked == [] and sent == [] and (row.phase, row.retries) == ("pre_conversion", 1)


# ── the hop's own refund ─────────────────────────────────────────────────────────────────────────────────────────────

def _hop_refund(monkeypatch, *, leg=None, resolve_raises=False, leg_raises=False):
    ti = _ti()
    recorded = []

    async def _resolve(db, did):
        if resolve_raises:
            raise RuntimeError("peer table unreadable")
        return "teg-sbxalphaop", "registry-sbxalphaop"

    async def _peer(db, rid):
        return None

    async def _two_pc(db, **kw):
        if leg_raises:
            raise RuntimeError("connection reset after the commit request")
        return leg

    async def _record(db, **kw):
        recorded.append(kw)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_record_fx_dead_letter", _record)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "SBXA")
    ok = asyncio.run(ti._fx_route_refund_to_origin(None, SimpleNamespace(id=9), ROUTER, "did:theprotocol:payer",
                                                   "0.4975", RID, origin_teg_id="teg-sbxalphaop",
                                                   origin_registry_id="registry-sbxalphaop"))
    return ok, recorded


def test_the_hops_refund_outcomes(monkeypatch):
    ti = _ti()
    ok, rec = _hop_refund(monkeypatch, leg=(True, None, "0.495012", "tx"))
    assert ok is True and rec == []
    ok, rec = _hop_refund(monkeypatch, leg=(False, ti._LegError("2pc leg 402: Insufficient", nothing_moved=True), None, None))
    assert ok is False and [r["phase"] for r in rec] == ["pre_conversion"] and rec[0]["note"] is None
    ok, rec = _hop_refund(monkeypatch, leg=(False, ti._LegError("2pc leg: ReadTimeout"), None, None))
    assert ok is False and [r["phase"] for r in rec] == ["refund_unknown"]
    assert f"fxroute:{RID}:refund" in rec[0]["note"] and "(outcome not known)" in rec[0]["note"]
    ok, rec = _hop_refund(monkeypatch, leg=(False, "an error nobody classified", None, None))
    assert [r["phase"] for r in rec] == ["refund_unknown"], "an unclassified failure may have moved money"
    ok, rec = _hop_refund(monkeypatch, leg_raises=True)
    assert ok is False and [r["phase"] for r in rec] == ["refund_unknown"]
    ok, rec = _hop_refund(monkeypatch, resolve_raises=True)
    assert ok is False and [r["phase"] for r in rec] == ["pre_conversion"], "it raised before the leg was sent"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
