"""§REPATLANE-4 (V0606; his word 2026-10-12: "fee back after refund"): a payment the FX route's gateway returned, having
reached nobody, costs its payer nothing. The round trip's two cross-TEG fees (the ingress's and the refund leg's, each
0.5% where the money landed) go back to the payer from the payer's home frame's fee collector, through the TEG's
fee-free distribute under the route's own Idempotency-Key.

Measured before the fix (drill 3 on V0603, 2026-10-12 14:27Z): route 6fd9b396 returned 0.5 SBXB and the payer got
0.495012 back (the ingress fee 0.0025 at sbx-beta, the refund leg's 0.002488 at sbxbetaop): 0.004988 short.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services import payout_outcome as po


def test_the_round_trip_fees_are_the_two_the_ledger_took():
    # drill 3, read on the ledgers: 0.5 in, 0.4975 at the gateway, 0.495012 back
    assert ti._cross_teg_fee("0.5") == Decimal("0.0025")
    assert ti._cross_teg_fee("0.4975") == Decimal("0.002488")
    assert ti._fx_route_round_trip_fees("0.5", "0.4975") == Decimal("0.004988")
    # the sweep of 2026-10-12: an ingress of 20.1394 credited 20.038703, sent back
    assert ti._fx_route_round_trip_fees("20.1394", "20.038703") == Decimal("0.200891")
    # no ingress fee (a credited amount equal to the gross) leaves the refund leg's alone
    assert ti._fx_route_round_trip_fees("10", "10") == ti._cross_teg_fee("10")


def _origin(monkeypatch, onward, ingress=(True, None, "1.990000", "tx-ingress")):
    from tests.test_payout_outcome import _origin_route
    fee_backs: list = []
    e = _origin_route(monkeypatch, onward, ingress=ingress, fee_backs=fee_backs)
    return e, fee_backs


@pytest.mark.parametrize("detail,status", [
    (f"{ti.FX_LEDGER_AHEAD_NOTE} {ti._FX_COMPENSATED_MARK} {po.NOT_DELIVERED}", 503),
    (f"FX route local egress failed: TEG 402: Insufficient balance {ti._FX_COMPENSATED_MARK} {po.NOT_DELIVERED}", 409),
])
def test_a_returned_payment_that_reached_nobody_gives_its_fees_back(monkeypatch, detail, status):
    onward = {"status": "error", "http_status": 409, "compensated": True, "not_delivered": True, "detail": detail}
    e, fee_backs = _origin(monkeypatch, onward)
    assert e.status_code == status
    (rid, payer, fees), = fee_backs
    assert payer == "did:theprotocol:agora-gateway-sbxalphaop-sbxa"
    # the ingress of 2.0 credited 1.99 at the gateway, which sent 1.99 back: 0.01 + 0.00995
    assert fees == Decimal("2.0") - Decimal("1.990000") + ti._cross_teg_fee("1.990000") == Decimal("0.019950")
    assert rid and rid in e.detail if status == 409 else True


@pytest.mark.parametrize("onward", [
    # an older gateway refunded after an egress that may have paid: not proof the payment reached nobody (the lane holds)
    {"status": "error", "http_status": 409, "compensated": True,
     "detail": f"FX route local egress failed: timed out {ti._FX_COMPENSATED_MARK} {po.OUTCOME_UNKNOWN}"},
    # stranded: nothing came back
    {"status": "error", "http_status": 409, "compensated": False, "detail": "FX route core swap (outcome not known)"},
    None,
])
def test_no_fee_goes_back_unless_the_gateway_returned_a_payment_that_reached_nobody(monkeypatch, onward):
    e, fee_backs = _origin(monkeypatch, onward)
    assert isinstance(e, HTTPException) and fee_backs == []


class _Teg:
    """The TEG's fee-collector distribute: answers from a script (a status, (status, body) or an exception per call)."""

    def __init__(self, script):
        self.script, self.calls = list(script), []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, dict(json or {}), dict(headers or {})))
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        code, body = step if isinstance(step, tuple) else (step, {"transaction_id": "tx-fee"} if step == 200 else {"detail": "x"})
        return httpx.Response(code, json=body)


def _fee_back(monkeypatch, script, fees="0.004988"):
    monkeypatch.setenv("FX_LEG_RESOLVE_DELAYS", "0,0,0")
    teg = _Teg(script)
    monkeypatch.setattr(ti, "_get_teg_client", lambda: teg)
    out = asyncio.run(ti._fx_route_fee_back("rid-1", "did:theprotocol:payer", Decimal(fees)))
    return out, teg


def test_the_fee_back_is_the_tegs_fee_free_distribute_under_the_routes_own_key(monkeypatch):
    out, teg = _fee_back(monkeypatch, [200])
    assert out == "tx-fee"
    (url, body, headers), = teg.calls
    assert url.endswith("/api/v1/admin/fee-collector/distribute")
    assert body == {"target_agent_id": "did:theprotocol:payer", "amount": "0.004988", "reason": "route_refund_fee",
                    "reference_id": "fee-back:route-rid-1"}
    assert headers["Idempotency-Key"] == "fxroute:rid-1:fee-back"


@pytest.mark.parametrize("script,want,calls", [
    ([httpx.ReadTimeout("15 s"), 200], "tx-fee", 2),          # its answer lost: asked again, under the same key
    ([503, (409, {"detail": "in flight"}), 200], "tx-fee", 3),
    ([(400, {"detail": "Insufficient fee_collector balance"})], None, 1),   # a refusal moved nothing: final
    ([500, 500, 500, 500], None, 4),                          # still not known after the replays: logged, not repeated
])
def test_the_fee_back_asks_again_until_it_is_known(monkeypatch, script, want, calls):
    out, teg = _fee_back(monkeypatch, script)
    assert out == want and len(teg.calls) == calls
    assert {h["Idempotency-Key"] for _, _, h in teg.calls} == {"fxroute:rid-1:fee-back"}


def test_no_fee_no_call(monkeypatch):
    out, teg = _fee_back(monkeypatch, [], fees="0")
    assert out is None and teg.calls == []
