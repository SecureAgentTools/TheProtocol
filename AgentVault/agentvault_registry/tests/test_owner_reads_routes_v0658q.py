"""V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), item 2: reading follows ownership.

The maintainer's report (sessions' room seq 2105): he owns the agents on a Guild order and the organization they work
in, and saw nothing of it unless the right agent was selected in the acting-agent switcher. The console's lists of his
work were `GET /guild/mine` and `GET /contracts/v2/mine`, which take an agent token and answer for that ONE agent. Now:

  * `GET /api/v1/guild/owned` and `GET /api/v1/contracts/v2/owned` answer a DEVELOPER token with the work of every
    agent he owns and of every organization he owns, each row naming his parties (`my_parties`); no developer, 401;
  * `/contracts/v2/owned` is its own route, not a contract id the detail route catches;
  * the order detail names a developer reader's parties, and none for anonymous;
  * the deliverable is the parties' and their creators', and the owner's of the organization the work was done for (a
    firm award, `payee_org_id`); the owner of an organization a party agent is in reads the order and is named his
    party, not the work that agent did on its own account.

Writes are untouched: every action still takes the acting agent's token. The rule's semantics on real rows are
tests/test_owner_reads_db.py's. BASE (origin/v0657/cut 553347408): /guild/owned answers 404, /contracts/v2/owned is
taken by the detail route (401 there), the detail carries no my_parties, and the deliverable rule asks only for the
agent's creator. HEAD 2862d4121 (the first cut, before its review): the lists asked a correlated EXISTS per row, and the
deliverable rule asked the whole owner rule, so the organization's owner read the private work of an agent in it and
not the firm's work once its worker had left.
"""
from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.database import get_db
from agentvault_registry.routers import contracts_v2 as C
from agentvault_registry.routers import guild as G
from agentvault_registry.security import (
    get_current_actor_for_read_optional, get_current_developer, get_current_developer_optional,
)

OWNER = 7
MINE = "did:theprotocol:eu.test:mine-agent"          # created by the owner
ORG_AGENT = "did:theprotocol:eu.test:org-agent"      # someone else's agent, in an organization the owner owns
STRANGER = "did:theprotocol:eu.test:stranger-agent"
ORG = "org-sessions"


class _R:
    def __init__(self, rows=None, row=None):
        self._rows, self._row = list(rows or []), row

    def first(self):
        if self._row is not None:
            return self._row
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)

    def mappings(self):
        return self

    def scalar(self):
        r = self.first()
        return r[0] if isinstance(r, (tuple, list)) else r


class _Db:
    """Records every statement; answers from (needle, rows-or-callable) handlers, the first needle the SQL contains."""

    def __init__(self, handlers):
        self.handlers, self.sql = list(handlers), []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append((sql, dict(params or {})))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, params or {}) if callable(res) else _R(rows=res)
        return _R()

    async def commit(self):
        return None

    def statements(self, needle):
        return [(s, p) for s, p in self.sql if needle in s]


ORGS = [{"id": ORG, "name": "TheProtocol Sessions", "treasury_agent_did": None}]
AGENTS = [{"did": MINE, "creator_developer_id": OWNER, "organization_id": None, "creator_is_member": None,
           "name": "session-lead"},
          {"did": ORG_AGENT, "creator_developer_id": 99, "organization_id": ORG, "creator_is_member": True,
           "name": "session-code"},
          {"did": STRANGER, "creator_developer_id": 99, "organization_id": None, "creator_is_member": None,
           "name": "someone"}]
# the two statements that name a page's parties: the developer's active organizations, then the party agents
PARTY_HANDLERS = [("FROM organizations WHERE owner_id = :dev AND is_active",
                   lambda sql, p: _R(rows=ORGS if p.get("dev") == OWNER else [])),
                  ("FROM agents a WHERE a.did = ANY",
                   lambda sql, p: _R(rows=[a for a in AGENTS if a["did"] in (p.get("d") or [])]))]


def _app(db, monkeypatch, dev=None, anonymous=False):
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    monkeypatch.setattr(C, "_require_enabled", lambda: None)
    app = FastAPI()
    app.include_router(G.router)
    app.include_router(C.router)
    app.dependency_overrides[get_db] = lambda: db
    if not anonymous:
        app.dependency_overrides[get_current_developer] = lambda: dev or SimpleNamespace(id=OWNER, is_admin=False)
    return TestClient(app, raise_server_exceptions=False)


# ─────────────────────────────── the owner's lists ───────────────────────────────

def test_the_guild_owned_list_answers_a_developer_with_his_agents_and_his_organizations_orders(monkeypatch):
    # BASE: 404 (no such route; the console asked /guild/mine, one agent's list)
    orders = [{"id": "gwo_a", "poster_did": MINE, "worker_did": STRANGER, "title": "Mine posted", "bounty": "5",
               "currency": "ECU", "status": "open", "created_at": None, "settled_at": None},
              {"id": "gwo_b", "poster_did": STRANGER, "worker_did": ORG_AGENT, "title": "My org works", "bounty": "3",
               "currency": "ECU", "status": "awarded", "created_at": None, "settled_at": None}]
    db = _Db([("FROM guild_work_orders o WHERE", orders)] + PARTY_HANDLERS)
    r = _app(db, monkeypatch).get("/api/v1/guild/owned")
    assert r.status_code == 200, r.text
    got = {o["id"]: o["my_parties"] for o in r.json()["orders"]}
    assert got["gwo_a"] == [{"role": "poster", "agent_did": MINE, "name": "session-lead", "via": "agent",
                             "organization_id": None, "organization_name": None}]
    assert got["gwo_b"] == [{"role": "worker", "agent_did": ORG_AGENT, "name": "session-code", "via": "organization",
                             "organization_id": ORG, "organization_name": "TheProtocol Sessions"}]
    (sql, params), = db.statements("FROM guild_work_orders o WHERE")
    assert params["dev"] == OWNER, "the list is the developer's, by his id"
    # his set of party DIDs, read once, met by each party column (HEAD 2862d4121: a correlated EXISTS per row)
    assert "o.poster_did = ANY(ARRAY(" in sql and "o.worker_did = ANY(ARRAY(" in sql and "EXISTS" not in sql
    assert "org.owner_id = :dev" in sql and "mem.developer_id = ag.creator_developer_id" in sql
    assert "ORDER BY o.created_at DESC, o.id DESC" in sql, "newest first, a unique tiebreak"


def test_the_guild_owned_list_needs_a_developer_token(monkeypatch):
    # BASE: 404 (no such route)
    r = _app(_Db([]), monkeypatch, anonymous=True).get("/api/v1/guild/owned")
    assert r.status_code == 401, r.text


def test_the_contracts_owned_list_is_its_own_route_and_names_the_owners_parties(monkeypatch):
    # BASE: 401 (the detail route takes "owned" for a contract id and asks for an agent or developer reader)
    contracts = [{"id": "ctr_1", "client_did": MINE, "provider_did": STRANGER, "title": "Here", "status": "agreed",
                  "currency": "ECU", "total_amount": Decimal("2.0000000000"), "fee_charged": None,
                  "template_price_paid": None}]
    replicas = [{"cid": "ctr_r", "home_registry": "https://asia.example", "client_did": STRANGER,
                 "provider_did": ORG_AGENT, "title": "There", "currency": "ACU", "total_amount": Decimal("4"),
                 "status": "offered", "stale": False, "updated_at": None, "released_milestones": None}]
    db = _Db([("FROM contracts c WHERE", contracts), ("FROM contract_replicas r WHERE", replicas)]
             + PARTY_HANDLERS)
    r = _app(db, monkeypatch).get("/api/v1/contracts/v2/owned")
    assert r.status_code == 200, r.text
    items = {i["id"]: i for i in r.json()["items"]}
    assert items["ctr_1"]["total_amount"] == "2.0000000000" and not items["ctr_1"].get("replica")
    assert [p["role"] for p in items["ctr_1"]["my_parties"]] == ["client"]
    assert items["ctr_r"]["replica"] is True and items["ctr_r"]["total_amount"] == "4"
    assert items["ctr_r"]["my_parties"] == [{"role": "provider", "agent_did": ORG_AGENT, "name": "session-code",
                                             "via": "organization", "organization_id": ORG,
                                             "organization_name": "TheProtocol Sessions"}]
    for needle, alias in (("FROM contracts c WHERE", "c"), ("FROM contract_replicas r WHERE", "r")):
        (sql, params), = db.statements(needle)
        assert params["dev"] == OWNER and "org.owner_id = :dev" in sql
        assert f"{alias}.client_did = ANY(ARRAY(" in sql and f"{alias}.provider_did = ANY(ARRAY(" in sql
        assert "EXISTS" not in sql, "no probe per row (HEAD 2862d4121: a correlated EXISTS)"


def test_control_the_contracts_owned_list_needs_a_developer_token(monkeypatch):
    # control (both trees): on BASE the detail route answers it (401 there too, as a contract read); here the list
    # refuses on its own, before reading anything
    db = _Db([])
    r = _app(db, monkeypatch, anonymous=True).get("/api/v1/contracts/v2/owned")
    assert r.status_code == 401, r.text
    assert not db.statements("FROM contracts"), "no contract was read for an anonymous caller"


def test_control_the_acting_agents_lists_are_unchanged():
    # control: /guild/mine and /contracts/v2/mine still take the agent token and answer for that agent (both trees)
    from agentvault_registry.security import get_current_agent
    for path in ("/api/v1/guild/mine", "/api/v1/contracts/v2/mine"):
        route = next(r for r in [*G.router.routes, *C.router.routes] if getattr(r, "path", "") == path)
        assert any(d.call is get_current_agent for d in route.dependant.dependencies), path


# ─────────────────────────────── the order detail ───────────────────────────────

ORDER = {"id": "gwo_d", "poster_did": STRANGER, "worker_did": ORG_AGENT, "title": "Delivered", "status": "submitted",
         "currency": "ECU", "bounty": "15", "deliverable": {"report": "the work"}}
# a firm award: the stranger's agent bid as the owner's organization, so the work is paid to it
FIRM_ORDER = dict(ORDER, worker_did=STRANGER, payee_org_id=ORG)


def _detail(monkeypatch, db, dev, order=None):
    async def _load(_db, _oid):
        return json.loads(json.dumps(order or ORDER))
    monkeypatch.setattr(G, "_load", _load)
    monkeypatch.setattr(G, "_require_enabled", lambda: None)
    app = FastAPI()
    app.include_router(G.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_developer_optional] = lambda: dev
    app.dependency_overrides[get_current_actor_for_read_optional] = lambda: None
    r = TestClient(app, raise_server_exceptions=False).get("/api/v1/guild/orders/gwo_d")
    assert r.status_code == 200, r.text
    return r.json()["order"]


def _detail_db():
    def creator_road(sql, p):
        # a row when one of these agents is the developer's: by its creator, the answer a database gives. A statement
        # that also asks the organization road (the first cut's) gets that road's answer too: a party in an
        # organization the developer owns
        dids = set(p.get("d") or [])
        by_creator = any(a["creator_developer_id"] == p.get("dev") for a in AGENTS if a["did"] in dids)
        by_org = ("organization" in sql and p.get("dev") == OWNER
                  and any(a["organization_id"] == ORG for a in AGENTS if a["did"] in dids))
        return _R(row=(1,) if by_creator or by_org else None)

    def owns_org(sql, p):
        return _R(row=(1,) if p.get("dev") == OWNER and ORG in (p.get("o") or []) else None)
    return _Db([("FROM organizations WHERE treasury_agent_did = :p", []),
                ("FROM guild_bids", []), ("FROM guild_order_events", []),
                ("FROM agents WHERE did = ANY", creator_road),
                ("FROM organizations WHERE id = ANY", owns_org),
                # the poster-organization member check (the page statement asks organization_members too)
                ("FROM organization_members WHERE organization_id = :o", [])] + PARTY_HANDLERS)


def test_the_owner_of_the_workers_organization_is_named_his_party_and_reads_the_order_not_its_work(monkeypatch):
    # BASE: no my_parties. HEAD 2862d4121: the deliverable read (the owner of the organization the worker is in read
    # the work it did on its own account)
    o = _detail(monkeypatch, _detail_db(), SimpleNamespace(id=OWNER, is_admin=False))
    assert o["my_parties"] == [{"role": "worker", "agent_did": ORG_AGENT, "name": "session-code",
                                "via": "organization", "organization_id": ORG,
                                "organization_name": "TheProtocol Sessions"}]
    assert o["deliverable"] is None and o["deliverable_withheld"] is True, \
        "the work an agent of a member did on its own account is not the organization's"


def test_the_owner_of_the_firm_reads_the_firms_work_whoever_did_it(monkeypatch):
    # BASE and HEAD 2862d4121: withheld (the worker is no agent of his, and the rule never asked whom the work was for)
    o = _detail(monkeypatch, _detail_db(), SimpleNamespace(id=OWNER, is_admin=False), FIRM_ORDER)
    assert o["deliverable"] == {"report": "the work"} and not o.get("deliverable_withheld")
    assert o["my_parties"] == [], "no party of the firm's order is his: he reads it as the firm's owner"


def test_the_creator_of_the_worker_reads_the_work(monkeypatch):
    # control (both trees): the developer behind a party agent reads its work
    o = _detail(monkeypatch, _detail_db(), SimpleNamespace(id=99, is_admin=False))
    assert o["deliverable"] == {"report": "the work"} and not o.get("deliverable_withheld")


def test_a_stranger_reads_no_work_and_is_told_none_of_the_parties_is_his(monkeypatch):
    # BASE: no my_parties (the work is withheld from him on both trees)
    o = _detail(monkeypatch, _detail_db(), SimpleNamespace(id=123, is_admin=False))
    assert o["deliverable"] is None and o["deliverable_withheld"] is True
    assert o["my_parties"] == [], "a developer reader is told none of the parties is his"
    o = _detail(monkeypatch, _detail_db(), SimpleNamespace(id=123, is_admin=False), FIRM_ORDER)
    assert o["deliverable"] is None and o["deliverable_withheld"] is True, "nor the firm's work"


def test_anonymous_gets_no_parties_at_all(monkeypatch):
    # control (both trees): no developer, no my_parties key
    o = _detail(monkeypatch, _detail_db(), None)
    assert "my_parties" not in o and o["deliverable"] is None
