"""§SECBATCH wave 2 (2026-10-16): every Event Store read of routers/teg_transactions.py presents the store's key.

The store authenticates its reads: its balance dumps since D6-200 (wave 1), its per-agent projections since wave 2
(/projections/balance/{did}, /projections/transactions/{did}, /projections/balance/{did}/at/{ts}). Two reads here went
without the key (`require_key=False`): the agent history read /projections/transactions/{did}, and the analytics read
/projections/balances, which the wave-1 store already refuses, so the analytics had shown no balances since. The
existing route tests replace `_es_get` whole, so none of them could see which headers it sends.

What these tests pin, through FastAPI on the real router with the store replaced by an httpx transport that answers like
the gated store (a read without the key is refused 403):
- the agent history comes from the projection, and the projection read carried the key;
- the analytics read the balances with the key, and its list of the largest accounts shows an account whose id is built
  from an e-mail address by its opaque public id (any developer reads that list), an agent DID as it is;
- no read of the router goes to the store without the key.
"""
from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_transactions as TT
from agentvault_registry.security import get_current_developer

KEY = "sec2-test-store-key-not-a-secret"
AGENT = "did:theprotocol:6f1c2a8e-sec2-agent"
WALLET = "did:theprotocol:alice_at_example.com"   # a developer's TEG account id (identifiers.developer_teg_did)
GATED = ("/api/v1/projections/transactions/", "/api/v1/projections/balance/", "/api/v1/projections/balances",
         "/api/v1/events/")


class StoreDouble:
    """Answers like the store: a gated read without the key is refused, as the store does."""

    def __init__(self):
        self.seen = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        key = request.headers.get("X-Internal-Key")
        self.seen.append((request.url.path, key))
        if request.url.path.startswith(GATED) and key != KEY:
            return httpx.Response(403, json={"detail": "Authentication required: provide X-Internal-Key, ..."})
        if request.url.path.startswith("/api/v1/projections/transactions/"):
            return httpx.Response(200, json={"agent_did": AGENT, "count": 1, "transactions": [
                {"amount": "5", "details": {"from": AGENT, "to": "did:theprotocol:someone"}}]})
        if request.url.path == "/api/v1/projections/stats":
            return httpx.Response(200, json={"total_events": 3, "unique_agents": 2,
                                             "event_counts": {"TokensTransferred": 3}})
        if request.url.path == "/api/v1/projections/balances":
            return httpx.Response(200, json={"total_liquid": 150, "total_staked": 0, "agents": [
                {"agent_did": WALLET, "total_balance": 100}, {"agent_did": AGENT, "total_balance": 50}]})
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture()
def store(monkeypatch):
    double = StoreDouble()
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("verify", None)
        return real_client(*args, transport=httpx.MockTransport(double), **kwargs)

    monkeypatch.setattr(TT, "EVENT_STORE_URL", "http://event-store.test:8200")
    monkeypatch.setattr(TT, "EVENT_STORE_KEY", KEY)
    monkeypatch.setattr(TT.httpx, "AsyncClient", client_factory)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(TT.router)
    # SEC-01: an administrator, who reads every account (a bare developer that owns nothing is refused the history)
    app.dependency_overrides[get_current_developer] = lambda: SimpleNamespace(id=7, is_admin=True)
    return TestClient(app, raise_server_exceptions=False), double


def test_the_agent_history_reads_the_projection_with_the_key(store):
    client, double = store
    r = client.get(f"/transactions/history/{AGENT}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("source") == "event_store_projection", body
    assert body["total"] == 1
    reads = [k for p, k in double.seen if p.startswith("/api/v1/projections/transactions/")]
    assert reads == [KEY], double.seen


def test_the_analytics_read_the_balances_with_the_key_and_withhold_personal_ids(store):
    client, double = store
    r = client.get("/transactions/analytics")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["total_liquid_supply"] == "150", body
    top = body["top_agents_by_balance"]
    assert [t["total"] for t in top] == [100, 50]
    assert top[1]["did"] == AGENT                      # an agent DID is shown as it is
    assert top[0]["did"].startswith("account:")        # a developer's account by its opaque public id
    assert "alice" not in r.text and "example.com" not in r.text
    assert ("/api/v1/projections/balances", KEY) in double.seen


def test_no_read_of_the_router_goes_without_the_key(store):
    client, double = store
    client.get(f"/transactions/history/{AGENT}")
    client.get("/transactions/analytics")
    client.get("/transactions")
    assert double.seen, "nothing reached the store double"
    assert all(k == KEY for _, k in double.seen), double.seen
