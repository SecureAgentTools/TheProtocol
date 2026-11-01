"""V0651 (o) (2026-10-31, agentvault2-14): an approval from the chat as the production word, bound to one act.

Order gwo_b81bd6234ac6d6b30b1f9759. The acceptance asked for a test per refusal (not approved, wrong decider, expired,
wrong sha256, already consumed) and the pass. Beside those: only the agent that asked may use it, an approval asked
without production_impact opens no production act, one that names no artifact opens nothing, a lost race writes
nothing and says why, the use is recorded once and shown by GET /chat/approvals/{id}, the room gets one line under the
approval card, and the route takes an agent credential only.

Pure rules are tested directly; the route through FastAPI on the real chat router, with only the database, the
conversation lookup and the post-commit line writer replaced (the pattern of test_chat_approvals.py). Each case marked
BASE fails on 48d07ecf2 (V0650), where neither the route, the rule nor the columns exist.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

NOW = dt.datetime(2026, 10, 31, 17, 0, 0, tzinfo=dt.timezone.utc)
ORG = "org-sessions"
CONV = "conv-room-1"
OWNER = 6
APPROVER = 7
MEMBER = 8
AGENT = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-000000000001"
OTHER = "did:theprotocol:eu.theprotocol.cloud:00000000-0000-4000-8000-000000000002"
SHA = "ab" * 32
SHA2 = "cd" * 32


def _row(aid="apr_c1", status="approved", minutes=60, production=True, sha=SHA, decider=OWNER, role="owner",
         consumed=None):
    r = SimpleNamespace(
        id=aid, conversation_id=CONV, org_id=ORG, requester_agent_did=AGENT, client_ref=f"ref-{aid}",
        request_message_id=f"msg-{aid}", title=f"Roll {aid}", reason=None, unlocks=None,
        artifact_sha256=sha, artifact_label="run_prod651.sh", production_impact=production,
        facts={"approval_id": aid}, facts_digest="d" * 64, status=status,
        created_at=NOW - dt.timedelta(minutes=5), expires_at=NOW + dt.timedelta(minutes=minutes),
        decided_at=NOW - dt.timedelta(minutes=1) if status in ("approved", "denied") else None,
        decided_by_developer_id=decider if status in ("approved", "denied") else None,
        decided_by_role=role if status in ("approved", "denied") else None, decision_note=None, decision_via=None,
        presence_method=None, presence_challenge_id=None, decision_statement=None,
        consumed_at=None, consumed_by_agent_did=None, consumed_act=None, consumed_act_sha256=None)
    if consumed:
        r.consumed_at, r.consumed_by_agent_did, r.consumed_act, r.consumed_act_sha256 = consumed
    return r


# ---------------------------------------------------------------------------
# The rule: why an approval may not open an act, first reason first
# ---------------------------------------------------------------------------

def _refuse(row, *, agent=AGENT, sha=SHA, role="owner", production=True):
    # BASE: AttributeError (no consume_refusal on V0650)
    from agentvault_registry.services import chat_approvals as ca
    return ca.consume_refusal(row, agent_did=agent, act_sha256=sha, now=NOW, role=role, production=production)


def test_the_pass_an_approved_unused_unexpired_production_approval_naming_this_act():
    assert _refuse(_row()) is None
    assert _refuse(_row(role="approver"), role="approver") is None
    assert _refuse(_row(production=False), production=False) is None      # a non-production act may use either


@pytest.mark.parametrize("status", ["pending", "denied", "expired"])
def test_not_approved_opens_nothing(status):
    code, sentence = _refuse(_row(status=status))
    assert code == 409 and f"is {status}, not approved" in sentence


def test_a_pending_request_past_its_expiry_reads_as_expired():
    code, sentence = _refuse(_row(status="pending", minutes=-1))
    assert code == 409 and "is expired, not approved" in sentence


def test_an_approved_request_past_its_expiry_opens_nothing():
    code, sentence = _refuse(_row(minutes=-1))
    assert code == 409 and "expired at" in sentence


def test_wrong_decider_a_decider_who_no_longer_owns_or_approves_opens_nothing():
    for role in (None, "member"):
        code, sentence = _refuse(_row(), role=role)
        assert code == 403 and "no longer owns this organization or approves for it" in sentence


def test_wrong_sha256_opens_nothing():
    code, sentence = _refuse(_row(), sha=SHA2)
    assert code == 409 and SHA[:12] in sentence and SHA2[:12] in sentence and "nothing opened" in sentence


def test_an_approval_that_names_no_artifact_opens_nothing():
    code, sentence = _refuse(_row(sha=None))
    assert code == 409 and "names no artifact" in sentence


def test_already_consumed_names_the_act_it_opened():
    used = (NOW - dt.timedelta(minutes=2), AGENT, "V0651 production roll", SHA)
    code, sentence = _refuse(_row(consumed=used))
    assert code == 409 and "already used" in sentence and "V0651 production roll" in sentence
    assert "One approval opens one act" in sentence


def test_only_the_agent_that_asked_may_use_it():
    code, sentence = _refuse(_row(), agent=OTHER)
    assert code == 403 and AGENT in sentence
    assert _refuse(_row(), agent=AGENT.upper()) is None                   # a DID compares case-insensitively


def test_an_approval_asked_without_production_impact_opens_no_production_act():
    code, sentence = _refuse(_row(production=False))
    assert code == 409 and "without production_impact" in sentence


def test_no_record_answers_404():
    assert _refuse(None) == (404, "approval request not found")


def test_an_earlier_use_is_named_before_the_status_and_the_asker_before_the_use():
    used = (NOW, AGENT, "V0651 production roll", SHA)
    assert _refuse(_row(consumed=used, status="approved", minutes=-1))[0] == 409
    assert "already used" in _refuse(_row(consumed=used, minutes=-1))[1]
    assert _refuse(_row(consumed=used), agent=OTHER)[0] == 403


def test_the_record_shows_its_one_use():
    # BASE: KeyError 'consumed' (serialize names no use on V0650)
    from agentvault_registry.services import chat_approvals as ca
    assert ca.serialize(_row(), NOW)["consumed"] is None
    used = ca.serialize(_row(consumed=(NOW, AGENT, "V0651 production roll", SHA)), NOW)["consumed"]
    assert used == {"at": NOW.isoformat(), "by_agent_did": AGENT, "act": "V0651 production roll", "act_sha256": SHA}
    old = SimpleNamespace(**{k: v for k, v in vars(_row()).items() if not k.startswith("consumed")})
    assert ca.serialize(old, NOW)["consumed"] is None                     # a row read before 0202 names no use


# ---------------------------------------------------------------------------
# The route, through FastAPI on the real chat router
# ---------------------------------------------------------------------------

class _R:
    def __init__(self, first=None, scalar=None):
        self._first, self._scalar = first, scalar

    def first(self):
        return self._first

    def scalar_one(self):
        return self._scalar


class _DB:
    """Answers the statements the consume path sends, by their text; anything else fails the test loudly. `race`
    makes the UPDATE find the row already used (another driver won between the read and the write)."""

    def __init__(self, rows, members=None, race=False):
        self.rows = {r.id: r for r in rows}
        self.members = members or {}
        self.race = race
        self.updated = []
        self.commits = self.rollbacks = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        p = dict(params or {})
        if sql.startswith("SELECT now()"):
            return _R(scalar=NOW)
        if "FROM organization_members" in sql:
            return _R(first=self.members.get(int(p["d"])))
        if sql.startswith("UPDATE chat_approvals SET consumed_at"):
            assert "consumed_at IS NULL" in sql and "status = 'approved'" in sql and "expires_at > now()" in sql
            assert "artifact_sha256 = :s" in sql and "lower(requester_agent_did) = lower(:a)" in sql
            r = self.rows.get(p["id"])
            if self.race and r is not None:
                r.consumed_at, r.consumed_by_agent_did, r.consumed_act, r.consumed_act_sha256 = (
                    NOW, AGENT, "the other driver's act", SHA)
            if (r is None or r.consumed_at is not None or r.status != "approved" or r.expires_at <= NOW
                    or r.artifact_sha256 != p["s"] or r.requester_agent_did.lower() != p["a"].lower()):
                return _R(first=None)
            r.consumed_at, r.consumed_by_agent_did, r.consumed_act, r.consumed_act_sha256 = NOW, p["a"], p["l"], p["s"]
            self.updated.append(p["id"])
            return _R(first=(NOW,))
        raise AssertionError(f"unexpected statement: {sql[:120]}")

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


@pytest.fixture()
def consume(monkeypatch):
    """The chat router with the room, the org and the line writer replaced; returns a caller."""
    from agentvault_registry.database import get_db
    from agentvault_registry.errors import register_error_handlers
    from agentvault_registry.routers import chat
    from agentvault_registry.security import get_current_agent
    from agentvault_registry.services import admin_audit
    from agentvault_registry.services import chat_approvals as ca
    from agentvault_registry.services import chat_service as cs

    state = {"lines": [], "audit": [], "state": "active"}

    async def _conv(db, cid):
        return SimpleNamespace(id=cid, kind="org", org_id=ORG, host_registry=None, mode="open")

    async def _membership(db, conv, actor, **kw):
        return SimpleNamespace(state=state["state"], can_post=True)

    async def _org(db, org_id):
        return {"owner_id": OWNER, "chat_enabled": True, "settings": {}}

    async def _fetch(db, aid, fresh=False):
        return db.rows.get(aid)

    async def _names(db, rows):
        return ({AGENT: "session-release"}, {OWNER: "Commander"})

    async def _insert(db, conv, my_row, sender, kind, body, card, client_ref, reply_to=None, **kw):
        state["lines"].append({"kind": kind, "body": body, "card": card, "client_ref": client_ref,
                               "reply_to": reply_to, "rail_author": kw.get("rail_author")})
        return SimpleNamespace(id="m-" + client_ref), False

    async def _recipients(db, conv, sender):
        return []

    async def _audit(db, **kw):
        state["audit"].append(kw)

    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _membership)
    monkeypatch.setattr(cs, "insert_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"id": m.id})
    monkeypatch.setattr(cs, "recipients_snapshot", _recipients)
    monkeypatch.setattr(cs, "deliver", lambda *a, **kw: None)
    monkeypatch.setattr(ca, "org_facts", _org)
    monkeypatch.setattr(ca, "fetch", _fetch)
    monkeypatch.setattr(ca, "names_for", _names)
    monkeypatch.setattr(admin_audit, "log_chat_action", _audit)
    monkeypatch.delenv("CHAT_APPROVALS_ENABLED", raising=False)

    def call(db, body, *, agent=AGENT, aid="apr_c1"):
        app = FastAPI()
        register_error_handlers(app)
        app.include_router(chat.router)
        app.dependency_overrides[get_db] = lambda: db
        app.dependency_overrides[get_current_agent] = lambda: SimpleNamespace(did=agent, name="session-release")
        return TestClient(app, raise_server_exceptions=False).post(f"/api/v1/chat/approvals/{aid}/consume", json=body)
    call.state = state
    return call


def _body(sha=SHA, label="V0651 production roll", production=True):
    return {"act_label": label, "act_sha256": sha, "production": production}


def test_the_pass_records_the_use_once_and_posts_one_line_under_the_card(consume):
    # BASE: 404 (no consume route on V0650)
    db = _DB([_row()], members={})
    r = consume(db, _body())
    assert r.status_code == 200, (r.status_code, r.text)
    used = r.json()["approval"]["consumed"]
    assert used == {"at": NOW.isoformat(), "by_agent_did": AGENT, "act": "V0651 production roll", "act_sha256": SHA}
    assert db.updated == ["apr_c1"] and db.commits == 1
    (line,) = consume.state["lines"]
    assert line["kind"] == "text" and line["reply_to"] == "msg-apr_c1" and line["client_ref"] == "aprused-apr_c1"
    assert line["rail_author"] is True and "opened one act: V0651 production roll" in line["body"]
    (audit,) = consume.state["audit"]
    assert audit["action"] == "approval.consumed" and audit["target_id"] == "apr_c1"
    assert audit["details"]["act_sha256"] == SHA and audit["details"]["role"] == "owner"


def test_a_named_approver_s_decision_opens_the_act_too(consume):
    db = _DB([_row(decider=APPROVER, role="approver")], members={APPROVER: ("member", True)})
    assert consume(db, _body()).status_code == 200


def test_a_second_use_is_refused_naming_the_first_act(consume):
    db = _DB([_row()])
    assert consume(db, _body()).status_code == 200
    r = consume(db, _body(label="another act"))
    assert r.status_code == 409 and "already used" in r.text and "V0651 production roll" in r.text
    assert db.updated == ["apr_c1"] and len(consume.state["lines"]) == 1


def test_a_lost_race_writes_nothing_and_says_the_other_act_won(consume):
    db = _DB([_row()], race=True)
    r = consume(db, _body())
    assert r.status_code == 409 and "the other driver's act" in r.text, r.text
    assert db.updated == [] and db.rollbacks == 1 and consume.state["lines"] == [] and consume.state["audit"] == []


@pytest.mark.parametrize("row,body,agent,code,words", [
    (_row(status="pending"), _body(), AGENT, 409, "not approved"),
    (_row(status="denied"), _body(), AGENT, 409, "not approved"),
    (_row(minutes=-1), _body(), AGENT, 409, "expired at"),
    (_row(), _body(sha=SHA2), AGENT, 409, "nothing opened"),
    (_row(decider=MEMBER, role="approver"), _body(), AGENT, 403, "no longer owns"),
    (_row(production=False), _body(), AGENT, 409, "without production_impact"),
    (_row(), _body(), OTHER, 403, "only the agent that asked"),
])
def test_every_refusal_writes_nothing(consume, row, body, agent, code, words):
    db = _DB([row], members={MEMBER: ("member", False)})
    r = consume(db, body, agent=agent)
    assert r.status_code == code and words in r.text, (r.status_code, r.text)
    assert db.updated == [] and db.commits == 0 and consume.state["lines"] == []


def test_a_malformed_sha256_is_refused_before_anything_is_read(consume):
    db = _DB([_row()])
    r = consume(db, _body(sha="z" * 64))
    assert r.status_code == 422 and db.updated == []


def test_an_agent_no_longer_active_in_the_room_opens_nothing(consume):
    consume.state["state"] = "left"
    db = _DB([_row()])
    r = consume(db, _body())
    assert r.status_code == 409 and "not active" in r.text and db.updated == []


def test_the_consume_route_takes_an_agent_credential_only():
    # BASE: KeyError (no consume route on V0650)
    from agentvault_registry.routers import chat
    from agentvault_registry.security import get_current_agent, get_current_developer
    paths = {(tuple(sorted(r.methods)), r.path): r for r in chat.router.routes}
    route = paths[(("POST",), "/api/v1/chat/approvals/{approval_id}/consume")]
    calls, todo = set(), list(route.dependant.dependencies)
    while todo:
        d = todo.pop()
        calls.add(d.call)
        todo.extend(d.dependencies)
    assert get_current_agent in calls and get_current_developer not in calls


# ---------------------------------------------------------------------------
# The MCP tool and the migration
# ---------------------------------------------------------------------------

def test_the_mcp_tool_is_tier_2_audited_categorized_listed_and_contracted():
    # BASE: KeyError / AssertionError (no consumeChatApproval on V0650)
    from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
    from agentvault_registry.mcp import audit, server
    from agentvault_registry.mcp.tool_categories import get_category
    name = "theprotocol_consumeChatApproval"
    assert server.TOOL_DISPATCH[name].__name__ == "consume_chat_approval"
    assert name in server.TIER2_TOOLS and name in server.AUTH_REQUIRED_TOOLS and name not in server.TIER3_TOOLS
    assert name in audit._TIER_2_TOOLS
    assert get_category(name) == "account"
    schema = next(t for t in server.ALL_TOOL_SCHEMAS if t["name"] == name)
    assert schema["inputSchema"]["required"] == ["approval_id", "act_label", "act_sha256"]
    assert MCP_CONTRACTS[name].expect_error_message_contains == "approval request not found"


def test_migration_0202_adds_the_four_use_columns_after_0201():
    # BASE: the file does not exist on V0650
    p = (pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0202_chat_approval_consumed.py")
    spec = importlib.util.spec_from_file_location("m0202", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.revision == "0202_chat_approval_consumed" and len(m.revision) <= 32
    assert m.down_revision == "0201_chat_message_mentions"
    src = p.read_text()
    for col in ("consumed_at", "consumed_by_agent_did", "consumed_act", "consumed_act_sha256"):
        assert f'"{col}"' in src
