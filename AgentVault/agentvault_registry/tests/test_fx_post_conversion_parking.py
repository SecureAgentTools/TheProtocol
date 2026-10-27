"""§FXPOSTCONV (2026-09-26): after a conversion, a failed delivery is parked for RE-DELIVERY, never refunded in the
wrong currency.

Measured on the sandbox pair: every nightly since 09-23 the federation suite's alpha->delta route (an agent on
sbx-alpha's operator paying a new agent on sbx-beta's operator) converted SBXA -> SBXB at sbx-alpha, delegated the
delivery to sbx-beta, and sbx-beta could not yet resolve the new receiver. The shared route engine then treated the
failure as pre-conversion: it refunded the ORIGIN 1:1 in SBXB (the origin's home holds SBXA; its TEG refused), wrote
a `pre_conversion` dead letter, and the keeper retried that refund 8 times before marking it 'failed'. One route a
night, 9 refused 2PC legs, about 2 SBXB left parked each time. The reserve-origin path already recorded such a
failure correctly (`post_conversion_remote` with the receiver, for the far frame's keeper to re-deliver); the
operator-origin path through the gateway recorded nothing.

The fix: the delegate after a conversion says so (`post_conversion: True`), the engine never refunds the origin in
that case (its one refund site is the `_compensate` wrapper), the gateway records `post_conversion_remote` when the
delegated delivery fails, and the keeper refuses a refund whose origin's home holds another currency.

RED control: against the tree before the fix (OPDIST_SRC naming it), the AST gates find no `post_conversion` field,
no wrapper, and no parking record in the engine; the keeper drive attempts the cross-currency refund.
"""
from __future__ import annotations

import ast
import asyncio
import os
import pathlib
from types import SimpleNamespace

_HERE = pathlib.Path(__file__).resolve()
_PKG = pathlib.Path(os.environ["OPDIST_SRC"]) if os.environ.get("OPDIST_SRC") else (
    _HERE.parents[1] / "src" / "agentvault_registry")
TEG = _PKG / "routers" / "teg_integration.py"
KEEPER = _PKG / "background_tasks" / "fx_router_keeper.py"


def _tree(path):
    return ast.parse(path.read_text(encoding="utf-8"))


def _node(tree, name, kinds=(ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef)):
    for n in ast.walk(tree):
        if isinstance(n, kinds) and n.name == name:
            return n
    raise AssertionError(f"{name} not found")


def _params(fn):
    return {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}


def _delegate_payloads(fn):
    """The dict literal handed to each `_fx_route_delegate(url, {...})` inside `fn`, as {key: value-node}."""
    out = []
    for c in ast.walk(fn):
        if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_fx_route_delegate" and len(c.args) >= 2 \
                and isinstance(c.args[1], ast.Dict):
            d = c.args[1]
            out.append({k.value: v for k, v in zip(d.keys, d.values) if isinstance(k, ast.Constant)})
    return out


def test_the_hop_request_carries_post_conversion_defaulting_false():
    model = _node(_tree(TEG), "FxRouteHopRequest", (ast.ClassDef,))
    fields = {n.target.id: n for n in model.body if isinstance(n, ast.AnnAssign)}
    assert "post_conversion" in fields, "FxRouteHopRequest must accept post_conversion from the delegating frame"
    default = fields["post_conversion"].value
    assert isinstance(default, ast.Constant) and default.value is False, "absent (an older caller) must mean False"


def test_the_flag_reaches_the_engine():
    tree = _tree(TEG)
    hop = _node(tree, "fx_route_hop")
    kws = [k.arg for c in ast.walk(hop) if isinstance(c, ast.Call)
           and getattr(c.func, "id", "") == "_fx_route_hop_execute" for k in c.keywords]
    assert "post_conversion" in kws, "the route-hop endpoint drops the flag"
    for name in ("_fx_route_hop_execute", "_fx_route_hop_execute_inner"):
        assert "post_conversion" in _params(_node(tree, name)), f"{name} does not take post_conversion"
    outer = _node(tree, "_fx_route_hop_execute")
    kws = [k.arg for c in ast.walk(outer) if isinstance(c, ast.Call)
           and getattr(c.func, "id", "") == "_fx_route_hop_execute_inner" for k in c.keywords]
    assert "post_conversion" in kws, "the semaphore wrapper drops the flag"


def test_the_engine_refunds_only_through_the_wrapper_and_never_after_a_conversion():
    engine = _node(_tree(TEG), "_fx_route_hop_execute_inner")
    wrapper = _node(engine, "_compensate")
    refunds = [c for c in ast.walk(engine) if isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == "_fx_route_refund_to_origin"]
    inside = [c for c in ast.walk(wrapper) if isinstance(c, ast.Call)
              and getattr(c.func, "id", "") == "_fx_route_refund_to_origin"]
    assert refunds and len(refunds) == len(inside) == 1, \
        f"{len(refunds)} refund call(s) in the engine, {len(inside)} inside _compensate: every refund must go through it"
    first = wrapper.body[1] if isinstance(wrapper.body[0], ast.Expr) else wrapper.body[0]   # after the docstring
    assert isinstance(first, ast.If) and getattr(first.test, "id", "") == "post_conversion", \
        "the wrapper must decide on post_conversion before anything else"
    rets = [n for n in ast.walk(first) if isinstance(n, ast.Return)]
    assert rets and all(isinstance(r.value, ast.Constant) and r.value.value is False for r in rets), \
        "after a conversion the wrapper returns False (no refund) and nothing else"


def test_every_delegate_after_a_conversion_says_so_and_the_ingress_delegate_does_not():
    tree = _tree(TEG)
    for name in ("_fx_route_hop_execute_inner", "_fx_route_origin_reserve"):
        payloads = _delegate_payloads(_node(tree, name))
        assert payloads, f"{name} delegates nowhere (the gate is looking at the wrong function)"
        for p in payloads:
            v = p.get("post_conversion")
            assert isinstance(v, ast.Constant) and v.value is True, f"{name}'s delegate after its FX core omits post_conversion"
    for p in _delegate_payloads(_node(tree, "_fx_route_origin")):
        v = p.get("post_conversion")
        assert v is None or (isinstance(v, ast.Constant) and v.value is False), \
            "the operator origin's ingress delegate is PRE-conversion: the gateway may still refund it"


def test_the_gateway_records_the_parking_for_the_far_frames_keeper():
    engine = _node(_tree(TEG), "_fx_route_hop_execute_inner")
    records = [c for c in ast.walk(engine) if isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == "_record_fx_dead_letter"]
    ok = [c for c in records
          if any(k.arg == "phase" and isinstance(k.value, ast.Constant) and k.value.value == "post_conversion_remote"
                 for k in c.keywords)
          and any(k.arg == "receiver_did" for k in c.keywords)]
    assert ok, "the engine must record post_conversion_remote (with the receiver) when its delegated delivery fails"


# ── the keeper: a refund whose origin's home holds another currency is never attempted ─────────────────────────────
class _Res:
    def __init__(self, rows=None, one=None):
        self._rows, self._one = rows or [], one

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def scalar_one_or_none(self):
        return self._one


class _DB:
    def __init__(self, row, router):
        self._answers = [_Res(rows=[row]), _Res(one=router)]
        self.commits = 0

    async def execute(self, stmt):
        return self._answers.pop(0)

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


def _drive_keeper(monkeypatch, origin_ccy, row_ccy="SBXB"):
    from agentvault_registry.background_tasks import fx_router_keeper as fk
    from agentvault_registry.routers import teg_integration as ti
    calls = []

    async def _peer(db, rid):
        return SimpleNamespace(trust_domain="sandbox-a.theprotocol.cloud")

    async def _ccy(db, target_peer=None, trust_domain=None):
        return origin_ccy

    async def _two_pc(db, **kw):
        calls.append(kw)
        # §REPATLANE-6 (V0606): a refusal that proves the leg never ran (a plain sentence now holds as not known)
        return False, ti._LegError("2pc leg 400: Target TEG rejected transfer", nothing_moved=True), None, None

    async def _resolve(db, did):
        return ("teg-sbxalphaop", "registry-sbxalphaop")

    async def _distribute(*a, **k):
        return "tx-fees", False, ""
    monkeypatch.setattr(ti, "_fee_collector_distribute", _distribute)
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", _peer)
    monkeypatch.setattr(ti, "_resolve_peer_currency", _ccy)
    monkeypatch.setattr(ti, "_fx_route_1to1_2pc", _two_pc)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", _resolve)
    monkeypatch.setenv("FX_ROUTER_DID", "did:theprotocol:router")
    row = SimpleNamespace(route_id="bf35446d-3e08-44cc-b1a7-bc397e7e7a3e", origin_did="did:theprotocol:origin",
                          origin_teg_id="teg-sbxalphaop", origin_registry_id="registry-sbxalphaop",
                          amount="1.988142", currency=row_ccy, status="pending", retries=0, last_error=None,
                          resolution_tx=None, resolved_at=None, phase="pre_conversion")
    db = _DB(row, SimpleNamespace(did="did:theprotocol:router"))
    keeper = fk.FxRouterKeeper()
    out = asyncio.run(keeper._process_dead_letters(db, SimpleNamespace(dead_letter_max_retries=8)))
    return out, row, calls


def test_the_keeper_refuses_a_cross_currency_refund_without_a_leg(monkeypatch):
    out, row, calls = _drive_keeper(monkeypatch, origin_ccy="SBXA")
    assert calls == [], "no 2PC leg may be attempted for a refund in the wrong currency"
    assert row.status == "failed" and "not refundable here" in (row.last_error or "")
    assert out.get("failed") == 1


def test_control_a_same_currency_refund_is_still_attempted(monkeypatch):
    out, row, calls = _drive_keeper(monkeypatch, origin_ccy="SBXB")
    assert len(calls) == 1, "the guard must not stop a refund the origin's home can take"
    assert row.status == "pending" and row.retries == 1, "a refused same-currency refund retries as before"
