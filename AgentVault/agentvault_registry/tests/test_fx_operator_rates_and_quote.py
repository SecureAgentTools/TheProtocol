"""V0651 (r) (order gwo_d47d480b9c640dd7b1902106, agentvault2-14, 2026-10-31): FX for the cloud operators.

Measured on the sandbox first (2026-10-31 18:40:40Z): sbxalphaop's canary sender sent 1 SBXA to sbx-beta's canary
receiver through /api/v1/teg/send: method fx, completed (route 2781da9d-b5c7-4669-8a80-c3970d642cbf), both ledgers'
events (TokensTransferred, CrossRegistryTransferCompleted, FxRouteSettled on sbx-alpha; the credit on sbx-beta), both
deltas 0.0 and the auditor 0.0. The transfer already worked: an operator converts at its parent frame (_fx_route_origin).
What did not:

  * the public /fx/rate and /fx/rates answered {"available": false, "reason": "fx_disabled"} on all six operators
    (amsterdam, lisbon, shenzhen, hochiminh, sbxalphaop, sbxbetaop) while their registry-config said fx_enabled: the
    proxy found the parent's public address in _FX_FRAME_PUBLIC_HOSTS, which knew only the retired frames. It is found
    now the way the transfer finds the parent (the gateway's url, else its ACTIVE peer row), port stripped.
  * the quote priced 1:1 by the operator's own fixed table: 0.995 quoted where 0.972085 arrived. An operator's quote is
    priced where its transfer converts: the ingress leg's 0.5% fee, then the parent's live spot (its public /fx/rates)
    less the pool fee, and the delivery leg's 0.5% when the receiver is on a leaf; it names the parent and the fees,
    and refuses (503) rather than quote 1:1 when the parent's rate cannot be read.

Every case fails on 48d07ecf2 (V0650), the two controls too (a frame's own quote, a node without a gateway): they
read the helper and the origin_fee field this adds.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import teg_integration as T

Q = Decimal("0.000001")
GW = "sandbox-alpha"
PEERS = [
    SimpleNamespace(name="Sandbox Alpha", base_url="https://sandbox-a.theprotocol.cloud:8443", peer_type="frame",
                    status="ACTIVE"),
    SimpleNamespace(name="Sandbox Beta", base_url="https://sandbox-b.theprotocol.cloud:8443", peer_type="frame",
                    status="ACTIVE"),
    SimpleNamespace(name="sbxbetaop", base_url="https://sbxbetaop.op.theprotocol.cloud:8443", peer_type="discovered",
                    status="ACTIVE"),
]
SPOT = Decimal("0.980588")   # SBXB per SBXA at sandbox-alpha's pool, read from inside sbxalphaop 2026-10-31 18:4xZ
RATES = {"available": True, "rate_mode": "pool", "currencies": ["SBXA", "SBXB"],
         "pairs": [{"a": "SBXA", "b": "SBXB", "a_per_b": "1.019796", "b_per_a": str(SPOT)}]}
RATE = {"available": True, "pair": "SBXA/SBXB", "rate_mode": "pool", "local_currency": "SBXA", "peer_currency": "SBXB",
        "local_per_peer": "1.019796", "peer_per_local": str(SPOT)}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _route(fn):
    return getattr(fn, "__wrapped__", fn)


class _DB:
    async def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(PEERS)))


@pytest.fixture
def operator(monkeypatch):
    """sbxalphaop's FX env as measured: no booth, the route engine on, the parent's identity and no URL."""
    for k in ("FX_ENABLED", "FX_ROUTE_GATEWAY_URL", "FX_RATE_PROXY_URL", "FX_RATE_MODE"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("FX_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_REGISTRY_ID", GW)
    monkeypatch.setenv("FX_ROUTE_GATEWAY_ROUTER_DID", "did:theprotocol:fx-router-sbxa")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_TEG_ID", "teg-layer-sandbox-alpha")
    monkeypatch.setitem(T._FX_RATE_CACHE, "data", None)
    monkeypatch.setitem(T._FX_RATES_CACHE, "data", None)
    getattr(T, "_FX_GATEWAY_SPOT_CACHE", {}).clear()
    state = {"fetched": [], "fail": False}

    class _Client:
        def __init__(self, *_a, **_k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_a):
            return False

        async def get(self, url):
            state["fetched"].append(url)
            if state["fail"]:
                raise T.httpx.ConnectError("connection refused")
            body = RATES if url.endswith("/fx/rates") else RATE
            return SimpleNamespace(status_code=200, json=lambda: body)

    monkeypatch.setattr(T.httpx, "AsyncClient", _Client)
    return state


def test_the_parent_is_found_the_way_the_transfer_finds_it(operator, monkeypatch):
    assert _run(T._fx_gateway_public_origin(_DB())) == "https://sandbox-a.theprotocol.cloud"
    monkeypatch.setenv("FX_ROUTE_GATEWAY_URL", "https://gw.example.test:8443")
    assert _run(T._fx_gateway_public_origin(_DB())) == "https://gw.example.test", "the gateway's url, port stripped"
    monkeypatch.setenv("FX_RATE_PROXY_URL", "https://rates.example.test/")
    assert _run(T._fx_gateway_public_origin(_DB())) == "https://rates.example.test", "an explicit proxy wins"


def test_control_a_node_without_a_gateway_has_no_parent(operator, monkeypatch):
    monkeypatch.delenv("FX_ROUTE_GATEWAY_REGISTRY_ID", raising=False)
    monkeypatch.delenv("FX_ROUTE_GATEWAY_ROUTER_DID", raising=False)
    assert _run(T._fx_gateway_public_origin(_DB())) == ""


def test_an_operator_answers_its_parents_public_rate(operator):
    out = _run(_route(T.fx_rate_public)(request=None, db=_DB()))
    assert out.get("available") is True and out.get("peer_per_local") == str(SPOT), out
    assert operator["fetched"] == ["https://sandbox-a.theprotocol.cloud/api/v1/teg/fx/rate"]


def test_an_operator_answers_its_parents_public_rates(operator):
    out = _run(_route(T.fx_rates_public)(request=None, db=_DB()))
    assert out.get("available") is True and out.get("pairs"), out
    assert operator["fetched"] == ["https://sandbox-a.theprotocol.cloud/api/v1/teg/fx/rates"]


def _quote(monkeypatch, home):
    import agentvault_registry.services.jurisdiction as juris

    async def _no_jurisdiction(*_a, **_k):
        return None

    async def _home(_db, _did):
        return f"teg-layer-{home}", home

    async def _ccy(_db, target_peer=None):
        return "SBXB"

    monkeypatch.setattr(juris, "check_jurisdiction", _no_jurisdiction)
    monkeypatch.setattr(T, "_resolve_receiver_registry", _home)
    monkeypatch.setattr(T, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(T, "_local_frame_currency", lambda: "SBXA")
    monkeypatch.setattr(T, "_fx_enforce_caps", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_fx_fee_rate", lambda: Decimal("0.005"))
    return _run(_route(T.fx_quote)(req=T.FxQuoteRequest(receiver_did="did:theprotocol:rx", amount="1"),
                                   request=None, current_agent=SimpleNamespace(did="did:theprotocol:tx"), db=_DB()))


def _expected_net():
    origin_fee = (Decimal("1") * Decimal("0.5") / Decimal("100")).quantize(Q)
    gross = ((Decimal("1") - origin_fee) * SPOT).quantize(Q)
    return origin_fee, gross, gross - (gross * Decimal("0.005")).quantize(Q)


def test_an_operators_quote_is_priced_where_its_transfer_converts(operator, monkeypatch):
    out = _quote(monkeypatch, "sandbox-beta")
    origin_fee, gross, net = _expected_net()
    assert out.rate_mode == "gateway_spot" and Decimal(out.rate) == SPOT
    assert out.reserve_frame == GW and Decimal(out.origin_fee) == origin_fee
    assert Decimal(out.amount_out_gross) == gross and Decimal(out.amount_out) == net
    assert out.delivery_fee is None, "the receiver is on a frame: no delivery leg"
    assert Decimal(out.amount_out) < Decimal("0.98"), "the 1:1 quote said 0.995; 0.972085 arrived"


def test_a_leaf_receiver_pays_the_delivery_leg_too(operator, monkeypatch):
    out = _quote(monkeypatch, "sbxbetaop")
    _origin_fee, _gross, net = _expected_net()
    fee = (net * Decimal("0.5") / Decimal("100")).quantize(Q)
    assert Decimal(out.delivery_fee) == fee > 0 and Decimal(out.amount_out) == net - fee
    assert out.reserve_frame == GW


def test_no_quote_rather_than_a_wrong_one_when_the_parent_cannot_be_read(operator, monkeypatch):
    operator["fail"] = True
    with pytest.raises(T.HTTPException) as e:
        _quote(monkeypatch, "sandbox-beta")
    assert e.value.status_code == 503 and "could not be read" in str(e.value.detail)


def test_control_a_frame_prices_with_its_own_booth(operator, monkeypatch):
    monkeypatch.setattr(T, "_fx_enabled", lambda: True)
    monkeypatch.setattr(T, "_fx_leaf_gateway", lambda *_a, **_k: None)
    monkeypatch.setenv("FX_RATE_MODE", "fixed")
    out = _quote(monkeypatch, "sandbox-beta")
    assert out.rate_mode == "fixed" and out.origin_fee is None and operator["fetched"] == []
