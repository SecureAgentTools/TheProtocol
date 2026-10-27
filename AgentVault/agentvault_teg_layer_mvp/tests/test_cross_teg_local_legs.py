"""§SECFIX-11/12/13 (2026-09-25) — who may call the cross-TEG money legs, what a peer may credit, and what leaves the frame.

Measured before, on the sandbox pair, with a PEER frame registry's own certificate and an EMPTY body (nothing can move):
lock-async, credit-async, credit-async-bulk, refund-async and reverse-async answered 400 and /accept 422 (the auth took
the peer, only the body stopped it), /prepare 500 (it sliced an Authorization header an mTLS caller does not send), and
/api/v1/admin/treasury/external-credit 422. On the live frames no peer called any of them, and every COMPLETED 2PC credit
came from the TEG's own trust domain. The sender forwarded the agent's TEG JWT to the peer on prepare, commit and abort.

RED control: run against the tree before the fix (PYTHONPATH naming it): the rule functions and peer_inbound do not
exist there, and the source pins fail.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
from decimal import Decimal

import pytest
from fastapi import HTTPException
from pydantic import BaseModel

from teg_core_service.core import internal_auth as ia

SRC = pathlib.Path(ia.__file__).resolve().parents[1]
ROUTER = SRC / "api" / "cross_teg_router.py"
COORD = SRC / "core" / "cross_teg" / "coordinator.py"
TREASURY = SRC / "api" / "v1" / "endpoints_treasury.py"
OWN = "sandbox-a.theprotocol.cloud"
PEER = "sandbox-b.theprotocol.cloud"
LOCAL_LEGS = {"lock_async": "lock-async", "credit_async": "credit-async", "credit_async_bulk": "credit-async-bulk",
              "refund_async": "refund-async", "reverse_async": "reverse-async", "accept_cross_teg_transfer": "accept"}


def _own(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    monkeypatch.delenv("CROSS_TEG_LOCAL_LEG_SOURCES", raising=False)


def test_the_own_frame_and_its_operators_are_local(monkeypatch):
    _own(monkeypatch)
    assert ia.local_leg_caller_ok(f"spiffe://{OWN}/service/sbx-alpha-registry")
    assert ia.local_leg_caller_ok(f"spiffe://{OWN}/operator/sbxalphaop/svid-writer")


def test_a_peer_frame_a_shared_key_and_nothing_are_not(monkeypatch):
    _own(monkeypatch)
    assert not ia.local_leg_caller_ok(f"spiffe://{PEER}/service/sbx-beta-registry")
    assert not ia.local_leg_caller_ok(f"spiffe://{PEER}/service/teg-layer")
    assert not ia.local_leg_caller_ok("shared-key")
    assert not ia.local_leg_caller_ok(None)
    assert not ia.local_leg_caller_ok("")


def test_the_sources_widen_by_domain_or_exact_id(monkeypatch):
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    monkeypatch.setenv("CROSS_TEG_LOCAL_LEG_SOURCES", f"{OWN},spiffe://{PEER}/service/sbx-beta-registry")
    assert ia.local_leg_caller_ok(f"spiffe://{PEER}/service/sbx-beta-registry")
    assert not ia.local_leg_caller_ok(f"spiffe://{PEER}/service/teg-layer")


def _router():
    from teg_core_service.api import cross_teg_router as r
    return r


class _Req:
    url = type("U", (), {"path": "/api/v1/cross-teg/lock-async"})()
    headers = {}


def test_the_wrapper_admits_its_frame_and_refuses_a_peer(monkeypatch):
    _own(monkeypatch)
    monkeypatch.setenv("TEG_MTLS_REQUIRED", "true")
    r = _router()
    monkeypatch.setattr(r, "_extract_spiffe_from_header", lambda req: f"spiffe://{OWN}/service/sbx-alpha-registry")
    assert r._require_local_caller(_Req(), "", "lock-async").startswith(f"spiffe://{OWN}/")
    monkeypatch.setattr(r, "_extract_spiffe_from_header", lambda req: f"spiffe://{PEER}/service/sbx-beta-registry")
    with pytest.raises(HTTPException) as e:
        r._require_local_caller(_Req(), "", "lock-async")
    assert e.value.status_code == 403 and "cross_teg_local_leg_refused" in str(e.value.detail)


def _src(path):
    return path.read_text(encoding="utf-8")


def _fn(tree, name):
    return next(n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)


def _calls(fn):
    return [n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]


def _dep_routes(fn):
    """The routes named by `_local_caller_dependency("<route>")` in the handler's parameter defaults."""
    out = []
    for d in fn.args.defaults + fn.args.kw_defaults:
        for n in ast.walk(d) if d is not None else ():
            if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_local_caller_dependency" and n.args:
                out.append(getattr(n.args[0], "value", None))
    return out


def test_every_local_leg_asks_the_local_rule():
    tree = ast.parse(_src(ROUTER))
    for name, route in LOCAL_LEGS.items():
        fn = _fn(tree, name)
        calls = _calls(fn)
        assert "_require_local_caller" in calls or route in _dep_routes(fn), name
        assert "_validate_cross_teg_auth" not in calls, f"{name} still authenticates without the local rule"
    # a leg with a typed body refuses in a DEPENDENCY, before the body is validated (else an empty body answers 422)
    assert "accept" in _dep_routes(_fn(tree, "accept_cross_teg_transfer"))


def test_the_2pc_legs_never_slice_an_absent_header_and_prepare_counts_the_peer():
    src = _src(ROUTER)
    assert '"auth_token": authorization[7:]' not in src
    assert src.count('"auth_token": (authorization or "")[7:]') == 3
    prep = ast.get_source_segment(src, _fn(ast.parse(src), "prepare_transfer"))
    assert "_peer_inbound.admit(caller" in prep and "HTTP_429_TOO_MANY_REQUESTS" in prep


def test_a_transfer_is_started_only_by_the_own_frame():
    src = _src(ROUTER)
    seg = ast.get_source_segment(src, _fn(ast.parse(src), "initiate_cross_teg_transfer"))
    assert "if teg_mtls_required():" in seg and "local_leg_caller_ok(_svid)" in seg


def test_the_sender_no_longer_forwards_the_agent_jwt():
    src = _src(COORD)
    assert "auth_token=request.authorization_token" not in src
    assert src.count("auth_token=PEER_BEARER_PLACEHOLDER") == 3


GATE = SRC / "core" / "external_credit.py"


class _Body(BaseModel):
    """A typed body like the route's (module level: this file postpones annotations, and FastAPI resolves them here)."""
    amount: str
    source_teg_id: str


def test_external_credit_is_retired_behind_a_positive_flag():
    gate = _src(GATE)
    assert 'os.getenv("TEG_EXTERNAL_CREDIT_ENABLED")' in gate and "HTTP_410_GONE" in gate and "local_leg_caller_ok(" in gate
    tsrc = _src(TREASURY)
    assert "from ...core.external_credit import external_credit_gate as _external_credit_gate" in tsrc
    handler = ast.get_source_segment(tsrc, _fn(ast.parse(tsrc), "treasury_external_credit"))
    assert "Depends(_external_credit_gate)" in handler


def _client(router, overrides=None):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(router)
    for k, v in (overrides or {}).items():
        app.dependency_overrides[k] = v
    return TestClient(app)


def test_accept_refuses_a_peer_before_reading_its_body(monkeypatch):
    """An EMPTY body from a peer: 403 from the dependency, never the 422 a body check would answer first."""
    _own(monkeypatch)
    monkeypatch.setenv("TEG_MTLS_REQUIRED", "true")
    r = _router()
    monkeypatch.setattr(r, "_extract_spiffe_from_header", lambda req: f"spiffe://{PEER}/service/sbx-beta-registry")
    res = _client(r.router).post("/api/v1/cross-teg/accept", json={})
    assert res.status_code == 403 and "cross_teg_local_leg_refused" in res.text, (res.status_code, res.text[:200])


def test_external_credit_answers_gone_before_reading_its_body(monkeypatch):
    """The gate as the route wires it (a dependency beside a typed body): an EMPTY body gets 410, never 422."""
    from fastapi import APIRouter, Depends
    from teg_core_service.core.external_credit import external_credit_gate

    rt = APIRouter()

    @rt.post("/treasury/external-credit")
    async def _route(request: _Body, _gate: None = Depends(external_credit_gate)):
        return {"credited": True}

    monkeypatch.delenv("TEG_EXTERNAL_CREDIT_ENABLED", raising=False)
    res = _client(rt).post("/treasury/external-credit", json={})
    assert res.status_code == 410 and "retired" in res.text, (res.status_code, res.text[:200])
    monkeypatch.setenv("TEG_EXTERNAL_CREDIT_ENABLED", "true")
    res = _client(rt).post("/treasury/external-credit", json={})
    assert res.status_code == 403 and "own frame only" in res.text, (res.status_code, res.text[:200])


class _FakeRedis:
    def __init__(self):
        self.v = {}

    async def incrbyfloat(self, k, a):
        self.v[k] = self.v.get(k, 0.0) + a
        return self.v[k]

    async def expire(self, k, s):
        return True


def _admit(monkeypatch, fake, mode, caller, amount, limit="100"):
    from teg_core_service.core.cross_teg import peer_inbound as pi
    monkeypatch.setenv("SPIRE_TRUST_DOMAIN", OWN)
    monkeypatch.setenv("CROSS_TEG_PEER_INBOUND_LIMIT_MODE", mode)
    monkeypatch.setenv("CROSS_TEG_PEER_INBOUND_DAILY_LIMIT", limit)

    async def _get():
        return fake

    import teg_core_service.redis_client as rc
    monkeypatch.setattr(rc, "get_redis", _get)
    return asyncio.run(pi.admit(caller, amount, "t-1"))


def test_own_domain_inbound_is_never_counted(monkeypatch):
    fake = _FakeRedis()
    ok, detail = _admit(monkeypatch, fake, "enforce", f"spiffe://{OWN}/operator/x/teg", "1000000")
    assert ok and detail == "not counted" and fake.v == {}


def test_a_peer_is_bounded_per_day(monkeypatch):
    fake = _FakeRedis()
    peer = f"spiffe://{PEER}/service/teg-layer"
    assert _admit(monkeypatch, fake, "enforce", peer, "60")[0]
    ok, detail = _admit(monkeypatch, fake, "enforce", peer, "50")
    assert not ok and "peer_inbound_limit" in detail
    assert Decimal(str(next(iter(fake.v.values())))) == Decimal("60"), "a refused amount is taken back"
    ok, detail = _admit(monkeypatch, fake, "observe", peer, "50")
    assert ok and "observe" in detail


def test_without_redis_observe_serves_and_enforce_refuses(monkeypatch):
    peer = f"spiffe://{PEER}/service/teg-layer"
    assert _admit(monkeypatch, None, "observe", peer, "1")[0]
    assert not _admit(monkeypatch, None, "enforce", peer, "1")[0]
