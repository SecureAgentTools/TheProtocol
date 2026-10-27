"""SEC-01 (§SECBATCH wave 3, 2026-10-16): a developer credential reads the ledger activity of the agents it created; a
treasury administrator (admin_treasury, or is_admin) reads every account's, on a credential that reaches admin; nobody
else reads anything.

Measured on the base (1032dca8) through these same requests: GET /api/v1/teg/transactions/history/{agent_id} answered
any agent's history, or any developer wallet's (an id built from an e-mail address), to any developer credential;
GET /api/v1/teg/transactions/export and GET /api/v1/teg/transaction/{id} answered every account's transaction events;
the developer listing GET /transactions listed every account's (where the whole application is mounted that path is
answered by the agent route of routers/teg_integration.py, mounted first, which reads the agent's own).

Why no test caught it: the router's tests (test_teg_transactions_present_the_store_key, test_es_path_segments) ran as a
bare developer that owns nothing (`SimpleNamespace(id=7)`) and asserted on the store's key and the path's encoding,
never on whose activity came back; they now run as an administrator, who may read every account.

The routes run through FastAPI on the real router over real (SQLite) rows; only the session, the caller and the store
(an httpx transport answering like the store, recording every request) are supplied.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import teg_transactions as TT
from tests._sqlite_db import sqlite_db

ADMIN, OWNER_A, OWNER_B, NOBODY, TREASURER, ENFORCER = 1, 2, 3, 4, 5, 6
A1 = "did:theprotocol:aaaaaaaa-0000-4000-8000-000000000001"
B1 = "did:theprotocol:bbbbbbbb-0000-4000-8000-000000000002"
WALLET = "did:theprotocol:carol_at_example.com"          # a developer's TEG account id (identifiers.developer_teg_did)
EVENTS = [
    {"id": "e1", "event_type": "TokensTransferred", "aggregate_id": A1, "timestamp": "2026-10-01T10:00:00",
     "data": {"from": A1, "to": B1, "amount": "5", "transaction_id": "tx-ab"}},
    {"id": "e2", "event_type": "TokensTransferred", "aggregate_id": B1, "timestamp": "2026-10-01T11:00:00",
     "data": {"from": B1, "to": WALLET, "amount": "7", "transaction_id": "tx-bw"}},
    {"id": "e3", "event_type": "TokensIssued", "aggregate_id": WALLET, "timestamp": "2026-10-01T12:00:00",
     "data": {"agent_did": WALLET, "amount": "100", "transaction_id": "tx-w"}},
]


class StoreDouble:
    """Answers the reads of the router like the store does, and records every request it receives."""

    def __init__(self):
        self.seen = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.seen.append(path)
        if path.startswith("/api/v1/projections/transactions/"):
            did = path.rsplit("/", 1)[1]
            return httpx.Response(200, json={"agent_did": did, "count": 1, "transactions": [
                {"amount": "5", "details": {"from": did, "to": WALLET}}]})
        if path == "/api/v1/events/":
            return httpx.Response(200, json=EVENTS)
        if path.startswith("/api/v1/events/by-transaction/"):
            tx = path.rsplit("/", 1)[1]
            return httpx.Response(200, json=[e for e in EVENTS if e["data"].get("transaction_id") == tx])
        return httpx.Response(404, json={"detail": "Not Found"})


@pytest.fixture()
def call(monkeypatch):
    db = sqlite_db(models.Developer, models.Agent)
    s = db.sync
    devs = {}
    for i in (ADMIN, OWNER_A, OWNER_B, NOBODY, TREASURER, ENFORCER):
        devs[i] = models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x",
                                   is_admin=(i == ADMIN), admin_treasury=(i == TREASURER),
                                   admin_enforcement=(i == ENFORCER))
        s.add(devs[i])
    s.add(models.Agent(id=1, did=A1, client_id="c1", hashed_client_secret="x", creator_developer_id=OWNER_A))
    s.add(models.Agent(id=2, did=B1, client_id="c2", hashed_client_secret="x", creator_developer_id=OWNER_B))
    s.commit()

    store = StoreDouble()
    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("verify", None)
        return real_client(*args, transport=httpx.MockTransport(store), **kwargs)

    monkeypatch.setattr(TT, "EVENT_STORE_URL", "http://event-store.test:8200")
    monkeypatch.setattr(TT, "EVENT_STORE_KEY", "sec01-test-store-key-not-a-secret")
    monkeypatch.setattr(TT.httpx, "AsyncClient", client_factory)

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(TT.router)
    who = {}

    async def _db():
        yield db

    async def _developer():
        security._PRESENTED_KEY_SCOPES.set(who.get("scopes"))     # as the auth dependency does (None: a JWT)
        return devs[who["dev"]]

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = _developer
    client = TestClient(app, raise_server_exceptions=False)

    def _call(path, dev, scopes=None, **params):
        who.clear()
        who.update({"dev": dev, "scopes": scopes})
        store.seen.clear()
        return client.get(path, params=params or None), list(store.seen)

    return _call


@pytest.mark.parametrize("dev, account, allowed", [
    (OWNER_A, A1, True),         # the agent's owner
    (NOBODY, A1, False),         # the defect: any developer read any agent's history
    (OWNER_B, A1, False),        # an owner of other agents
    (NOBODY, WALLET, False),     # a developer's wallet, whose id is built from an e-mail address
    (OWNER_A, WALLET, False),
    (ENFORCER, A1, False),       # the disputes flag does not read the ledger
    (ADMIN, A1, True),           # control: the administrators read every account
    (TREASURER, B1, True),
    (ADMIN, WALLET, True),
])
def test_an_agents_history_is_read_by_its_owner_and_a_treasury_administrator(call, dev, account, allowed):
    r, seen = call(f"/transactions/history/{account}", dev)
    if allowed:
        assert r.status_code == 200, r.text
        assert r.json()["transactions"], r.json()
    else:
        assert r.status_code == 403, r.text
        assert "owner" in r.text
        assert seen == [], f"the store was read before the refusal: {seen}"


def test_an_administrator_on_a_key_scoped_for_tools_reads_as_a_developer(call):
    r, seen = call(f"/transactions/history/{A1}", ADMIN, scopes=["mcp:tools"])
    assert r.status_code == 403 and seen == [], r.text
    r, _ = call(f"/transactions/history/{A1}", ADMIN, scopes=["*"])          # a full key reaches admin
    assert r.status_code == 200, r.text
    r, seen = call("/transactions/export", ADMIN, scopes=["mcp:tools"])       # the admin owns no agent here
    assert r.status_code == 200 and r.json()["transactions"] == [] and seen == [], r.text


@pytest.mark.parametrize("dev, ids", [
    (OWNER_A, {"e1"}),               # its agent sent e1
    (OWNER_B, {"e1", "e2"}),         # its agent received e1 and sent e2
    (NOBODY, set()),                 # the defect: the export answered every account's events
    (ENFORCER, set()),
    (ADMIN, {"e1", "e2", "e3"}),
    (TREASURER, {"e1", "e2", "e3"}),
])
def test_the_export_holds_the_callers_agents(call, dev, ids):
    r, seen = call("/transactions/export", dev)
    assert r.status_code == 200, r.text
    assert {t["id"] for t in r.json()["transactions"]} == ids
    assert r.json()["total"] == len(ids)
    if not ids and dev in (NOBODY, ENFORCER):
        assert seen == [], "a developer with no agents is answered without reading the store"


@pytest.mark.parametrize("dev, ids", [
    (OWNER_A, {"e1"}),
    (OWNER_B, {"e1", "e2"}),
    (NOBODY, set()),                 # the defect: this developer view listed every account's events
    (ADMIN, {"e1", "e2", "e3"}),
])
def test_the_developer_listing_holds_the_callers_agents(call, dev, ids):
    r, _ = call("/transactions", dev)
    assert r.status_code == 200, r.text
    assert {t["id"] for t in r.json()["transactions"]} == ids


@pytest.mark.parametrize("tx, dev, status", [
    ("tx-ab", OWNER_A, 200),         # a party's owner (the sender's)
    ("tx-ab", OWNER_B, 200),         # (the receiver's)
    ("tx-ab", NOBODY, 403),          # the defect: any developer read any transaction
    ("tx-bw", OWNER_A, 403),         # a transaction between other accounts
    ("tx-w", OWNER_B, 403),
    ("tx-w", ADMIN, 200),
    ("tx-bw", TREASURER, 200),
    ("tx-none", OWNER_A, 404),       # an unknown id stays 404 for a developer who may read some
])
def test_a_transactions_detail_is_read_by_a_partys_owner(call, tx, dev, status):
    r, _ = call(f"/transaction/{tx}", dev)
    assert r.status_code == status, r.text
    if status == 200:
        assert r.json()["transaction_id"] == tx
