"""V0662 console polish, item 3 (order gwo_0aa7b875cbf65b6347f5f775): the order page names its parties.

The Guild order page showed every party as fifteen characters of a DID: the poster, the worker, each bidder and each
event's actor. The registry has no batch read of names, and one read per DID is the request storm item 13 removes.
So the order detail answers the names itself: `names`, DID -> the card's name (agent display names live on
agent_cards, which covers local agents and federated mirrors; services/dispute_parties.names_for, the rule the dispute
pages already use), for every DID the answer carries. A DID no card names is null, never a blank, and the console
then shows the DID. Names are public (a direct DID lookup resolves any card), so an anonymous reader gets them too.
Red on f569f6a6e: the answer carries no names.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.routers import guild as G
from agentvault_registry.security import get_current_actor_for_read_optional, get_current_developer_optional

POSTER = "did:theprotocol:eu.test:poster-agent"
WORKER = "did:theprotocol:eu.test:worker-agent"
BIDDER = "did:theprotocol:eu.test:bidder-agent"
NAMELESS = "did:theprotocol:eu.test:no-card-agent"
CARDS = {POSTER: "Harbour Desk", WORKER: "session-code", BIDDER: "Lattice Works"}

ORDER = {"id": "gwo_n", "poster_did": POSTER, "worker_did": WORKER, "title": "Named", "status": "submitted",
         "currency": "ECU", "bounty": "5", "deliverable": None}


class _R:
    def __init__(self, rows=None, row=None):
        self._rows, self._row = list(rows or []), row

    def first(self):
        return self._row if self._row is not None else (self._rows[0] if self._rows else None)

    def all(self):
        return list(self._rows)

    def mappings(self):
        return self


class _Db:
    """Records every statement; answers from (needle, rows-or-callable) handlers, the first needle the SQL contains."""

    def __init__(self, handlers):
        self.handlers, self.sql = list(handlers), []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append((sql, dict(params or {})))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, dict(params or {})) if callable(res) else _R(res)
        return _R([])


def _cards(sql, p):
    asked = set(p.get("d") or [])
    return _R([(did, name) for did, name in CARDS.items() if did.lower() in asked])


def _db():
    return _Db([
        ("FROM organizations WHERE treasury_agent_did = :p", []),
        ("FROM guild_bids", [{"id": 1, "bidder_did": BIDDER, "price": "5", "eta_seconds": 60, "pitch": "", "reputation": 0,
                              "status": "pending", "on_behalf_of_org_id": None, "stake_amount": None,
                              "stake_status": None, "home_registry_url": None, "created_at": "2026-11-13T00:00:00Z"}]),
        ("FROM guild_order_events", [{"seq": 1, "event_type": "posted", "actor_did": POSTER, "payload": {},
                                      "created_at": "2026-11-13T00:00:00Z"},
                                     {"seq": 2, "event_type": "bid", "actor_did": NAMELESS, "payload": {},
                                      "created_at": "2026-11-13T00:01:00Z"}]),
        ("FROM agent_cards WHERE lower(agent_did) = ANY", _cards),
    ])


def _detail(monkeypatch, db, dev=None):
    async def _load(_db, _oid):
        return json.loads(json.dumps(ORDER))

    async def _no_parties(_db, _dev, orders, _roles):
        return [[] for _ in orders]
    monkeypatch.setattr(G, "_load", _load)
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(G.owner_reads, "owned_parties", _no_parties)
    app = FastAPI()
    app.include_router(G.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_developer_optional] = lambda: dev
    app.dependency_overrides[get_current_actor_for_read_optional] = lambda: None
    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/guild/orders/gwo_n")
    assert r.status_code == 200, r.text
    return r.json()


def test_the_order_names_every_party_the_answer_carries(monkeypatch):
    body = _detail(monkeypatch, _db(), SimpleNamespace(id=5, is_admin=False))
    assert body["names"] == {POSTER: "Harbour Desk", WORKER: "session-code", BIDDER: "Lattice Works", NAMELESS: None}


def test_the_names_are_one_read(monkeypatch):
    db = _db()
    _detail(monkeypatch, db)
    assert sum(1 for sql, _ in db.sql if "FROM agent_cards" in sql) == 1, "one read for every party, never one per DID"


def test_an_anonymous_reader_gets_the_names_too(monkeypatch):
    # control for the page being public: the names are the cards', which a direct DID lookup already resolves
    body = _detail(monkeypatch, _db(), None)
    assert body["names"][POSTER] == "Harbour Desk" and body["names"][NAMELESS] is None
