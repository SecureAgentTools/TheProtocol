"""§MCPTEST30 (V0528, 2026-10-01) — a receiver on a LEAF of the destination frame is quoted where the transfer pays it.

agentvault2-21's Forex lifecycle on sbx-alpha (V0526) quoted 1 SBXA to a receiver on sbxbetaop, an operator of
sbx-beta: 503 "FX pool quote: reserve read failed: Client error '404 Not Found' for url
'https://sbxbetaop.op.theprotocol.cloud:8443/api/v1/admin/fx/reserve'". The quote read the reserve of the receiver's
HOME, and a leaf operator holds none. The transfer to the same receiver works: since §pass78c it converts at the frame
that holds the SBXB reserve (GD, sandbox-beta) and delivers 1:1 to the leaf, paying the delivery leg's 0.5%
cross-registry fee (_fx_route_1to1_2pc). Two paths to the same receiver disagreed. One predicate,
`_fx_leaf_gateway`, now answers for the transfer, the quote and the pool; the quote prices GD's pool, takes the
delivery fee out of amount_out, and names both.

RED control: against V0527's tree the AST pin finds the inline predicate in cross_registry_transfer and no call in
fx_quote / fx_pool, and the quote drive reads the leaf's reserve (the stub answers 404 there).
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from decimal import Decimal
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import teg_integration as T

# the source of the module under test (the one this file imported), not a configured tree: the pin must read the
# code the drives above just ran
_SRC = pathlib.Path(T.__file__).with_suffix(".py")
GD = {"currency": "SBXB", "registry_id": "sandbox-beta", "teg_id": "teg-layer-sandbox-beta",
      "router_did": "did:theprotocol:fx-router-sbxb"}
LOCAL_TEG = "http://local-teg:8080"


def _run(coro):
    # a fresh loop of its own: asyncio.run() would leave the NEXT test file without one
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _route(fn):
    # the rate limiter's decorator sits on the route; the function under it is what this drives
    return getattr(fn, "__wrapped__", fn)


@pytest.fixture
def engine_on(monkeypatch):
    monkeypatch.setattr(T, "_fx_enabled", lambda: True)
    monkeypatch.setattr(T, "_fx_route_enabled", lambda: True)
    monkeypatch.setattr(T, "_fx_route_local_router_did", lambda: "did:theprotocol:fx-router-sbxa")
    monkeypatch.setattr(T, "_fx_route_peer_gateways", lambda: [dict(GD)])


def test_the_predicate_names_gd_only_for_a_leaf(engine_on, monkeypatch):
    assert T._fx_leaf_gateway("SBXB", "registry-sbxbetaop")["registry_id"] == "sandbox-beta"
    assert T._fx_leaf_gateway("sbxb", "sbxbetaop") is not None, "currency and slug forms are normalized"
    assert T._fx_leaf_gateway("SBXB", "registry-sandbox-beta") is None, "a receiver ON the reserve frame is direct"
    assert T._fx_leaf_gateway("SBXB", "") is None, "an unresolved home is not a leaf"
    assert T._fx_leaf_gateway("SBXC", "registry-elsewhere") is None, "no gateway settles that currency"
    monkeypatch.setattr(T, "_fx_route_enabled", lambda: False)
    assert T._fx_leaf_gateway("SBXB", "registry-sbxbetaop") is None, "the route engine off: the old direct path"


class _DB:
    async def execute(self, *_a, **_k):
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))


def _quote_with(monkeypatch, home):
    """Drive the real fx_quote for a receiver homed on `home`; return (response, the TEG bases whose reserve was read)."""
    import agentvault_registry.services.jurisdiction as juris

    async def _no_jurisdiction(*_a, **_k):
        return None

    async def _home(_db, _did):
        return f"teg-layer-{home}", f"registry-{home}"

    async def _ccy(_db, target_peer=None):
        return "SBXB"

    async def _base(teg_id, registry_id):
        return f"https://{teg_id}:8443"

    read = []

    async def _reserve(base, _key):
        read.append(base)
        if base in (LOCAL_TEG, "https://teg-layer-sandbox-beta:8443"):
            return Decimal("1000")
        raise RuntimeError(f"Client error '404 Not Found' for url '{base}/api/v1/admin/fx/reserve'")

    monkeypatch.setattr(juris, "check_jurisdiction", _no_jurisdiction)
    monkeypatch.setattr(T, "_resolve_receiver_registry", _home)
    monkeypatch.setattr(T, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(T, "_local_frame_currency", lambda: "SBXA")
    monkeypatch.setattr(T, "_resolve_dest_teg_mtls_base", _base)
    monkeypatch.setattr(T, "_fx_read_reserve", _reserve)
    monkeypatch.setattr(T, "_fx_enforce_caps", lambda *_a, **_k: None)
    monkeypatch.setattr(T, "_fx_fee_rate", lambda: Decimal("0.005"))
    monkeypatch.setenv("FX_RATE_MODE", "pool")
    monkeypatch.setenv("TEG_API_BASE_URL", LOCAL_TEG)
    out = _run(_route(T.fx_quote)(req=T.FxQuoteRequest(receiver_did="did:theprotocol:rx", amount="1"),
                                   request=None, current_agent=SimpleNamespace(did="did:theprotocol:tx"),
                                   db=_DB()))
    return out, read


def _swap_net():
    pq = T._fx_pool_quote(Decimal("1000"), Decimal("1000"), Decimal("1"), False, Decimal("0.005"))
    return pq["net"]


def test_a_leaf_receiver_is_priced_at_the_reserve_frame_and_pays_the_delivery_fee(engine_on, monkeypatch):
    out, read = _quote_with(monkeypatch, "sbxbetaop")
    assert read == [LOCAL_TEG, "https://teg-layer-sandbox-beta:8443"], f"the leaf's reserve was read: {read}"
    net = _swap_net()
    fee = (net * Decimal("0.5") / Decimal("100")).quantize(Decimal("0.000001"))
    assert out.reserve_frame == "sandbox-beta"
    assert Decimal(out.delivery_fee) == fee > 0
    assert Decimal(out.amount_out) == net - fee, "amount_out is what the receiver is credited after delivery"


def test_control_a_receiver_on_the_reserve_frame_is_quoted_directly(engine_on, monkeypatch):
    out, read = _quote_with(monkeypatch, "sandbox-beta")
    assert read == [LOCAL_TEG, "https://teg-layer-sandbox-beta:8443"]
    assert out.reserve_frame is None and out.delivery_fee is None
    assert Decimal(out.amount_out) == _swap_net()


def test_control_with_the_route_engine_off_the_leaf_is_read_as_before(engine_on, monkeypatch):
    monkeypatch.setattr(T, "_fx_route_enabled", lambda: False)
    with pytest.raises(T.HTTPException) as e:
        _quote_with(monkeypatch, "sbxbetaop")
    assert e.value.status_code == 503 and "reserve read failed" in str(e.value.detail)


def _calls(tree, fn_name, callee):
    for n in ast.walk(tree):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == fn_name:
            return sum(1 for c in ast.walk(n) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == callee)
    raise AssertionError(f"{fn_name} not found")


def test_the_transfer_the_quote_and_the_pool_ask_one_predicate():
    tree = ast.parse(_SRC.read_text(encoding="utf-8"))
    for fn in ("_cross_registry_transfer_run", "fx_quote", "fx_pool"):  # §REPATLANE-5: the transfer route's work
        assert _calls(tree, fn, "_fx_leaf_gateway") == 1, f"{fn} must ask _fx_leaf_gateway"
        # a second copy of the predicate would look the gateway up itself (the pre-V0528 transfer path did, inline)
        assert _calls(tree, fn, "_fx_route_gateway_for_currency") == 0, f"{fn} asks the gateway itself again"
