"""V0658 (s), session-code 2026-11-08: moving an agent into another organization asks first, naming the one it leaves
(order gwo_694b8aeb40cb6b064b564a64; the maintainer's report, sessions' room seq 2150).

An agent belongs to one organization (agents.organization_id). Assigning it to a second organization, or accepting its
join request there, silently took it out of the first: the maintainer did it trying to make one agent owner in two
organizations, and nothing warned him. Both paths go through organizations._attach_agent.

What each test pins:
- the assign route refuses a move out of the organization the agent is in (409, AGENT_IN_ANOTHER_ORGANIZATION) and
  names that organization (name and id) in the answer, through the real router and the real error handlers; nothing
  is written;
- a request that names the organization it leaves (leave_organization_id) moves it, revokes the authority the old
  organization granted it (as before) and answers which organization it left;
- a confirmation naming another organization (a stale one: the agent moved since the console asked) moves nothing and
  names the organization the agent is in now;
- accepting a join request asks the same, and a refused accept leaves the request open (the claim is rolled back);
- the MCP tool carries the confirmation, and its schema says so;
- controls: a direct assignment to the organization the agent is in, and an agent in no organization, need no
  confirmation (unchanged).

The fakes answer by statement text; the route functions, _attach_agent and the error handlers are the real ones.
RED on 553347408 (origin/v0657/cut, the base of (s)).

The review's fixes (the tests under "the review", RED on 6194c8fa0): the refusal's words say the move did not happen
(an MCP caller reads only them, "Error: HTTP 409: ..."); an organization whose row is gone is named as gone, not by
its id dressed up as a name; a confirmation names the organization whatever the case its id is written in; the accept's
audit row names the organization the agent left.

The second review (session-lead, sessions' room seq 2361; the tests under "the second review", RED on f3b3ed22d): an
accept is decided by an administrator of the RECEIVING organization, whom the request list never showed where the agent
is, and an organization that is not listed has not agreed to be named (public_listing is that consent). The accept's
refusal named it anyway. Now it names the organization only when it is listed or the administrator is a member of it;
otherwise it is never named to them, not in the 409's words, not in its error.context, not in the accept's answer or
its audit row, and the move is confirmed with an opaque reference the 409 hands out (an id sent for it confirms
nothing, so a refusal cannot be used to test a guess). Controls: a listed organization, and an administrator who is a
member (or the owner) of it, still see the name; the assign path names it to the agent's creator as before.
"""
from __future__ import annotations

import asyncio
import json
import types

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

ORG_A = "0a6e2f1c-0000-4000-8000-00000000000a"     # where the agent is
ORG_B = "0b6e2f1c-0000-4000-8000-00000000000b"     # where it is assigned
ORG_C = "0c6e2f1c-0000-4000-8000-00000000000c"     # a third one, named by a stale confirmation
ORG_GONE = "0d6e2f1c-0000-4000-8000-00000000000d"  # one the agent still names, whose row is gone
ORG_U = "0e6e2f1c-0000-4000-8000-00000000000e"     # an organization that is not listed
ORG_U2 = "0f6e2f1c-0000-4000-8000-00000000000f"    # another one, not listed either
AGENT = "did:theprotocol:eu.test:5a0e9c1e-77a2-4c39-9a4e-2f0d3b1c9e11"
CODE = "AGENT_IN_ANOTHER_ORGANIZATION"
NAMES = {ORG_A: "Alder Freight", ORG_B: "Birch Ledger", ORG_C: "Cedar Works", ORG_U: "Umber Holdings",
         ORG_U2: "Umbra Logistics"}
LISTED = {ORG_A, ORG_B, ORG_C}                      # these chose to be listed (public_listing); U and U2 did not
OWNERS = {ORG_A: 20, ORG_B: 6, ORG_C: 22, ORG_U: 21, ORG_U2: 23}   # the caller (developer 6) owns B
UNNAMED = "another organization, not listed"


def _slug(oid):
    return NAMES[oid].lower().replace(" ", "-")


class _Result:
    def __init__(self, rows=(), rowcount=None, scalar=None, obj=None):
        self._rows = list(rows)
        self.rowcount = len(self._rows) if rowcount is None else rowcount
        self._scalar = scalar
        self._obj = obj

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    def all(self):
        return list(self._rows)

    def scalar(self):
        if self._scalar is not None:
            return self._scalar
        r = self.first()
        return (r[0] if isinstance(r, (tuple, list)) else r) if r is not None else None

    def scalar_one_or_none(self):
        return self._obj

    def scalars(self):
        return self


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Db:
    """Answers by the first handler whose needle is in the statement; records every statement, commit and rollback."""

    def __init__(self, *handlers):
        self.handlers = list(handlers)
        self.calls = []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.calls.append((sql, dict(params or {})))
        for needle, res in self.handlers:
            if needle in sql:
                return res(sql, dict(params or {})) if callable(res) else res
        return _Result([], rowcount=0)

    def sql(self, needle):
        return [c for c in self.calls if needle in c[0]]

    def begin_nested(self):
        return _Nested()

    async def commit(self):
        self.calls.append(("COMMIT", {}))

    async def rollback(self):
        self.calls.append(("ROLLBACK", {}))

    async def flush(self):
        return None

    def add(self, obj):
        pass

    @property
    def commits(self):
        return sum(1 for c in self.calls if c[0] == "COMMIT")


def _org_row(sql, params):
    """SELECT ... FROM organizations WHERE id = :o, in whichever columns and order the code asks: id, slug, name,
    owner_id, and `listed` (an expression named so: active, and public_listing set). Each is read by its name or its
    alias, the last word of its select item."""
    oid = params.get("o")
    if oid not in NAMES:
        return _Result([])
    head = sql.split("FROM organizations")[0]
    cols = [c.strip().split()[-1] for c in head.replace("SELECT", "", 1).split(",")]
    value = {"id": oid, "slug": _slug(oid), "name": NAMES[oid], "owner_id": OWNERS[oid], "listed": oid in LISTED}
    return _Result([tuple(value.get(c) for c in cols)])


def _agent(org=ORG_A, creator=6):
    return types.SimpleNamespace(did=AGENT, organization_id=org, team_id=None, creator_developer_id=creator,
                                 status="active")


def _db_for(agent):
    return _Db(("FROM agents", _Result(obj=agent)), ("count(", _Result(scalar=0)),
               ("FROM organizations WHERE id", _org_row))


def _org(oid=ORG_B):
    return types.SimpleNamespace(id=oid, slug=NAMES[oid].lower().replace(" ", "-"), name=NAMES[oid], owner_id=6,
                                 is_active=True, settings={}, limits={})


@pytest.fixture
def touches(monkeypatch):
    from agentvault_registry.services import org_mark
    seen = []

    async def agents(db, dids):
        seen.append(tuple(dids))
        return len(dids)
    monkeypatch.setattr(org_mark, "touch_agent_cards_no_commit", agents)
    return seen


@pytest.fixture
def admin_of_b(monkeypatch):
    """The caller (developer 6) is an administrator of the organization in the path, which exists."""
    from agentvault_registry.services.organization_service import OrganizationService

    async def get(db, org_id, **kw):
        return _org(org_id) if org_id in NAMES else None

    async def check(db, org_id, developer_id, required_role=None):
        return True
    monkeypatch.setattr(OrganizationService, "get_organization", staticmethod(get))
    monkeypatch.setattr(OrganizationService, "check_member_permission", staticmethod(check))


def _client(db):
    """The real organizations router and the real error handlers; the session and the caller are the test's."""
    from agentvault_registry import security
    from agentvault_registry.database import get_db
    from agentvault_registry.errors import register_error_handlers
    from agentvault_registry.routers import organizations

    app = FastAPI()
    register_error_handlers(app)
    app.include_router(organizations.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = lambda: types.SimpleNamespace(id=6, email="d@x.invalid")
    # the routes an agent may use too (the join request's accept) take the actor dict; who decides is the `decider`
    # fixture's (organizations._authority)
    app.dependency_overrides[security.get_current_actor_for_read_or_key] = lambda: {
        "kind": "developer", "developer": types.SimpleNamespace(id=6, email="d@x.invalid")}
    return TestClient(app, raise_server_exceptions=False)


def _assign(db, body=None, org=ORG_B):
    url = f"/api/v1/organizations/{org}/agents/{AGENT}/assign"
    return _client(db).post(url, json=body) if body is not None else _client(db).post(url)


def _refusal_names(r, oid):
    """The 409 says which organization the agent is in: the readable detail and the context a console reads."""
    assert r.status_code == 409, r.text[:400]
    j = r.json()
    assert j["error"]["code"] == CODE, j
    assert j["error"]["context"]["current_organization"] == {"id": oid, "name": NAMES[oid]}, j["error"]
    assert NAMES[oid] in j["detail"] and oid in j["detail"], j["detail"]
    assert "leave_organization_id" in j["detail"], "the answer says how to confirm the move"


# ── the assign route ────────────────────────────────────────────────────────────────────────────────────────────────
def test_assigning_an_agent_of_another_organization_is_refused_naming_it(admin_of_b, touches):
    agent = _agent(ORG_A)
    db = _db_for(agent)
    r = _assign(db)
    _refusal_names(r, ORG_A)
    assert agent.organization_id == ORG_A, "the agent stays where it is"
    assert db.commits == 0 and not db.sql("UPDATE agent_delegation_grants"), "nothing is written"
    assert touches == [], "no peer is told it moved"


def test_a_confirmation_naming_the_organization_it_leaves_moves_it(admin_of_b, touches):
    agent = _agent(ORG_A)
    db = _db_for(agent)
    r = _assign(db, {"leave_organization_id": ORG_A})
    assert r.status_code == 200, r.text[:400]
    assert agent.organization_id == ORG_B
    assert r.json()["left_organization_id"] == ORG_A, "the answer says which organization it left"
    revoke = db.sql("UPDATE agent_delegation_grants")
    assert revoke and revoke[0][1]["ref_id"] == f"org:{ORG_A}", "the old organization's authority goes with the move"
    assert db.commits >= 1 and touches == [(AGENT,)]


def test_a_stale_confirmation_cannot_move_it_out_of_a_different_organization(admin_of_b, touches):
    # the console asked while the agent was in C; it is in A now: the confirmation names the wrong organization
    agent = _agent(ORG_A)
    db = _db_for(agent)
    r = _assign(db, {"leave_organization_id": ORG_C})
    _refusal_names(r, ORG_A)
    assert NAMES[ORG_C] not in r.json()["detail"]
    assert agent.organization_id == ORG_A and db.commits == 0 and touches == []


def test_the_team_and_the_confirmation_bind_together(admin_of_b, touches):
    agent = _agent(ORG_A)
    db = _db_for(agent)
    db.handlers.insert(0, ("FROM teams", _Result(obj=types.SimpleNamespace(id="team-1"))))
    r = _assign(db, {"team_id": "team-1", "leave_organization_id": ORG_A})
    assert r.status_code == 200, r.text[:400]
    assert (agent.organization_id, agent.team_id) == (ORG_B, "team-1")
    assert (r.json()["team_id"], r.json()["left_organization_id"]) == ("team-1", ORG_A)


# ── controls: unchanged behaviour (green on the base by design) ─────────────────────────────────────────────────────
def test_control_a_direct_assignment_to_the_organization_it_is_in_is_unchanged(admin_of_b, touches):
    agent = _agent(ORG_B)
    db = _db_for(agent)
    db.handlers.insert(0, ("FROM teams", _Result(obj=types.SimpleNamespace(id="team-2"))))
    r = _assign(db, {"team_id": "team-2"})
    assert r.status_code == 200, r.text[:400]
    assert (agent.organization_id, agent.team_id) == (ORG_B, "team-2")
    assert not db.sql("UPDATE agent_delegation_grants"), "a team move inside one organization revokes nothing"


def test_control_an_agent_in_no_organization_needs_no_confirmation(admin_of_b, touches):
    agent = _agent(None)
    db = _db_for(agent)
    r = _assign(db)
    assert r.status_code == 200, r.text[:400]
    assert agent.organization_id == ORG_B and touches == [(AGENT,)]


# ── accepting a join request ────────────────────────────────────────────────────────────────────────────────────────
def _accept_db(agent, claims):
    db = _db_for(agent)
    db.handlers[:0] = [
        ("SELECT agent_did, status FROM organization_agent_requests", _Result([(AGENT, "pending")])),
        ("UPDATE organization_agent_requests SET status", lambda sql, p: _Result(rowcount=next(claims))),
    ]
    return db


@pytest.fixture
def decider(monkeypatch):
    """An administrator of B (a person) decides; the requester's notice is not sent."""
    from agentvault_registry.routers import organizations as r
    from agentvault_registry.services import org_actor

    async def authority(db, org_id, actor, people, agents=None, *, people_only=False):
        return _org(org_id), types.SimpleNamespace(kind="developer", ref="6", level="admin", developer_id=6,
                                                   developer=types.SimpleNamespace(id=6), agent_did=None)

    audits = []

    async def audit(db, who, action, org_id, **kw):
        audits.append((action, str(org_id), kw))
        return None
    monkeypatch.setattr(r, "_authority", authority)
    monkeypatch.setattr(r, "_tell_requester", lambda *a, **k: None)
    monkeypatch.setattr(org_actor, "audit", audit)
    return audits


def _accept(db, body):
    from agentvault_registry.routers import organizations as r
    actor = {"kind": "developer", "developer": types.SimpleNamespace(id=6)}
    return asyncio.run(r.accept_agent_request(actor=actor, org_id=ORG_B, request_id="oar_1", body=body, db=db))


def test_accepting_a_join_request_of_an_agent_in_another_organization_asks_first(decider, touches):
    from agentvault_registry.routers import organizations as r
    agent = _agent(ORG_A)
    db = _accept_db(agent, iter([1, 1]))
    with pytest.raises(HTTPException) as e:
        _accept(db, r.AgentRequestDecision())
    assert e.value.status_code == 409 and getattr(e.value, "error_code", None) == CODE
    assert e.value.context["current_organization"] == {"id": ORG_A, "name": NAMES[ORG_A]}
    assert NAMES[ORG_A] in e.value.detail and ORG_A in e.value.detail
    assert agent.organization_id == ORG_A and touches == []
    claim = max(i for i, c in enumerate(db.calls) if c[0].startswith("UPDATE organization_agent_requests"))
    assert ("ROLLBACK", {}) in db.calls[claim:], "the claim is undone: the request stays open for a confirmed accept"
    assert db.commits == 0


def test_an_accept_that_names_the_organization_it_leaves_brings_the_agent_in(decider, touches):
    from agentvault_registry.routers import organizations as r
    agent = _agent(ORG_A)
    db = _accept_db(agent, iter([1, 1]))
    with pytest.raises(HTTPException):
        _accept(db, r.AgentRequestDecision())                         # asked first
    out = _accept(db, r.AgentRequestDecision(leave_organization_id=ORG_A))
    assert out["status"] == "accepted" and agent.organization_id == ORG_B
    assert touches == [(AGENT,)] and db.commits >= 1


def test_an_accept_naming_another_organization_moves_nothing(decider, touches):
    from agentvault_registry.routers import organizations as r
    agent = _agent(ORG_A)
    db = _accept_db(agent, iter([1]))
    with pytest.raises(HTTPException) as e:
        _accept(db, r.AgentRequestDecision(leave_organization_id=ORG_C))
    assert e.value.status_code == 409 and e.value.context["current_organization"]["id"] == ORG_A
    assert agent.organization_id == ORG_A and db.commits == 0


# ── the MCP tool ────────────────────────────────────────────────────────────────────────────────────────────────────
def test_the_mcp_tool_carries_the_confirmation_and_its_schema_says_so(monkeypatch):
    from agentvault_registry.mcp import tools_developer as T
    sent = []

    async def req(auth, method, path, **kw):
        sent.append((method, path, kw.get("json_body")))
        return {"ok": True}
    monkeypatch.setattr(T, "_dev_request", req)
    asyncio.run(T.assign_agent_to_org(object(), ORG_B, AGENT, leave_organization_id=ORG_A))
    asyncio.run(T.assign_agent_to_org(object(), ORG_B, AGENT))
    assert sent[0][2] == {"leave_organization_id": ORG_A}
    assert sent[1][2] is None, "without a confirmation the request is the one it always was"
    schema = next(s for s in T.DEVELOPER_TOOL_SCHEMAS if s["name"] == "theprotocol_assignAgentToOrg")
    prop = schema["inputSchema"]["properties"]["leave_organization_id"]
    assert prop["type"] == "string" and prop["maxLength"] == 255
    assert "leave_organization_id" not in schema["inputSchema"]["required"]
    assert "one organization" in schema["description"]


# ── the review (V0658 (s), RED on 6194c8fa0) ────────────────────────────────────────────────────────────────────────
def test_the_refusal_says_the_move_did_not_happen(admin_of_b, touches):
    # an MCP caller reads only these words ("Error: HTTP 409: ..."): they must not read as a move already made
    db = _db_for(_agent(ORG_A))
    r = _assign(db)
    _refusal_names(r, ORG_A)
    detail = r.json()["detail"]
    assert "would take it out of Alder Freight; nothing was changed" in detail, detail
    assert "this moves it" not in detail, detail


def test_an_organization_whose_row_is_gone_is_named_as_gone(admin_of_b, touches):
    agent = _agent(ORG_GONE)
    db = _db_for(agent)
    r = _assign(db)
    assert r.status_code == 409, r.text[:400]
    j = r.json()
    assert j["error"]["code"] == CODE
    assert j["error"]["context"]["current_organization"] == {"id": ORG_GONE, "name": None}
    assert f"an organization that no longer exists (id {ORG_GONE})" in j["detail"], j["detail"]
    assert f"the organization {ORG_GONE}" not in j["detail"], "an id is not dressed up as a name"
    assert agent.organization_id == ORG_GONE and db.commits == 0 and touches == []


def test_a_confirmation_names_the_organization_whatever_the_case_of_its_id(admin_of_b, touches):
    agent = _agent(ORG_A)
    db = _db_for(agent)
    r = _assign(db, {"leave_organization_id": ORG_A.upper()})
    assert r.status_code == 200, r.text[:400]
    assert agent.organization_id == ORG_B and r.json()["left_organization_id"] == ORG_A


def test_the_accept_audit_names_the_organization_the_agent_left(decider, touches):
    from agentvault_registry.routers import organizations as r
    agent = _agent(ORG_A)
    db = _accept_db(agent, iter([1]))
    out = _accept(db, r.AgentRequestDecision(leave_organization_id=ORG_A))
    assert out["left_organization_id"] == ORG_A
    accepted = [kw for action, _org, kw in decider if action == "agent_request_accepted"]
    assert accepted and accepted[0]["details"] == {"request_id": "oar_1", "left_organization_id": ORG_A}, decider


def test_control_an_accept_that_moves_nothing_audits_as_before(decider, touches):
    from agentvault_registry.routers import organizations as r
    agent = _agent(None)
    db = _accept_db(agent, iter([1]))
    out = _accept(db, r.AgentRequestDecision())
    assert out["status"] == "accepted" and out["left_organization_id"] is None
    accepted = [kw for action, _org, kw in decider if action == "agent_request_accepted"]
    assert accepted and accepted[0]["details"] == {"request_id": "oar_1"}, decider


# ── the second review (session-lead, sessions' room seq 2361; RED on f3b3ed22d) ─────────────────────────────────────
OTHER_AGENT = "did:theprotocol:eu.test:0b0b0b0b-1111-4222-8333-444455556666"   # an agent administrator of B


def _accept_http(db, body=None):
    """The accept as a console sends it: the real route and the real error handlers, so the 409's words and its
    error.context are read as the caller receives them."""
    return _client(db).post(f"/api/v1/organizations/{ORG_B}/agent-requests/oar_1/accept", json=body or {})


def _says_nothing_of(text, oid):
    """`text` names the organization `oid` in no form: its id (as written, without its hyphens, in any case), its name,
    its slug."""
    low = text.lower()
    for form in (oid, oid.replace("-", ""), NAMES.get(oid), _slug(oid) if oid in NAMES else None):
        if form:
            assert form.lower() not in low, (form, text[:600])


def _audited_accepts(audits):
    return [kw for action, _org, kw in audits if action == "agent_request_accepted"]


@pytest.fixture
def agent_decides(monkeypatch, decider):
    """An agent administrator of B decides: org_actor gives an agent authority only in the organization it belongs to,
    and an agent belongs to one."""
    from agentvault_registry.routers import organizations as r

    async def authority(db, org_id, actor, people, agents=None, *, people_only=False):
        return _org(org_id), types.SimpleNamespace(kind="agent", ref=OTHER_AGENT, level="admin", developer_id=None,
                                                   developer=None, agent_did=OTHER_AGENT)
    monkeypatch.setattr(r, "_authority", authority)
    return decider


def test_an_unlisted_organization_is_never_named_to_another_organizations_administrator(decider, touches):
    # B's administrator decides; Umber Holdings is not listed and they are not a member of it: no form of it is said
    agent = _agent(ORG_U)
    db = _accept_db(agent, iter([1]))
    r = _accept_http(db)
    assert r.status_code == 409, r.text[:400]
    j = r.json()
    assert j["error"]["code"] == CODE, j
    _says_nothing_of(r.text, ORG_U)          # the whole answer: its words (detail, error.detail) and its error.context
    assert f"The agent is in {UNNAMED}." in j["detail"] and "nothing was changed" in j["detail"], j["detail"]
    context = j["error"]["context"]
    assert context["current_organization"] == {"id": None, "name": None, "label": UNNAMED}, context
    reference = context.get("confirm_value")
    assert isinstance(reference, str) and reference, "the refusal hands out what confirms the move"
    assert f"send leave_organization_id {reference} with the request" in j["detail"], "the words say how to confirm"
    assert agent.organization_id == ORG_U and db.commits == 0 and touches == []


def test_the_reference_confirms_the_move_and_neither_the_answer_nor_the_audit_row_names_it(decider, touches):
    agent = _agent(ORG_U)
    db = _accept_db(agent, iter([1, 1]))
    reference = _accept_http(db).json()["error"]["context"].get("confirm_value")
    assert isinstance(reference, str) and reference, "the refusal hands out what confirms the move"
    r = _accept_http(db, {"leave_organization_id": reference})
    assert r.status_code == 200, r.text[:400]
    assert agent.organization_id == ORG_B and touches == [(AGENT,)]
    revoke = db.sql("UPDATE agent_delegation_grants")
    assert revoke and revoke[0][1]["ref_id"] == f"org:{ORG_U}", "the old organization's authority goes with the move"
    _says_nothing_of(r.text, ORG_U)
    out = r.json()
    assert (out["status"], out["left_organization_id"], out.get("left_organization_ref")) == (
        "accepted", None, reference), out
    accepted = _audited_accepts(decider)
    assert accepted and accepted[0]["details"] == {"request_id": "oar_1", "left_organization_ref": reference}, decider
    _says_nothing_of(json.dumps(accepted, default=str), ORG_U)


def test_an_id_sent_for_it_cannot_be_tested_against_it(decider, touches):
    # where the organization is not named, only the reference confirms: its id (known from elsewhere) and another
    # organization's get the same answer, so a refusal cannot confirm a guess, and neither moves the agent
    agent = _agent(ORG_U)
    db = _accept_db(agent, iter([1, 1]))
    right = _accept_http(db, {"leave_organization_id": ORG_U})
    wrong = _accept_http(db, {"leave_organization_id": ORG_C})
    assert (right.status_code, wrong.status_code) == (409, 409), (right.text[:300], wrong.text[:300])
    assert right.json()["detail"] == wrong.json()["detail"]
    assert right.json()["error"]["context"] == wrong.json()["error"]["context"]
    _says_nothing_of(right.text, ORG_U)
    assert agent.organization_id == ORG_U and db.commits == 0 and touches == []


def test_a_reference_for_one_organization_does_not_move_it_out_of_another(decider, touches):
    # the agent moved to another unlisted organization after the refusal: the reference confirmed that move only, so it
    # moves nothing now, and the new refusal hands out the reference of the move it would be
    agent = _agent(ORG_U)
    db = _accept_db(agent, iter([1, 1]))
    first = _accept_http(db).json()["error"]["context"].get("confirm_value")
    assert isinstance(first, str) and first, "the refusal hands out what confirms the move"
    agent.organization_id = ORG_U2
    r = _accept_http(db, {"leave_organization_id": first})
    assert r.status_code == 409, r.text[:400]
    _says_nothing_of(r.text, ORG_U2)
    _says_nothing_of(r.text, ORG_U)
    now = r.json()["error"]["context"]["confirm_value"]
    assert isinstance(now, str) and now and now != first
    assert agent.organization_id == ORG_U2 and db.commits == 0 and touches == []


def test_an_organization_whose_row_is_gone_is_not_named_to_another_organizations_administrator(decider, touches):
    # listed nowhere and with no members: an accept's refusal says nothing of it, not even its id
    agent = _agent(ORG_GONE)
    db = _accept_db(agent, iter([1]))
    r = _accept_http(db)
    assert r.status_code == 409, r.text[:400]
    _says_nothing_of(r.text, ORG_GONE)
    assert r.json()["error"]["context"]["current_organization"] == {"id": None, "name": None, "label": UNNAMED}
    assert agent.organization_id == ORG_GONE and db.commits == 0


def test_an_agent_administrator_is_not_told_an_unlisted_organization(agent_decides, touches):
    # an agent decides as an agent of B, and an agent belongs to one organization: it is a member of no other
    agent = _agent(ORG_U)
    db = _accept_db(agent, iter([1]))
    db.handlers.insert(0, ("SELECT a.creator_developer_id", _Result([(6, "Courier")])))   # whose agent decides
    r = _accept_http(db)
    assert r.status_code == 409, r.text[:400]
    _says_nothing_of(r.text, ORG_U)
    assert agent.organization_id == ORG_U and db.commits == 0


def test_the_refusal_hands_out_the_id_where_it_names_the_organization(admin_of_b, decider, touches):
    # a console confirms with what the refusal hands out: where it names the organization, that is its id
    assigned = _assign(_db_for(_agent(ORG_U)))
    assert assigned.json()["error"]["context"].get("confirm_value") == ORG_U, assigned.text[:400]
    accepted = _accept_http(_accept_db(_agent(ORG_A), iter([1])))
    assert accepted.json()["error"]["context"].get("confirm_value") == ORG_A, accepted.text[:400]


# ── the second review's controls: who may be told still is (green on f3b3ed22d by design) ───────────────────────────
def test_control_a_listed_organization_is_named_to_the_administrator(decider, touches):
    # Alder Freight chose to be listed: its name is no secret, and the accept names it as before
    agent = _agent(ORG_A)
    db = _accept_db(agent, iter([1, 1]))
    _refusal_names(_accept_http(db), ORG_A)
    r = _accept_http(db, {"leave_organization_id": ORG_A})
    assert r.status_code == 200 and r.json()["left_organization_id"] == ORG_A, r.text[:400]
    assert agent.organization_id == ORG_B


@pytest.mark.parametrize("how", ["an active member", "its owner"])
def test_control_an_administrator_who_belongs_to_it_is_told_which(decider, touches, monkeypatch, how):
    # Umber Holdings is not listed, but the administrator deciding is in it: they know it, and the accept names it
    agent = _agent(ORG_U)
    db = _accept_db(agent, iter([1, 1]))
    if how == "its owner":
        monkeypatch.setitem(OWNERS, ORG_U, 6)
    else:
        db.handlers.insert(0, ("FROM organization_members", lambda sql, p: _Result(
            [("member",)] if (p.get("o"), p.get("d")) == (ORG_U, 6) else [])))
    _refusal_names(_accept_http(db), ORG_U)
    r = _accept_http(db, {"leave_organization_id": ORG_U})
    assert r.status_code == 200 and r.json()["left_organization_id"] == ORG_U, r.text[:400]
    accepted = _audited_accepts(decider)
    assert accepted and accepted[0]["details"] == {"request_id": "oar_1", "left_organization_id": ORG_U}, decider


def test_control_the_assign_path_names_an_unlisted_organization_to_the_agents_creator(admin_of_b, touches):
    # the assign's caller is the agent's creator, who knows where the agent is: the assign path is as it was
    agent = _agent(ORG_U)
    db = _db_for(agent)
    _refusal_names(_assign(db), ORG_U)
    r = _assign(db, {"leave_organization_id": ORG_U})
    assert r.status_code == 200 and r.json()["left_organization_id"] == ORG_U, r.text[:400]


# ── the third review (session-lead, sessions' room seq 2415; RED on e5bcba1f8) ──────────────────────────────────────
def test_an_agent_that_hides_its_organization_does_not_have_it_named(decider, touches):
    # Alder Freight is listed, but the agent does not show it (show_org False): being named to another organization
    # takes the same consent as the public mark, the organization listed AND the agent showing it
    agent = _agent(ORG_A)
    agent.show_org = False
    db = _accept_db(agent, iter([1, 1]))
    r = _accept_http(db)
    assert r.status_code == 409, r.text[:400]
    _says_nothing_of(r.text, ORG_A)
    context = r.json()["error"]["context"]
    assert context["current_organization"] == {"id": None, "name": None, "label": UNNAMED}, context
    moved = _accept_http(db, {"leave_organization_id": context["confirm_value"]})
    assert moved.status_code == 200 and agent.organization_id == ORG_B, moved.text[:400]


def test_control_an_agent_that_shows_its_listed_organization_has_it_named(decider, touches):
    agent = _agent(ORG_A)
    agent.show_org = True
    _refusal_names(_accept_http(_accept_db(agent, iter([1]))), ORG_A)


def test_a_move_without_a_team_leaves_the_old_organizations_team_behind(admin_of_b, touches):
    # the agent was in a team of Alder Freight: moved into B with no team named, it is in no team, not in A's
    agent = _agent(ORG_A)
    agent.team_id = "team-of-alder"
    r = _assign(_db_for(agent), {"leave_organization_id": ORG_A})
    assert r.status_code == 200, r.text[:400]
    assert (agent.organization_id, agent.team_id) == (ORG_B, None)


def test_control_an_assignment_inside_its_organization_without_a_team_keeps_its_team(admin_of_b, touches):
    agent = _agent(ORG_B)
    agent.team_id = "team-of-b"
    r = _assign(_db_for(agent))
    assert r.status_code == 200, r.text[:400]
    assert agent.team_id == "team-of-b"


def test_a_failed_revoke_logs_its_class_and_not_its_parameters(admin_of_b, touches, caplog):
    import logging

    class _GrantRevokeFailed(Exception):
        pass

    def fail(sql, params):
        raise _GrantRevokeFailed(f"connection was closed\n[SQL: {sql}]\n[parameters: {params}]")

    agent = _agent(ORG_A)
    db = _db_for(agent)
    db.handlers.insert(0, ("UPDATE agent_delegation_grants", fail))
    with caplog.at_level(logging.WARNING):
        r = _assign(db, {"leave_organization_id": ORG_A})
    assert r.status_code == 200 and agent.organization_id == ORG_B, r.text[:400]
    said = " ".join(rec.getMessage() for rec in caplog.records if "prev-org grant revoke failed" in rec.getMessage())
    assert "_GrantRevokeFailed" in said and "connection was closed" in said, said
    assert _slug(ORG_A) not in said and ORG_A not in said and "[parameters" not in said, said
