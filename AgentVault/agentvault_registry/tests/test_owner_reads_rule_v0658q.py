"""V0658 (q), item 2: the ownership rule the owner's reads follow (services/owner_reads), at the unit level.

A party of a Guild order or a contract is a developer's when he created the agent ("agent"), or when the agent is in
an active organization he owns AND its creator is an active member of that organization ("organization"). An
assignment outlives its creator's membership on purpose (§ORGLIFE L2), so the assignment alone is not the
relationship. There is no treasury road: a treasury is keyless and never holds a seat. `owned_parties` names the
parties per row in two statements for a whole page; the list reads ask `owned_by_sql`, which reads the developer's set
of party DIDs once (an array), never a probe per row. The Guild's deliverable asks `created_a_party` (the agent road)
and `owns_an_organization` (the owner of the organization the work was done for). The rule's semantics on real rows
are tests/test_owner_reads_db.py's.

HEAD 2862d4121 (the first cut): the organization road read the assignment alone (a removed member's agent was named),
a treasury DID was named, the list condition was a correlated EXISTS per row, and neither `created_a_party` nor
`owns_an_organization` existed (the deliverable asked the whole owner rule).
"""
from __future__ import annotations

import asyncio
import re

from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from agentvault_registry.services import owner_reads as R

DEV = 7
A_MINE = "did:theprotocol:eu.test:a-mine"
A_ORG = "did:theprotocol:eu.test:a-org"
A_LEFT = "did:theprotocol:eu.test:a-left"
A_OTHER = "did:theprotocol:eu.test:a-other"
TREASURY = "did:theprotocol:eu.test:org-treasury"


class _R:
    def __init__(self, rows=None, row=None):
        self._rows, self._row = list(rows or []), row

    def first(self):
        return self._row if self._row is not None else (self._rows[0] if self._rows else None)

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self, orgs=(), agents=(), row=None):
        self.orgs, self.agents, self.row, self.sql = list(orgs), list(agents), row, []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append((sql, dict(params or {})))
        if "FROM organizations WHERE owner_id = :dev AND is_active" in sql:
            return _R(rows=self.orgs)
        if "FROM agents a WHERE a.did = ANY" in sql:
            return _R(rows=[a for a in self.agents if a["did"] in params["d"]])
        if "FROM agents WHERE did = ANY" in sql or "FROM organizations WHERE id = ANY" in sql:
            return _R(row=self.row)
        raise AssertionError(f"unexpected statement: {sql[:120]}")


ORGS = [{"id": "org-1", "name": "TheProtocol Sessions", "treasury_agent_did": TREASURY}]
AGENTS = [
    {"did": A_MINE, "creator_developer_id": DEV, "organization_id": "org-1", "creator_is_member": True,
     "name": "session-lead"},
    {"did": A_ORG, "creator_developer_id": 99, "organization_id": "org-1", "creator_is_member": True,
     "name": "session-code"},
    # still assigned to his organization, its creator removed from it (the assignment outlives the membership)
    {"did": A_LEFT, "creator_developer_id": 98, "organization_id": "org-1", "creator_is_member": False,
     "name": "a leaver's agent"},
    {"did": A_OTHER, "creator_developer_id": 99, "organization_id": "org-9", "creator_is_member": True, "name": None},
    # the treasury's keyless agent row: created by someone else, in no organization
    {"did": TREASURY, "creator_developer_id": 99, "organization_id": None, "creator_is_member": None, "name": None},
]


def _run(c):
    return asyncio.run(c)


def test_each_road_names_its_party_and_a_strangers_agent_is_not_named():
    db = _Db(ORGS, AGENTS)
    rows = [{"poster_did": A_MINE, "worker_did": A_OTHER},     # his own agent (also in his organization: "agent" wins)
            {"poster_did": A_OTHER, "worker_did": A_ORG},      # his organization's agent, brought by a member
            {"poster_did": A_OTHER, "worker_did": None}]       # nobody's of his
    got = _run(R.owned_parties(db, DEV, rows, R.GUILD_ROLES))
    assert got[0] == [{"role": "poster", "agent_did": A_MINE, "name": "session-lead", "via": "agent",
                       "organization_id": None, "organization_name": None}]
    assert got[1] == [{"role": "worker", "agent_did": A_ORG, "name": "session-code", "via": "organization",
                       "organization_id": "org-1", "organization_name": "TheProtocol Sessions"}]
    assert got[2] == []
    assert len(db.sql) == 2, "two statements for the whole page, never one per row"


def test_a_removed_members_agent_still_assigned_is_not_named():
    # HEAD 2862d4121: named "via organization" (the assignment alone was read as the relationship)
    got = _run(R.owned_parties(_Db(ORGS, AGENTS), DEV, [{"poster_did": A_LEFT, "worker_did": None}], R.GUILD_ROLES))
    assert got == [[]]


def test_a_treasury_is_not_a_party_of_his():
    # HEAD 2862d4121: named "via organization" by a treasury road; a treasury is keyless and never holds a seat
    got = _run(R.owned_parties(_Db(ORGS, AGENTS), DEV, [{"poster_did": TREASURY, "worker_did": None}],
                               R.GUILD_ROLES))
    assert got == [[]]


def test_the_page_statement_reads_whether_each_agents_creator_is_a_member():
    db = _Db(ORGS, AGENTS)
    _run(R.owned_parties(db, DEV, [{"poster_did": A_ORG, "worker_did": None}], R.GUILD_ROLES))
    (agents_sql, _p), = [(s, p) for s, p in db.sql if "FROM agents a WHERE a.did = ANY" in s]
    assert "FROM organization_members m" in agents_sql and "m.developer_id = a.creator_developer_id" in agents_sql
    assert "m.is_active" in agents_sql and "AS creator_is_member" in agents_sql


def test_both_parties_of_one_contract_can_be_his():
    got = _run(R.owned_parties(_Db(ORGS, AGENTS), DEV, [{"client_did": A_MINE, "provider_did": A_ORG}],
                               R.CONTRACT_ROLES))
    assert [(p["role"], p["via"]) for p in got[0]] == [("client", "agent"), ("provider", "organization")]


def test_no_developer_or_no_party_asks_nothing():
    db = _Db(ORGS, AGENTS)
    assert _run(R.owned_parties(db, None, [{"poster_did": A_MINE}], R.GUILD_ROLES)) == [[]]
    assert _run(R.owned_parties(db, DEV, [{"poster_did": None, "worker_did": None}], R.GUILD_ROLES)) == [[]]
    assert _run(R.created_a_party(db, DEV, [])) is False and _run(R.created_a_party(db, None, [A_MINE])) is False
    assert _run(R.owns_an_organization(db, DEV, [None, ""])) is False
    assert _run(R.owns_an_organization(db, None, ["org-1"])) is False
    assert db.sql == []


def test_the_deliverables_two_questions_are_one_statement_each():
    # HEAD 2862d4121: AttributeError (the deliverable asked the whole owner rule, organizations included)
    assert _run(R.created_a_party(_Db(row=(1,)), DEV, [A_ORG, None])) is True
    db = _Db(row=None)
    assert _run(R.created_a_party(db, DEV, [A_ORG])) is False
    (sql, params), = db.sql
    assert params == {"d": [A_ORG], "dev": DEV}
    assert "creator_developer_id = :dev" in sql and "organization" not in sql and sql.endswith("LIMIT 1")
    db = _Db(row=(1,))
    assert _run(R.owns_an_organization(db, DEV, ["org-1", None, "org-1"])) is True
    (sql, params), = db.sql
    assert params == {"o": ["org-1"], "dev": DEV}
    assert "owner_id = :dev" in sql and "is_active" in sql and sql.endswith("LIMIT 1")


def test_the_list_condition_reads_his_set_once_and_compiles_for_postgres():
    # SQL is pinned by compiling it (the postgresql dialect), never by paging a fixture.
    # HEAD 2862d4121: a correlated EXISTS per row, a treasury road, and no membership condition
    dialect = postgresql.dialect()
    cond = R.owned_by_sql("o.poster_did", "o.worker_did")
    assert "EXISTS" not in cond.split("ARRAY(")[0], "no probe per row: the row's columns meet a set computed once"
    assert "o.poster_did = ANY(ARRAY(" in cond and "o.worker_did = ANY(ARRAY(" in cond
    assert "treasury_agent_did" not in cond, "no treasury road"
    compiled = str(text("SELECT o.id FROM guild_work_orders o WHERE " + cond).compile(dialect=dialect))
    assert "%(dev)s" in compiled
    assert "ag.creator_developer_id = %(dev)s" in compiled
    assert "org.owner_id = %(dev)s AND org.is_active" in compiled, "his active organizations"
    assert "JOIN organization_members mem ON mem.organization_id = org.id" in compiled
    assert "mem.developer_id = ag.creator_developer_id AND mem.is_active" in compiled, \
        "the organization road needs the agent's creator to be an active member of it"
    assert not re.search(r"\bo\.", R.MY_PARTY_DIDS), "the set names no alias of the row's: it cannot depend on it"
