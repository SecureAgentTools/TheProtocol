"""§SUITES1018 batch 7 (2026-10-19): the api-tester's peer-only rows, read against their handlers.

The V0624 sweep (2026-10-18) stamped 17 peer-only rows expected-failure on a 401 "Federation authentication required".
For most of them that said nothing about the route: the sweep had quarantined and blacklisted sbx-alpha's only peer
frame at 21:10:11Z (batch 6c's finding), and every peer-only row after it went out with no identity to speak as. With
the peer protected they carry the internal rail's identity again. What is left here is what that does not reach:

- GET /teg/fx/ledger is a peer-only read whose OpenAPI security names the federation licence first, so the catalog took
  it for a developer route and sent a developer token (overrides.yaml now names it "mtls").
- GET /federation/policy-compliance runs an AAA+ contract, and a contract sends a developer token, an agent token or
  nothing, never a peer's identity: the federation gate alone answered. A peer-only READ now runs no contract.
- the FX hop, the slash request and its confirmation move value, and the agent blocklist acts on a peer's word: each
  read EF on the 401 a tester speaking for no peer met, and spoken as the frame's real peer each would act. They are
  NOT MEASURED before any contract runs, with what they would do.

Every handler named here was read for a write or a freshness stamp first (routers/federation_sync.py,
teg_integration.py, federation_ballots.py, guild.py, exchange_federation.py, federation_blocklist.py).

RED on 1b6c461b (batch 6c): every test_red_* fails there; the test_control_* ones pass on both.
"""
from __future__ import annotations

import asyncio

import httpx

from agentvault_registry.api_tests import base as B
from agentvault_registry.api_tests.core import catalog_sync as CS

PEER = "spiffe://sandbox-b.theprotocol.cloud/service/registry"

ACTS = {
    ("POST", "/teg/fx/route-hop"): "moves_money",
    ("POST", "/federation/disputes/slash-request"): "moves_money",
    ("POST", "/federation/disputes/slash-confirmation"): "moves_money",
    ("POST", "/federation/admin/agents/{agent_did}/block"): "peer_standing",
    ("POST", "/federation/admin/agents/did:theprotocol:abc123/unblock"): "peer_standing",
}


def test_red_the_peer_rails_that_act_are_not_measured_contract_or_not():
    for (m, p), kind in ACTS.items():
        got, why = B._classify_frame_control(m, p)
        assert got == kind and why, (m, p, got)


def test_control_the_peer_reads_beside_them_are_measured():
    for m, p in (("GET", "/teg/fx/ledger"), ("GET", "/federation/fx/ledger"), ("GET", "/federation/policy-compliance"),
                 ("GET", "/federation/sync-watermark"), ("GET", "/federation/disputes/settlements"),
                 ("POST", "/federation/agora-order-status"), ("POST", "/federation/sync-request")):
        assert B._classify_frame_control(m, p) == ("", ""), (m, p)


class _SharedValues(dict):
    async def refresh_from_redis(self):
        return None


class _Wire:
    """Every request the router makes, answered 200 only when it carries the peer's identity on the internal rail."""

    def __init__(self, monkeypatch):
        self.seen = []
        real = httpx.AsyncClient

        def _client(*a, **k):
            k["transport"] = httpx.MockTransport(self._handle)
            return real(*a, **k)
        monkeypatch.setattr(httpx, "AsyncClient", _client)

    def _handle(self, req):
        self.seen.append(req)
        if req.url.path.startswith("/api/v1/federation/") or req.url.path == "/api/v1/teg/fx/ledger":
            if req.headers.get("X-Federation-SPIFFE-ID") != PEER:
                return httpx.Response(401, json={"detail": "Federation authentication required (mTLS certificate, "
                                                           "internal secret, or federation license)"})
            return httpx.Response(200, json={"policy_hash": "abc", "mode": "shadow"})
        return httpx.Response(200, json={"items": []})


def _router(monkeypatch):
    from agentvault_registry.api_tests import auth_manager
    from agentvault_registry.routers import admin_api_test as R
    monkeypatch.setattr(R, "DYNAMIC_VALUES", _SharedValues(peer_id="2", agent_did="did:theprotocol:sweep"))
    monkeypatch.setattr(R, "API_TEST_TARGET_URL", "http://registry-test:8000")
    monkeypatch.setattr(R, "_delegation_target", lambda: None)

    async def _identity(path=""):
        return PEER
    monkeypatch.setattr(auth_manager, "federation_spiffe_id", _identity)
    return R


def test_red_the_router_sends_nothing_for_a_slash_request(monkeypatch):
    R = _router(monkeypatch)
    w = _Wire(monkeypatch)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "POST", "auth": "mtls",
                                                                   "path": "/federation/disputes/slash-request"},
                                      current_developer=None))
    assert out["not_measured"] is True and out["failure_bucket"] == "not_measured_moves_money", out
    assert w.seen == []


def test_red_the_router_sends_nothing_for_a_peers_block_of_an_agent(monkeypatch):
    R = _router(monkeypatch)
    w = _Wire(monkeypatch)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "POST", "auth": "mtls",
                                                                   "path": "/federation/admin/agents/{agent_did}/block"},
                                      current_developer=None))
    assert out["not_measured"] is True and out["failure_bucket"] == "not_measured_peer_standing", out
    assert w.seen == []


def _contracts():
    from agentvault_registry.api_tests.contracts import load_all
    from agentvault_registry.api_tests.core.contract import get_contract
    assert load_all() > 0
    # the contract is registered: what follows is the router's choice, not an empty registry
    assert get_contract("GET", "/federation/policy-compliance") is not None


def test_red_a_peer_only_read_runs_no_contract():
    from agentvault_registry.routers import admin_api_test as R
    _contracts()
    assert R._contract_for("GET", "/federation/policy-compliance") is None


def test_control_a_developer_read_and_a_peer_write_keep_their_contracts():
    from agentvault_registry.routers import admin_api_test as R
    _contracts()
    assert R._contract_for("GET", "/federation/registries") is not None
    # a peer-only WRITE keeps its contract; the slash request is not measured before it is ever reached
    assert R._contract_for("POST", "/federation/disputes/slash-request") is not None


def test_red_the_policy_compliance_read_is_asked_as_the_peer(monkeypatch):
    R = _router(monkeypatch)
    w = _Wire(monkeypatch)
    _contracts()

    async def _catalog(*a, **k):   # the target's catalog names the read a peer route (its OpenAPI: mTLSPeer first)
        return {"federation_synchronization": [{"method": "GET", "path": "/federation/policy-compliance",
                                                "auth": "mtls", "category": "federation_synchronization"}]}
    monkeypatch.setattr(CS, "build_catalog", _catalog)
    out = asyncio.run(R.test_endpoint(request=None, endpoint_test={"method": "GET", "auth": "mtls",
                                                                   "path": "/federation/policy-compliance"},
                                      current_developer=None))
    calls = [r for r in w.seen if r.url.path == "/api/v1/federation/policy-compliance"]
    assert calls and calls[-1].headers.get("X-Federation-SPIFFE-ID") == PEER, [r.url.path for r in w.seen]
    assert out.get("statusCode") == 200 and out.get("healthy") is True and not out.get("expected_failure"), out


def test_red_the_teg_fx_ledger_row_is_a_peer_row():
    ov = CS._load_overrides()
    spec = {"security": [{"FederationLicense": []}, {"DeveloperLogin": []}]}
    assert CS._infer_auth("GET", "/teg/fx/ledger", spec, ov) == "mtls"


def test_control_a_route_beside_it_keeps_the_inferred_auth():
    ov = CS._load_overrides()
    spec = {"security": [{"FederationLicense": []}, {"DeveloperLogin": []}]}
    assert CS._infer_auth("GET", "/teg/fx/rates", spec, ov) == "developer"
    assert CS._infer_auth("GET", "/federation/fx/ledger", {"security": [{"mTLSPeer": []}]}, ov) == "mtls"
