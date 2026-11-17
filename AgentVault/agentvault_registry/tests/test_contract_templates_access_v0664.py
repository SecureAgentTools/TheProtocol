"""V0664 (order gwo_7cd9be62cb545b15e4f6f8f4): who may read and fork a contract template.

  reading   a public or unlisted template (by id) is read by any signed-in caller; a private one by its owner agent, an
            org one by an agent of its organization; a developer reads a private or org template only through an agent
            it owns that may read it, and its "mine" list holds the templates of its own agents only
  the terms a purchase-priced template's version (its terms, schema and milestones: what the template sells) goes to
            the owner and to a buyer (an agent that bought it, or a developer through such an agent); anyone else gets
            402 and the sentence instantiate already says. The detail and its version index stay readable to all who may
            see the template, so a buyer knows what they buy
  forking   copies a version's terms, so a fork of a purchase-priced template needs the owner or a purchase (402
            otherwise, the same sentence); a royalty-priced template, which pays its author on each settled contract,
            forks only for its owner (session-lead, room seq 3785: use it as it is); a free template forks for anyone
            who may see it
Red on v0663/cut b7ca684e9.
"""
from __future__ import annotations

import asyncio
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import contract_templates as ct

OWNER, BUYER, STRANGER, MEMBER = "did:a:owner", "did:a:buyer", "did:a:stranger", "did:a:member"
AGENTS = {  # did: (creator developer, organization)
    OWNER: (1, "org-1"), BUYER: (2, None), STRANGER: (3, None), MEMBER: (4, "org-1"),
}


def tpl(tid, *, visibility="public", pricing="free", price=None):
    return {"id": tid, "slug": tid, "title": tid, "summary": None, "owner_agent_did": OWNER, "source_org_id": "org-1",
            "contract_type": "work_order", "visibility": visibility, "pricing_model": pricing, "price": price,
            "price_currency": "ECU", "royalty_bps": 0, "current_version_id": f"{tid}-v1"}


TEMPLATES = {t["id"]: t for t in (
    tpl("pub-free"), tpl("pub-paid", pricing="purchase", price="5"), tpl("unl", visibility="unlisted"),
    tpl("priv", visibility="private"), tpl("org", visibility="org"),
    tpl("priv-paid", visibility="private", pricing="purchase", price="5"), tpl("pub-royalty", pricing="royalty"),
)}
PURCHASES = {("pub-paid", BUYER)}


class _Res:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def first(self):
        return self.rows[0] if self.rows else None

    def all(self):
        return list(self.rows)

    def scalar(self):
        r = self.first()
        if r is None:
            return None
        return next(iter(r.values())) if isinstance(r, dict) else r[0]


class Db:
    """Answers the router's own statements from the tables above; records the rest."""

    def __init__(self):
        self.stmts, self.commits = [], 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        self.stmts.append((sql, p))
        if sql.startswith("SELECT * FROM contract_templates WHERE id=:t"):
            t = TEMPLATES.get(p["t"])
            return _Res([dict(t)] if t else [])
        if "FROM agents WHERE did=:d" in sql:
            a = AGENTS.get(p["d"])
            return _Res([{"organization_id": a[1]}] if a else [])
        if "FROM agents WHERE creator_developer_id" in sql:
            return _Res([{"did": d, "organization_id": o} for d, (dev, o) in AGENTS.items() if dev == p["dev"]])
        if "FROM contract_template_purchases WHERE template_id=:t AND buyer_did" in sql:
            hit = (p["t"], p["b"]) in PURCHASES
            return _Res([{"id": 1, "price": "5"}] if hit else [])
        if "FROM contract_template_purchases" in sql and "creator_developer_id" in sql:
            hit = any(t == p["t"] and AGENTS.get(b, (None,))[0] == p["dev"] for t, b in PURCHASES)
            return _Res([{"id": 1}] if hit else [])
        if sql.startswith("SELECT * FROM contract_template_versions WHERE template_id=:t AND version=:v"):
            return _Res([{"id": f"{p['t']}-v1", "template_id": p["t"], "version": 1, "terms": {"scope": "the work"},
                          "terms_schema": None, "milestones": None, "suggested_amount": "10",
                          "content_hash": "h", "published_at": "2026-11-14"}])
        if sql.startswith("SELECT * FROM contract_template_versions WHERE id=:v"):
            return _Res([{"id": p["v"], "version": 1, "terms": {"scope": "the work"}, "terms_schema": None,
                          "milestones": None, "suggested_amount": "10", "suggested_currency": "ECU",
                          "suggested_deadline_seconds": None}])
        if "count(*) FILTER" in sql:
            return _Res([(0, 0)])
        if sql.startswith("SELECT id, version, changelog"):
            return _Res([])
        if sql.startswith("SELECT * FROM contract_templates WHERE"):
            return _Res([])
        return _Res([])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        pass


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("CONTRACT_TEMPLATES_ENABLED", "true")


def run(c):
    return asyncio.run(c)


def agent(did):
    return {"kind": "agent", "agent_did": did, "agent": SimpleNamespace(did=did)}


def developer(dev_id):
    return {"kind": "developer", "developer": SimpleNamespace(id=dev_id)}


def status_of(coro):
    try:
        run(coro)
    except HTTPException as e:
        return e.status_code
    return 200


def read(tid, actor):
    return status_of(ct.get_template(tid, actor=actor, db=Db()))


def read_version(tid, actor):
    return status_of(ct.get_template_version(tid, 1, actor=actor, db=Db()))


def fork(tid, did):
    return status_of(ct.fork_template(tid, ct.ForkIn(slug="my-fork"), agent=SimpleNamespace(did=did), db=Db()))


# --- reading -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tid,dev,expect", [
    ("priv", 3, 403), ("org", 3, 403), ("priv-paid", 3, 403),     # a developer whose agents may not read it
    ("priv", 1, 200), ("org", 1, 200),                            # the owner's developer
    ("org", 4, 200),                                              # a developer with an agent in the organization
    ("pub-free", 3, 200), ("unl", 3, 200),                        # the controls: public, and unlisted by id
])
def test_a_developer_reads_a_private_or_org_template_only_through_an_agent_it_owns(tid, dev, expect):
    assert read(tid, developer(dev)) == expect
    assert read_version(tid, developer(dev)) in ((expect,) if expect == 403 else (200,))


@pytest.mark.parametrize("tid,did,expect", [
    ("priv", OWNER, 200), ("org", MEMBER, 200), ("priv", STRANGER, 403), ("org", STRANGER, 403),
    ("pub-free", STRANGER, 200), ("unl", STRANGER, 200),
])
def test_the_controls_for_agents_keep_working(tid, did, expect):
    assert read(tid, agent(did)) == expect


def test_a_developers_mine_list_holds_its_own_agents_templates_only():
    db = Db()
    run(ct.list_templates(mine=True, actor=developer(3), db=db, q=None, contract_type=None, pricing_model=None,
                          limit=20, cursor=None))
    sql, params = next((s, p) for s, p in db.stmts if s.startswith("SELECT * FROM contract_templates WHERE"))
    assert "visibility IN ('public','org','unlisted','private')" not in sql
    assert "creator_developer_id" in sql and params.get("dev") == 3


# --- the terms of a purchase-priced template --------------------------------------------------------------------

@pytest.mark.parametrize("actor,expect", [
    (agent(STRANGER), 402), (developer(3), 402),
    (agent(BUYER), 200), (developer(2), 200),     # a buyer, and a developer through its buying agent
    (agent(OWNER), 200), (developer(1), 200),     # the owner, and the owner's developer
])
def test_a_paid_templates_terms_go_to_the_owner_and_buyers(actor, expect):
    assert read_version("pub-paid", actor) == expect
    assert read("pub-paid", actor) == 200, "the detail and its version index stay readable: a buyer knows what they buy"


def test_the_refusal_is_the_sentence_instantiate_says():
    with pytest.raises(HTTPException) as e:
        run(ct.get_template_version("pub-paid", 1, actor=agent(STRANGER), db=Db()))
    assert e.value.status_code == 402 and "buy it first" in e.value.detail


def test_a_free_templates_terms_go_to_anyone_who_may_see_it():
    assert read_version("pub-free", agent(STRANGER)) == 200


# --- forking -------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("tid,did,expect", [
    ("pub-paid", STRANGER, 402), ("pub-paid", BUYER, 201), ("pub-paid", OWNER, 201),
    ("pub-free", STRANGER, 201),                  # the control: a free template forks for anyone who may see it
    ("priv", STRANGER, 403),
])
def test_a_fork_of_a_paid_template_needs_the_owner_or_a_purchase(tid, did, expect):
    got = fork(tid, did)
    assert (201 if got == 200 else got) == expect


def test_a_refused_fork_writes_nothing():
    db = Db()
    with pytest.raises(HTTPException):
        run(ct.fork_template("pub-paid", ct.ForkIn(slug="my-fork"), agent=SimpleNamespace(did=STRANGER), db=db))
    assert not any(re.match(r"INSERT", s) for s, _ in db.stmts) and db.commits == 0


@pytest.mark.parametrize("did,expect", [(STRANGER, 403), (BUYER, 403), (OWNER, 201)])
def test_a_royalty_priced_template_forks_only_for_its_owner(did, expect):
    got = fork("pub-royalty", did)
    assert (201 if got == 200 else got) == expect


def test_the_royalty_refusal_says_to_use_it_as_it_is():
    db = Db()
    with pytest.raises(HTTPException) as e:
        run(ct.fork_template("pub-royalty", ct.ForkIn(slug="my-fork"), agent=SimpleNamespace(did=STRANGER), db=db))
    assert e.value.status_code == 403 and "royalty" in e.value.detail and "as it is" in e.value.detail
    assert not any(s.startswith("INSERT") for s, _ in db.stmts) and db.commits == 0
