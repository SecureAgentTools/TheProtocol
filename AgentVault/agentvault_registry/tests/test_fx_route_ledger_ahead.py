"""§LEDGERGATE (V0602): a cross-currency FX route is refused IN FRONT of the value while the receiving reserve frame's
ledger cannot record its payout.

Measured in journal 51's photo drill (2026-10-12, take 2: Sandbox Alpha's store down 90 s): Sandbox Alpha's TEG refused
the payouts of five routes Sandbox Beta had already converted (router -> receiver is a new movement to that TEG), the
converted 235.08 SBXA parked at Sandbox Alpha's @fx_router, and the recovery delivered it five minutes later; three of
the five paid AGORA passport orders that could not be placed meanwhile. The converting frame now reads the receiving
frame's ledger first (GET /federation/fx/ledger): while that frame enforces and reads unhealthy nothing is converted. A
read that fails, an older frame without the read, shadow or any other state goes ahead as before.

§LEDGERGATE (V0603): V0602 read GET /api/v1/teg/fx/ledger, a path no frame's federation proxy forwards (they forward
/api/v1/teg/fx/route-hop and /api/v1/federation/; the rest answers 404 from `location /`). Every live read failed and
went ahead: drill 3 (2026-10-12) held Sandbox Alpha's store down 107 s and four routes into it converted and parked,
one of them an AGORA payout the lane then sent again. The read now rides /api/v1/federation/fx/ledger.

RED on mcptest/v0601: none of these names exist there. RED on mcptest/v0602 for the path tests.
Sync tests driving the coroutines with asyncio.run (CI's pytest cannot see the ini's asyncio mode, see ci.yml).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import teg_integration as ti
from agentvault_registry.services.ledger_unavailable import MARKER, SENTENCE

TEG = pathlib.Path(ti.__file__)


# ---------------------------------------------------------------------------------------------------------- the rule
def test_an_enforcing_unhealthy_ledger_refuses_with_the_tegs_own_sentence():
    r = ti._fx_ledger_ahead_refusal({"mode": "enforce", "state": "unhealthy", "retry_after_s": 45})
    assert isinstance(r, HTTPException) and r.status_code == 503
    assert r.detail == f"{MARKER} {SENTENCE}"
    assert r.headers == {"Retry-After": "45"}


@pytest.mark.parametrize("state", [
    {"mode": "shadow", "state": "unhealthy"},      # shadow counts, the receiving TEG would not refuse
    {"mode": "enforce", "state": "ok"},
    {"mode": "enforce", "state": "degraded"},       # the TEG passes degraded, so does the route
    {"mode": "enforce", "state": "unknown"},
    {"mode": "off", "state": "unhealthy"},
    {}, None, "unhealthy", ["enforce"],
])
def test_anything_else_goes_ahead(state):
    assert ti._fx_ledger_ahead_refusal(state) is None


@pytest.mark.parametrize("raw,want", [(None, "30"), ("abc", "30"), (0, "30"), (999, "300"), (7, "7")])
def test_the_retry_after_is_bounded(raw, want):
    r = ti._fx_ledger_ahead_refusal({"mode": "enforce", "state": "unhealthy", "retry_after_s": raw})
    assert r.headers["Retry-After"] == want


def test_this_frames_ledger_is_read_from_its_tegs_health():
    h = {"status": "ok", "ledger": {"mode": "enforce", "ledger": {"state": "unhealthy", "reason": "store_unreachable",
                                                                   "source": "leader", "retry_after_s": 30}}}
    assert ti._fx_ledger_block_from_health(h) == {"mode": "enforce", "state": "unhealthy",
                                                  "reason": "store_unreachable", "retry_after_s": 30}
    assert ti._fx_ledger_block_from_health({"status": "ok"}) == {"mode": "unknown", "state": "unknown"}
    assert ti._fx_ledger_block_from_health(None) == {"mode": "unknown", "state": "unknown"}


# ------------------------------------------------------------------------------------------ the read of the far frame
class _Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class _Client:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    async def get(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


def _read(monkeypatch, client, gd=None, peer=None):
    monkeypatch.setattr(ti, "_get_teg_client", lambda: client)
    ti._FX_LEDGER_AHEAD_CACHE.clear()
    return asyncio.run(ti._fx_route_gd_ledger_state(gd or {"url": "https://gd.example/", "registry_id": "registry-gd"},
                                                    peer or SimpleNamespace(base_url="")))


def test_the_far_ledger_is_read_with_the_federation_credentials(monkeypatch):
    monkeypatch.setenv("FEDERATION_LICENSE_KEY", "lic-for-the-test")
    c = _Client(_Resp(200, {"mode": "enforce", "state": "ok"}))
    assert _read(monkeypatch, c) == {"mode": "enforce", "state": "ok"}
    url, headers = c.calls[0]
    assert url == "https://gd.example/api/v1/federation/fx/ledger"
    assert headers.get("X-Federation-License") == "lic-for-the-test"


def test_the_peer_rows_address_is_used_when_the_gateway_names_none(monkeypatch):
    c = _Client(_Resp(200, {"mode": "enforce", "state": "ok"}))
    _read(monkeypatch, c, gd={"url": "", "registry_id": "registry-gd"}, peer=SimpleNamespace(base_url="https://row.example"))
    assert c.calls[0][0] == "https://row.example/api/v1/federation/fx/ledger"


def _proxied_prefixes(conf: str):
    """The location prefixes a federation proxy template sends to the registry (everything but `location /`)."""
    import re
    return [m.group(1) for m in re.finditer(r"^\s*location\s+(?:=\s+)?(/[^\s{]+)\s*\{", conf, re.M) if m.group(1) != "/"]


def test_the_peer_path_is_one_the_federation_proxies_forward():
    # every frame's proxy forwards /api/v1/federation/ (agent-card sync, the FX keeper's parked-at/claim/resolve)
    assert ti.FX_LEDGER_PEER_PATH.startswith("/api/v1/federation/")
    tmpl = pathlib.Path("/opt/theprotocol/stack/Agentvault2/templates/frame-test/nginx-federation-frame-test.conf.tmpl")
    if tmpl.exists():   # the stack's template, where this tree sits in the stack (CI checks the prefix rule above)
        prefixes = _proxied_prefixes(tmpl.read_text(encoding="utf-8"))
        assert any(ti.FX_LEDGER_PEER_PATH.startswith(p) for p in prefixes), prefixes
        assert not any("/api/v1/teg/fx/ledger".startswith(p) for p in prefixes), "the V0602 path is now forwarded?"


def test_the_federation_router_serves_the_ledger_read_to_peers():
    from agentvault_registry.routers import federation_sync as fs
    route = next(r for r in fs.router.routes if getattr(r, "path", "") == "/api/v1/federation/fx/ledger")
    assert route.methods == {"GET"}
    assert fs.require_peer_registry_identity in [d.call for d in route.dependant.dependencies]


@pytest.mark.parametrize("answer", [_Resp(404, {}), _Resp(500, {"detail": "x"}), _Resp(200, ["not", "a", "dict"]),
                                    RuntimeError("connection refused")])
def test_a_read_that_could_not_be_made_is_not_a_refusal(monkeypatch, answer):
    assert _read(monkeypatch, _Client(answer)) is None


def test_the_read_is_cached_for_two_seconds_per_frame(monkeypatch):
    c = _Client(_Resp(200, {"mode": "enforce", "state": "unhealthy"}))
    monkeypatch.setattr(ti, "_get_teg_client", lambda: c)
    ti._FX_LEDGER_AHEAD_CACHE.clear()
    gd, peer = {"url": "https://gd.example"}, SimpleNamespace(base_url="")
    first = asyncio.run(ti._fx_route_gd_ledger_state(gd, peer))
    second = asyncio.run(ti._fx_route_gd_ledger_state(gd, peer))
    assert first == second == {"mode": "enforce", "state": "unhealthy"}
    assert len(c.calls) == 1


# ------------------------------------------------------------------------------ the reserve-frame origin, driven
def _origin_reserve(monkeypatch, refusal):
    async def _peer(db, reg):
        return SimpleNamespace(base_url="https://gd.example")

    async def _streak(reg):
        return 0

    async def _refusal(gd, gd_peer):
        return refusal

    swaps = []

    async def _swap(**kw):
        swaps.append(kw)
        raise RuntimeError("the swap ran")   # the control stops here: the route went ahead to its conversion

    monkeypatch.setattr(ti, "_fx_route_enabled", lambda: True)
    monkeypatch.setattr(ti, "_fx_route_local_router_did", lambda: "did:theprotocol:router-here")
    monkeypatch.setattr(ti, "_fx_route_gateway_for_currency",
                        lambda ccy: {"router_did": "did:theprotocol:router-gd", "registry_id": "registry-gd",
                                     "teg_id": "teg-gd", "url": "https://gd.example"})
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_fx_egress_breaker_state", _streak)
    monkeypatch.setattr(ti, "_fx_egress_breaker_threshold", lambda: 3)
    monkeypatch.setattr(ti, "_fx_route_gd_ledger_refusal", _refusal)
    monkeypatch.setattr(ti, "_fx_cross_currency_swap", _swap)
    agent = SimpleNamespace(did="did:theprotocol:sender", spiffe_id="", mtls_enabled=False, id=1)
    req = SimpleNamespace(amount="10", receiver_did="did:theprotocol:receiver", message="")
    return swaps, asyncio.run(ti._fx_route_origin_reserve(None, agent, req, dest_ccy="SBXA"))


def test_the_reserve_origin_refuses_before_it_converts(monkeypatch):
    refusal = ti._fx_ledger_ahead_refusal({"mode": "enforce", "state": "unhealthy"})
    with pytest.raises(HTTPException) as e:
        _origin_reserve(monkeypatch, refusal)
    assert e.value.status_code == 503 and e.value.detail == f"{MARKER} {SENTENCE}"


def test_control_the_reserve_origin_converts_when_the_far_ledger_can_record(monkeypatch):
    with pytest.raises(RuntimeError, match="the swap ran"):
        _origin_reserve(monkeypatch, None)


# ------------------------------------------------------------- the operator's origin, when its gateway returned the money
def test_the_operators_origin_says_the_money_came_back(monkeypatch):
    async def _peer(db, reg):
        return SimpleNamespace(base_url="https://gw.example")

    async def _ingress(db, **kw):
        return True, None, "10", "tx-ingress"

    async def _delegate(url, body):
        return {"status": "error", "http_status": 409, "compensated": True,
                "detail": f"{ti.FX_LEDGER_AHEAD_NOTE} {ti._FX_COMPENSATED_MARK}"}

    async def _resolve(db, did):
        return "teg-far", "registry-far"

    async def _ccy(db, target_peer=None):
        return "SBXA"

    events = []
    monkeypatch.setattr(ti, "_fx_route_my_gateway",
                        lambda: {"registry_id": "registry-gw", "router_did": "did:theprotocol:router-gw",
                                 "teg_id": "teg-gw", "url": "https://gw.example"})
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _ingress)
    monkeypatch.setattr(ti, "_fx_route_delegate", _delegate)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_emit_fx_route_event", lambda kind, **kw: events.append((kind, kw.get("status"))))
    agent = SimpleNamespace(did="did:theprotocol:sender", spiffe_id="", mtls_enabled=False, id=1)
    req = SimpleNamespace(amount="10", receiver_did="did:theprotocol:receiver", message="")
    with pytest.raises(HTTPException) as e:
        asyncio.run(ti._fx_route_origin(None, agent, req))
    assert e.value.status_code == 503 and e.value.headers == {"Retry-After": "30"}
    assert "came back to you" in e.value.detail
    assert events == [("FxRouteRefunded", "refunded")]


# ---------------------------------------------------------------------------------- the order, in the engine's source
def _fn(name):
    tree = ast.parse(TEG.read_text())
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def _first_call_line(fn, callee):
    lines = [c.lineno for c in ast.walk(fn) if isinstance(c, ast.Call) and getattr(c.func, "id", "") == callee]
    return min(lines) if lines else None


@pytest.mark.parametrize("name", ["_fx_route_hop_execute_inner", "_fx_route_origin_reserve"])
def test_both_converting_sites_read_the_far_ledger_before_the_swap(name):
    fn = _fn(name)
    read, swap = _first_call_line(fn, "_fx_route_gd_ledger_refusal"), _first_call_line(fn, "_fx_cross_currency_swap")
    assert read is not None and swap is not None and read < swap, (name, read, swap)


def test_the_hop_returns_the_ingress_before_it_refuses():
    fn = _fn("_fx_route_hop_execute_inner")
    guard = next(n for n in ast.walk(fn) if isinstance(n, ast.If)
                 and any(getattr(c.func, "id", "") == "_fx_route_gd_ledger_refusal"
                         for c in ast.walk(n.test) if isinstance(c, ast.Call)))
    body = ast.unparse(ast.Module(body=guard.body, type_ignores=[]))
    assert body.index("_compensate()") < body.index("raise HTTPException")
    assert "_FX_COMPENSATED_MARK" in body and "_uncompensated_note()" in body   # the marker only when it came back


def test_the_ledger_read_is_a_federation_authed_get():
    route = next(r for r in ti.router.routes if getattr(r, "path", "").endswith("/fx/ledger"))
    assert route.methods == {"GET"}
    deps = [d.call for d in route.dependant.dependencies]
    assert ti.require_peer_registry_identity in deps
    assert inspect.iscoroutinefunction(ti.fx_ledger_state)
