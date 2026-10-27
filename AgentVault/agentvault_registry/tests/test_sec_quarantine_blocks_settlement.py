"""D6-801 (2026-10-17): a peer this registry holds in quarantine takes part in no movement of money with it.

A compliance quarantine (federated_registry_compliance.federation_status) was recorded, announced and listed, and no
money path read it: its only effect was the RegistryQuarantined reactor's removal of the peer from the TEG's partner
list, which the next cross-registry leg re-added (every leg names its target TEG to the local TEG). Now the money paths
ask before anything moves: the cross-registry transfer (A2A settlement and /teg/send come through it), the FX booth,
every FX route leg (which is what names a target TEG), and the FX route hop for the registry presenting the route.

Through FastAPI on the real TEG router. Doubles: the database session (it answers the compliance read with the
quarantined rows), the receiver's home resolution (cards and the federation crawl), and the steps after the refusal
point that would reach the TEG, each replaced by a sentinel that records it was reached. RED on b49fc6ad: every case
that expects a refusal (the base reaches the sentinel instead).
"""
from __future__ import annotations

import json
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.core import federation_auth
from agentvault_registry.database import get_db
from agentvault_registry.routers import teg_integration as ti

LISBON = ("Lisbon", "eu.theprotocol.cloud", "cloud_operator", "quarantined")
ASIA = ("ASIA", "asia.theprotocol.cloud", "frame", "quarantined")
ROUTER_DID = "did:theprotocol:fx-router-eu"


class _Res:
    def __init__(self, rows=(), one=None):
        self._rows, self._one = list(rows), one

    def all(self):
        return list(self._rows)

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return types.SimpleNamespace(all=lambda: [], first=lambda: None)

    def scalar(self):
        return 0

    def first(self):
        return None


class _Db:
    """The compliance read answers the quarantined rows (or fails), the @fx_router lookup answers the router agent,
    anything else answers nothing (the receiver is no agent of this registry: V0639's native-agent read)."""

    def __init__(self, quarantined=(), router=None, fail=False):
        self.quarantined, self.router, self.fail = list(quarantined), router, fail

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "federated_registry_compliance" in sql:
            if self.fail:
                raise RuntimeError("database unreachable")
            return _Res(rows=self.quarantined)
        if "is_federated_mirror IS NOT TRUE" in sql:
            return _Res()
        if "FROM agents" in sql:
            return _Res(one=self.router)
        return _Res()

    async def commit(self):
        return None

    async def rollback(self):
        return None


AGENT = types.SimpleNamespace(id=11, did="did:theprotocol:payer-1", mtls_enabled=False, spiffe_id=None, status="active")
ROUTER = types.SimpleNamespace(id=12, did=ROUTER_DID, mtls_enabled=False, spiffe_id=None, status="active")


@pytest.fixture
def reached(monkeypatch):
    """Sentinels on the first steps past each refusal point: each records that the money path got there."""
    out = []

    async def teg_token(agent_id, agent_did):
        out.append(("teg_token", agent_did))
        raise RuntimeError("sentinel: a TEG token was minted for a leg")

    async def peer_currency(db, target_peer=None):
        out.append(("currency", getattr(target_peer, "name", None)))
        raise HTTPException(status_code=418, detail="sentinel: the transfer went on to choose its rail")

    async def dest_teg(target_teg_id, target_registry_id):
        out.append(("dest_teg", target_registry_id))
        raise HTTPException(status_code=418, detail="sentinel: the swap dialed the destination TEG")

    async def refund(db, router_agent, router_did, origin_did, amount, route_id, **kw):
        out.append(("refund", origin_did))
        return True

    monkeypatch.setattr(ti, "get_teg_token_for_agent", teg_token)
    monkeypatch.setattr(ti, "_resolve_peer_currency", peer_currency)
    monkeypatch.setattr(ti, "_resolve_dest_teg_mtls_base", dest_teg)
    monkeypatch.setattr(ti, "_fx_route_refund_to_origin", refund)
    return out


def _home(monkeypatch, teg_id, registry_id):
    async def resolve(db, did):
        return teg_id, registry_id
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)


@pytest.fixture
def reachable(monkeypatch):
    """The federation crawl knows registry-lisbon, so a transfer the quarantine does not stop goes on to its rail."""
    async def bfs(db):
        return [{"name": "registry-lisbon"}]
    from agentvault_registry.routers import agent_locations
    monkeypatch.setattr(agent_locations, "_compute_trusted_registries", bfs)


def _client(db, presenter=None):
    app = FastAPI()
    app.include_router(ti.router, prefix="/api/v1")

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_agent] = lambda: AGENT
    app.dependency_overrides[security.verify_agent_token] = lambda: {}
    if presenter is not None:
        app.dependency_overrides[federation_auth.require_peer_registry_identity] = lambda: presenter
    return TestClient(app, raise_server_exceptions=False)


def _transfer(db):
    return _client(db).post("/api/v1/teg/cross-registry-transfer",
                            json={"receiver_did": "did:theprotocol:payee-lisbon", "amount": "5"})


# ── the cross-registry transfer (A2A settlement and /teg/send reach it) ────────────────────────────────────────────

def test_a_transfer_to_a_quarantined_registry_is_refused_before_anything_moves(monkeypatch, reached, reachable):
    _home(monkeypatch, "teg-layer-lisbon", "registry-lisbon")
    r = _transfer(_Db(quarantined=[LISBON]))
    assert r.status_code == 403, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert "Lisbon is quarantined" in detail and "(no funds moved)" in detail
    assert reached == [], reached


def test_control_a_transfer_to_a_registry_in_good_standing_goes_on(monkeypatch, reached, reachable):
    _home(monkeypatch, "teg-layer-lisbon", "registry-lisbon")
    r = _transfer(_Db(quarantined=[ASIA]))   # another registry is quarantined, not this one
    assert r.status_code == 418, (r.status_code, r.text[:300])
    assert reached == [("currency", None)], reached


def test_a_blacklisted_registry_is_refused_too(monkeypatch, reached, reachable):
    _home(monkeypatch, "teg-layer-lisbon", "registry-lisbon")
    r = _transfer(_Db(quarantined=[("Lisbon", "eu.theprotocol.cloud", "cloud_operator", "blacklisted")]))
    assert r.status_code == 403 and "Lisbon is blacklisted" in r.json()["detail"], (r.status_code, r.text[:300])
    assert reached == [], reached


def test_an_unreadable_compliance_state_refuses_and_moves_nothing(monkeypatch, reached, reachable):
    _home(monkeypatch, "teg-layer-lisbon", "registry-lisbon")
    r = _transfer(_Db(quarantined=[LISBON], fail=True))
    assert r.status_code == 503, (r.status_code, r.text[:300])
    assert "(no funds moved)" in r.json()["detail"]
    assert reached == [], reached


# ── an FX route leg (here the origin's ingress into its gateway) ────────────────────────────────────────────────────

def test_no_fx_route_leg_goes_to_a_quarantined_gateway(monkeypatch, reached):
    _home(monkeypatch, None, None)   # the receiver is unresolvable here: the route goes through the gateway
    monkeypatch.setenv("FX_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_REGISTRY_ID", "registry-lisbon")
    monkeypatch.setenv("FX_ROUTE_GATEWAY_ROUTER_DID", "did:theprotocol:fx-router-lisbon")
    r = _transfer(_Db(quarantined=[LISBON]))
    assert r.status_code == 409, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert "FX route ingress failed (no funds moved)" in detail and "Lisbon is quarantined" in detail, detail
    assert reached == [], reached   # no TEG token minted, no partner added, nothing sent


# ── the FX route hop ───────────────────────────────────────────────────────────────────────────────────────────────

HOP = {"route_id": "6b1c0a58-1111-4b0e-9c3e-1d2a3b4c5d6e", "final_receiver_did": "did:theprotocol:payee-x",
       "amount": "4.975", "hop_budget": 4, "origin_did": "did:theprotocol:payer-lisbon",
       "origin_registry_id": "registry-lisbon", "origin_teg_id": "teg-layer-lisbon"}


@pytest.fixture
def hop_env(monkeypatch):
    monkeypatch.setenv("FX_ROUTE_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTER_DID", ROUTER_DID)


def test_a_route_presented_by_a_quarantined_registry_goes_no_further(monkeypatch, reached, hop_env):
    went_on = []

    async def resolve(db, did):
        went_on.append(did)
        raise HTTPException(status_code=418, detail="sentinel: the hop went on to deliver")
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)
    r = _client(_Db(quarantined=[LISBON], router=ROUTER),
                presenter="spiffe://eu.theprotocol.cloud/operator/lisbon/registry").post(
        "/api/v1/teg/fx/route-hop", json=HOP)
    assert r.status_code == 403, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert "Lisbon is quarantined" in detail and "(origin refunded)" in detail, detail
    assert went_on == [], went_on
    assert reached == [("refund", HOP["origin_did"])], reached   # the ingress goes back through the one refund path


def test_control_a_route_from_a_registry_in_good_standing_goes_on(monkeypatch, reached, hop_env):
    went_on = []

    async def resolve(db, did):
        went_on.append(did)
        raise HTTPException(status_code=418, detail="sentinel: the hop went on to deliver")
    monkeypatch.setattr(ti, "_resolve_receiver_registry", resolve)
    r = _client(_Db(quarantined=[ASIA], router=ROUTER),
                presenter="spiffe://eu.theprotocol.cloud/operator/lisbon/registry").post(
        "/api/v1/teg/fx/route-hop", json=HOP)
    assert r.status_code == 418, (r.status_code, r.text[:300])
    assert went_on == [HOP["final_receiver_did"]] and reached == [], (went_on, reached)


def test_a_hop_does_not_deliver_to_a_receiver_on_a_quarantined_registry(monkeypatch, reached, hop_env):
    _home(monkeypatch, "teg-layer-lisbon", "registry-lisbon")

    async def currency(db, target_peer=None):
        return None   # same currency as this frame: the terminal 1:1 egress
    monkeypatch.setattr(ti, "_resolve_peer_currency", currency)
    r = _client(_Db(quarantined=[LISBON], router=ROUTER),
                presenter="spiffe://asia.theprotocol.cloud/service/registry").post(
        "/api/v1/teg/fx/route-hop", json={**HOP, "origin_registry_id": "registry-shenzhen",
                                          "origin_teg_id": "teg-layer-shenzhen"})
    assert r.status_code == 409, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert "FX route egress failed" in detail and "Lisbon is quarantined" in detail, detail
    assert ("teg_token", ROUTER_DID) not in reached, reached   # the egress leg was never sent
    assert reached == [("refund", HOP["origin_did"])], reached


def test_a_hop_converts_nothing_into_a_quarantined_frame(monkeypatch, reached, hop_env):
    _home(monkeypatch, "teg-layer-asiaop", "registry-asiaop")

    async def currency(db, target_peer=None):
        return "ACU"
    monkeypatch.setattr(ti, "_resolve_peer_currency", currency)
    monkeypatch.setattr(ti, "_local_frame_currency", lambda: "ECU")
    monkeypatch.setenv("FX_ENABLED", "true")
    monkeypatch.setenv("FX_ROUTE_PEERS", json.dumps([{"currency": "ACU", "registry_id": "registry-asia",
                                                      "teg_id": "teg-layer-asia", "router_did": "did:theprotocol:fx-router-asia",
                                                      "url": "https://asia.example.test"}]))

    async def gd_peer(db, registry_id):
        return types.SimpleNamespace(name="ASIA", trust_domain="asia.theprotocol.cloud", base_url="https://asia.example.test")

    async def no_ledger_refusal(gd, peer):
        return None
    monkeypatch.setattr(ti, "_fx_route_find_active_peer", gd_peer)
    monkeypatch.setattr(ti, "_fx_route_gd_ledger_refusal", no_ledger_refusal)
    r = _client(_Db(quarantined=[ASIA], router=ROUTER),
                presenter="spiffe://eu.theprotocol.cloud/operator/amsterdam/registry").post(
        "/api/v1/teg/fx/route-hop", json={**HOP, "origin_registry_id": "registry-amsterdam",
                                          "origin_teg_id": "teg-layer-amsterdam"})
    assert r.status_code == 409, (r.status_code, r.text[:300])
    detail = r.json()["detail"]
    assert "core swap failed" in detail and "ASIA is quarantined" in detail and "(origin refunded)" in detail, detail
    assert not any(k == "dest_teg" for k, _ in reached), reached   # the swap never dialed ASIA's TEG
    assert reached == [("refund", HOP["origin_did"])], reached
