"""V0639 (agentvault2-66, 2026-10-24): the cross-registry transfer refuses a receiver that is one of this registry's own
agents, before any route is tried.

_resolve_receiver_registry answers (None, None) for a local agent (its step 1: "use normal /teg/transfer"), and
_cross_registry_transfer_run read None as "unresolvable here": on a node with an FX gateway configured (every cloud
operator) the transfer went into the FX route. Measured on both sandbox operators: the MCP tester's 0.01 from its
sentinel to the sentinel ITSELF went up to the parent frame's FX router (cross_teg_send) and came back as 0.0099
(cross_teg_receive, fee 0.00005), sbxalphaop 13:40:33Z and sbxbetaop 13:43:55Z, and the route answered 200.

Through FastAPI on the real TEG router, as tests/test_sec_quarantine_blocks_settlement.py does. Doubles: the database
session (it answers the native-agent read), the receiver's home resolution, and the FX route's ingress (a sentinel
that records it was reached). RED on 810d6038: the native receiver on an FX-gateway node reaches the route.
"""
from __future__ import annotations

import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti

AGENT = types.SimpleNamespace(id=11, did="did:theprotocol:sandbox-a.theprotocol.cloud:1b73ce96",
                              mtls_enabled=False, spiffe_id=None, status="active")
NATIVE_SQL = "is_federated_mirror IS NOT TRUE"


class _Res:
    def __init__(self, one=None):
        self._one = one

    def first(self):
        return self._one

    def all(self):
        return []

    def scalar_one_or_none(self):
        return None

    def scalars(self):
        return types.SimpleNamespace(all=lambda: [], first=lambda: None)

    def scalar(self):
        return 0


class _Db:
    """The native-agent read answers a row (`native`), nothing, or fails; anything else answers nothing."""

    def __init__(self, native=False, fail=False):
        self.native, self.fail, self.asked = native, fail, []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if NATIVE_SQL in sql:
            self.asked.append(dict(params or {}))
            if self.fail:
                raise RuntimeError("database unreachable")
            return _Res(one=(1,) if self.native else None)
        return _Res()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def reached(monkeypatch):
    """Sentinels past the refusal point: the FX route's ingress and the choice of a rail each record they were
    reached."""
    out = []

    async def fx_route_origin(db, purse_agent, xfer_req):
        out.append(("fx_route", xfer_req.receiver_did))
        raise HTTPException(status_code=418, detail="sentinel: the transfer went into the FX route")

    async def teg_token(agent_id, agent_did):
        out.append(("teg_token", agent_did))
        raise RuntimeError("sentinel: a TEG token was minted for a leg")

    async def resolve(db, did):
        return None, None          # what the resolver answers for a local agent, and for one it cannot place

    monkeypatch.setattr(ti, "_fx_route_origin", fx_route_origin)
    monkeypatch.setattr(ti, "get_teg_token_for_agent", teg_token)
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)
    return out


@pytest.fixture
def gateway(monkeypatch):
    """This node has an FX gateway, as every cloud operator does."""
    monkeypatch.setenv("FX_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_REGISTRY_ID", "registry-sandbox-alpha")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_ROUTER_DID", "did:theprotocol:fx-router-sbxa")


def _transfer(db, receiver=AGENT.did):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_agent] = lambda: AGENT
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    client = TestClient(app, raise_server_exceptions=False)
    return client.post("/api/v1/teg/cross-registry-transfer", json={"receiver_did": receiver, "amount": "0.01"})


def test_a_transfer_to_oneself_on_a_gateway_node_is_refused_before_any_route(reached, gateway):
    db = _Db(native=True)
    r = _transfer(db)
    assert r.status_code == 400, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert "is an agent on this registry" in detail and "/api/v1/teg/transfer" in detail
    assert "(no funds moved)" in detail
    assert reached == [], reached
    assert db.asked == [{"d": AGENT.did}]


def test_another_own_agent_is_refused_the_same_way(reached, gateway):
    r = _transfer(_Db(native=True), receiver="did:theprotocol:sandbox-a.theprotocol.cloud:695f4bf5")
    assert r.status_code == 400 and "is an agent on this registry" in r.json()["detail"], (r.status_code, r.text[:300])
    assert reached == [], reached


def test_without_a_gateway_an_own_agent_is_refused_with_the_new_sentence(reached):
    r = _transfer(_Db(native=True))
    assert r.status_code == 400 and "is an agent on this registry" in r.json()["detail"], (r.status_code, r.text[:300])
    assert reached == [], reached


def test_control_a_receiver_that_is_not_ours_still_goes_into_the_fx_route(reached, gateway):
    r = _transfer(_Db(native=False), receiver="did:theprotocol:sandbox-b.theprotocol.cloud:e3f5ea56")
    assert r.status_code == 418, (r.status_code, r.text[:300])
    assert reached == [("fx_route", "did:theprotocol:sandbox-b.theprotocol.cloud:e3f5ea56")], reached


def test_control_a_receiver_that_is_not_ours_and_no_gateway_is_the_old_refusal(reached):
    r = _transfer(_Db(native=False), receiver="did:theprotocol:nowhere-1")
    assert r.status_code == 400 and "Cannot resolve registry" in r.json()["detail"], (r.status_code, r.text[:300])
    assert reached == [], reached


def test_an_unreadable_answer_refuses_and_moves_nothing(reached, gateway):
    r = _transfer(_Db(native=True, fail=True))
    assert r.status_code == 503, (r.status_code, r.text[:300])
    assert "(no funds moved)" in r.json()["detail"]
    assert reached == [], reached
