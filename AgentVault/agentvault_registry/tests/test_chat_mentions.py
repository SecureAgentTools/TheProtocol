"""V0650 (h) (2026-10-31, agentvault2-14): server-side @mentions in chat.

Order gwo_2c71fdfcbc1b74d55549ed8d. A message's `@name` tokens resolve to principals of its conversation (an agent's
card name where it is unique, its DID, a member developer's handle), are stored with the message as `mentions`, ship in
every serialized message, and GET .../messages?mentions=me (and MCP readThread mentions="me") reads only the messages
that name the caller, saying so in `applied_filters`. An unknown name is ignored, never an error.

The acceptance: a resolved mention, an unknown name, the filter. The resolver runs on its own; the roster over real
(SQLite) rows; the stored mention through insert_message; the filter as the statement it sends (JSONB containment,
which SQLite does not have); the route and the MCP tool. Cases marked BASE fail on V0649 (6c1f036b), where no resolver,
column or filter exists; the test_control_* cases pass on both trees.
"""
from __future__ import annotations

import datetime
import types
import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.dialects import postgresql

from agentvault_registry import models
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

SCOUT = "did:theprotocol:eu.test:Scout-AGENT-1"
SCOUT2 = "did:theprotocol:eu.test:scout-agent-2"
THEO = "did:theprotocol:eu.test:theo"
THEOBOT = "did:theprotocol:eu.test:theo-bot"
SENDER = "did:theprotocol:eu.test:sender"


def _agent(did, *names):
    return {"key": cs.principal_key("agent", did), "ptype": "agent", "developer_id": None, "agent_did": did,
            "aliases": [("did", did)] + [("name", n) for n in names]}


def _dev(dev_id, handle=None):
    return {"key": cs.principal_key("developer", dev_id), "ptype": "developer", "developer_id": dev_id,
            "agent_did": None, "aliases": [("handle", handle)] if handle else []}


def _keys(found):
    return [m["key"] for m in found]


# ─────────────────────────────── the resolver ───────────────────────────────

def test_a_card_name_resolves_to_its_agent_whatever_its_case():
    # BASE: no resolver
    from agentvault_registry.services.chat_mentions import resolve_mentions
    roster = [_agent(SCOUT, "Scout"), _agent(SENDER, "Sender"), _dev(4, "alice")]
    found = resolve_mentions("@Scout please look", roster, cs.principal_key("agent", SENDER))
    assert found == [{"key": cs.principal_key("agent", SCOUT), "ptype": "agent", "developer_id": None,
                      "agent_did": SCOUT, "token": "Scout"}]
    assert _keys(resolve_mentions("ping @scout", roster, None)) == [cs.principal_key("agent", SCOUT)]


def test_a_handle_resolves_and_an_unknown_name_is_ignored_never_an_error():
    # BASE: no resolver
    from agentvault_registry.services.chat_mentions import resolve_mentions
    roster = [_dev(4, "alice"), _dev(5), _agent(SCOUT, "Scout")]
    assert _keys(resolve_mentions("@alice can you", roster, None)) == ["dev:4"]
    assert resolve_mentions("@nobody and @bob, and Dev Five", roster, None) == []
    assert resolve_mentions("", roster, None) == [] and resolve_mentions("no at sign", roster, None) == []


@pytest.mark.parametrize("body,named", [
    ("mail bob@scout.example", False),
    ("@scouting today", False),
    ("@Scout-team", False),
    ("@Scout:x", False),
    ("(@Scout).", True),
    ("@Scout: look", True),
    ("@Scout", True),
    ("hi@Scout", False),
    ("@@Scout", False),
])
def test_a_name_starts_after_a_separator_and_does_not_run_on(body, named):
    # BASE: no resolver
    from agentvault_registry.services.chat_mentions import resolve_mentions
    found = resolve_mentions(body, [_agent(SCOUT, "Scout")], None)
    assert bool(found) is named, (body, found)


def test_a_shared_card_name_names_nobody_and_the_did_or_a_handle_names_one():
    # BASE: no resolver
    from agentvault_registry.services.chat_mentions import resolve_mentions
    roster = [_agent(SCOUT, "Scout"), _agent(SCOUT2, "Scout")]
    assert resolve_mentions("@Scout hi", roster, None) == []
    assert _keys(resolve_mentions(f"@{SCOUT} hi", roster, None)) == [cs.principal_key("agent", SCOUT)]
    roster = [_agent(SCOUT, "rex"), _dev(9, "rex")]
    assert _keys(resolve_mentions("@rex hi", roster, None)) == ["dev:9"]       # a handle beats an equal card name


def test_the_longest_name_wins_the_sender_is_never_named_and_each_principal_once():
    # BASE: no resolver
    from agentvault_registry.services import chat_mentions as cm
    roster = [_agent(THEO, "Theo"), _agent(THEOBOT, "Theo Bot"), _agent(SENDER, "Sender")]
    assert _keys(cm.resolve_mentions("@Theo Bot hi", roster, None)) == [cs.principal_key("agent", THEOBOT)]
    assert _keys(cm.resolve_mentions("@Theo Botany", roster, None)) == [cs.principal_key("agent", THEO)]
    me = cs.principal_key("agent", SENDER)
    assert cm.resolve_mentions("@Sender note to self", roster, me) == []
    assert _keys(cm.resolve_mentions("@Theo @theo @THEO", roster, None)) == [cs.principal_key("agent", THEO)]
    many = [_agent(f"did:theprotocol:eu.test:a{k}", f"a{k}") for k in range(cm.MENTIONS_MAX + 5)]
    body = " ".join(f"@a{k}" for k in range(cm.MENTIONS_MAX + 5))
    assert len(cm.resolve_mentions(body, many, None)) == cm.MENTIONS_MAX


def test_the_stored_key_is_the_key_the_reader_asks_with():
    # BASE: no resolver
    from agentvault_registry.services.chat_mentions import resolve_mentions
    found = resolve_mentions("@Scout", [_agent(SCOUT, "Scout")], None)
    assert found[0]["key"] == cs.Actor("agent", agent_did=SCOUT).key == "agt:" + SCOUT.lower()
    assert resolve_mentions("@alice", [_dev(4, "alice")], None)[0]["key"] == cs.Actor("developer", developer_id=4).key


# ─────────────────────────────── the roster, over real rows ───────────────────────────────

def _roster_db():
    db = sqlite_db(models.Developer, models.Agent, models.AgentCard, models.Conversation,
                   models.ConversationParticipant)
    s = db.sync
    for i, handle, suspended, deleted in ((4, "alice", False, False), (5, None, False, False),
                                          (6, "gone", True, False), (7, "left", False, False),
                                          (8, "erased", False, True)):
        s.add(models.Developer(id=i, name=f"Dev {i}", email=f"d{i}@example.invalid", hashed_password="x",
                               handle=handle, is_suspended=suspended,
                               deleted_at=datetime.datetime.now(datetime.timezone.utc) if deleted else None))
    for did, name in ((SCOUT, "Scout"), (THEO, "Theo")):
        s.add(models.AgentCard(id=uuid.uuid4(), developer_id=4, card_data={}, name=name, agent_did=did))
    s.add(models.Conversation(id="c1", kind="org", created_by_ptype="developer", created_by_id="4"))
    rows = [("developer", 4, None, "active"), ("developer", 5, None, "active"), ("developer", 6, None, "active"),
            ("developer", 7, None, "left"), ("developer", 8, None, "active"),
            ("agent", None, SCOUT, "active"), ("agent", None, THEO, "pending")]
    for n, (ptype, dev, did, state) in enumerate(rows):
        s.add(models.ConversationParticipant(id=f"p{n}", conversation_id="c1", ptype=ptype, developer_id=dev,
                                             agent_did=did, state=state))
    s.commit()
    return db


async def test_the_roster_is_the_threads_active_and_pending_principals_with_their_names():
    # BASE: no roster
    from agentvault_registry.services.chat_mentions import mention_roster
    roster = {r["key"]: r for r in await mention_roster(_roster_db(), "c1")}
    assert set(roster) == {"dev:4", "dev:5", "dev:6", "dev:8", cs.principal_key("agent", SCOUT),
                           cs.principal_key("agent", THEO)}                   # the left row is no participant
    assert roster["dev:4"]["aliases"] == [("handle", "alice")]
    assert roster["dev:5"]["aliases"] == [] and roster["dev:6"]["aliases"] == []   # no handle; suspended
    assert roster["dev:8"]["aliases"] == []                                     # deleted
    assert ("name", "Scout") in roster[cs.principal_key("agent", SCOUT)]["aliases"]
    assert ("name", "Theo") in roster[cs.principal_key("agent", THEO)]["aliases"]   # a pending row is addressable


# ─────────────────────────────── stored with the message ───────────────────────────────

class _R:
    def __init__(self, v=None, rows=()):
        self.v, self.rows = v, list(rows)

    def scalars(self):
        return self

    def first(self):
        return self.v

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.v[0]


class _InsertDb:
    """Answers insert_message's statements (no duplicate, the next seq) and records every statement and add."""

    def __init__(self):
        self.sql, self.added = [], []

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        self.sql.append(sql)
        if "UPDATE conversations" in sql:
            return _R((5,))
        return _R(None)

    def add(self, o):
        self.added.append(o)

    async def flush(self):
        return None

    async def commit(self):
        return None


def _open_gates(monkeypatch):
    async def _open(*a, **k):
        return None
    monkeypatch.setattr(cs, "room_posting_gate", _open)


CONV = types.SimpleNamespace(id="c1", kind="org", created_by_ptype="developer", created_by_id="4", org_id="org-1")


async def test_a_posted_message_stores_whom_it_mentions_and_ships_it(monkeypatch):
    # BASE: no resolver, no column, no key in the serialized message
    from agentvault_registry.services import chat_mentions as cm
    _open_gates(monkeypatch)
    asked = []

    async def _roster(db, conversation_id):
        asked.append(conversation_id)
        return [_agent(SCOUT, "Scout"), _agent(SENDER, "Sender")]
    monkeypatch.setattr(cm, "mention_roster", _roster)
    db = _InsertDb()
    row = types.SimpleNamespace(state="active", last_read_seq=0)
    msg, dup = await cs.insert_message(db, CONV, row, cs.Actor("agent", agent_did=SENDER), "text",
                                       "hi @Scout and @nobody", None, "ref-mention-0001")
    assert dup is False and asked == ["c1"]
    expected = [{"key": cs.principal_key("agent", SCOUT), "ptype": "agent", "developer_id": None,
                 "agent_did": SCOUT, "token": "Scout"}]
    assert msg.mentions == expected and cs.serialize_message(msg)["mentions"] == expected


@pytest.mark.parametrize("body,rail", [("no names here", False), ("@Scout from the rail", True)])
async def test_control_a_body_without_an_at_or_a_rail_row_reads_no_roster(monkeypatch, body, rail):
    # control: passes on both trees (no participants read beyond insert_message's own statements)
    _open_gates(monkeypatch)
    db = _InsertDb()
    row = types.SimpleNamespace(state="active", last_read_seq=0)
    msg, dup = await cs.insert_message(db, CONV, row, cs.Actor("agent", agent_did=SENDER), "text", body, None,
                                       "ref-mention-0002", rail_author=rail)
    assert dup is False and not any("conversation_participants" in q for q in db.sql), db.sql
    assert getattr(msg, "mentions", None) is None


# ─────────────────────────────── the filter ───────────────────────────────

class _ListDb:
    def __init__(self):
        self.stmts = []

    async def execute(self, stmt, params=None):
        self.stmts.append(stmt)
        return _R(None, rows=[])


def _quiet_reads(monkeypatch):
    conv = types.SimpleNamespace(id="c1", kind="dm", last_seq=3, service_inflight_at=None, retention_hours=None,
                                 dm_pair_key=None, created_by_ptype="agent", created_by_id=SENDER, org_id=None)

    async def _conv(db, cid):
        return conv

    async def _member(db, c, actor, announce_ok=False):
        return types.SimpleNamespace(hidden_before_seq=0, state="active", last_read_seq=0, can_post=True)

    async def _keys(db, actor):
        return {actor.key}

    async def _names(db, keys):
        return {}

    async def _hosting(db, c, parts):
        return {}
    monkeypatch.setattr(cs, "_get_conversation", _conv)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    monkeypatch.setattr(cs, "household_keys", _keys)
    monkeypatch.setattr(cs, "display_names", _names)
    monkeypatch.setattr(cs, "thread_hosting", _hosting)
    monkeypatch.setattr(cs, "pick_counterparty", lambda *a, **k: (None, False))


def _messages_statement(db):
    q = next(s for s in db.stmts if "FROM chat_messages" in str(s))
    return q.compile(dialect=postgresql.dialect())


async def test_mentions_me_reads_only_the_messages_that_name_the_caller(monkeypatch):
    # BASE: list_messages takes no mentions
    _quiet_reads(monkeypatch)
    db = _ListDb()
    actor = cs.Actor("agent", agent_did=SCOUT)
    out = await cs.list_messages(db, "c1", actor, mentions="me")
    compiled = _messages_statement(db)
    assert "chat_messages.mentions @>" in str(compiled) and "chat_messages.mentions IS NOT NULL" in str(compiled)
    assert [{"key": actor.key}] in compiled.params.values()
    assert out["applied_filters"] == {"mentions": "me"}


async def test_control_without_the_filter_the_thread_reads_whole(monkeypatch):
    # control: passes on both trees
    _quiet_reads(monkeypatch)
    db = _ListDb()
    out = await cs.list_messages(db, "c1", cs.Actor("agent", agent_did=SCOUT))
    assert "@>" not in str(_messages_statement(db)) and out.get("applied_filters") is None


async def test_a_filter_other_than_me_is_the_callers_422_before_any_read(monkeypatch):
    # BASE: list_messages takes no mentions
    _quiet_reads(monkeypatch)
    db = _ListDb()
    with pytest.raises(cs.ChatError) as e:
        await cs.list_messages(db, "c1", cs.Actor("agent", agent_did=SCOUT), mentions="everyone")
    assert e.value.status_code == 422 and db.stmts == []


# ─────────────────────────────── the route and the MCP tool ───────────────────────────────

async def test_the_route_hands_the_filter_on_and_refuses_another(monkeypatch):
    # BASE: FastAPI drops the undeclared parameter, so the filter never arrives and "everyone" answers 200
    from agentvault_registry.database import get_db
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.security import get_current_actor_for_read
    seen = []

    async def _list(db, cid, actor, before_seq=None, limit=40, join=False, **kw):
        seen.append(kw.get("mentions"))
        return {"messages": []}
    monkeypatch.setattr(chat_router.cs, "list_messages", _list)
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield None
    app.dependency_overrides[get_db] = _db
    from agentvault_registry import security
    caller = lambda: {"kind": "agent", "agent_did": SCOUT, "agent": types.SimpleNamespace(name="Scout")}
    # the chat read dependency, and (where V0650 (m) is merged) its key-aware successor on the GET routes
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep is not None:
            app.dependency_overrides[dep] = caller
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        ok = await c.get("/api/v1/chat/conversations/c1/messages", params={"mentions": "me"})
        bad = await c.get("/api/v1/chat/conversations/c1/messages", params={"mentions": "everyone"})
        plain = await c.get("/api/v1/chat/conversations/c1/messages")
    assert (ok.status_code, bad.status_code, plain.status_code) == (200, 422, 200)
    assert seen == ["me", None]


def _record(monkeypatch):
    from agentvault_registry.mcp import tools_agent as ta
    calls = []

    async def _req(auth, method, path, json_body=None, params=None, op_name=""):
        calls.append((method, path, params, op_name))
        return {"ok": True}
    monkeypatch.setattr(ta, "_chat_request", _req)
    return ta, calls, types.SimpleNamespace(auth_type="agent", raw_token="x")


async def test_readThread_sends_the_filter_and_advertises_it(monkeypatch):
    # BASE: chat_read_thread takes no mentions; the schema has no such property
    ta, calls, auth = _record(monkeypatch)
    await ta.chat_read_thread(auth, "c1", mentions="me")
    await ta.chat_read_thread(auth, "c1")
    assert calls[0][2] == {"limit": 40, "mentions": "me"} and "mentions" not in calls[1][2]
    from agentvault_registry.mcp import server
    schema = next(s for s in server.ALL_TOOL_SCHEMAS if s["name"] == "theprotocol_readThread")
    assert schema["inputSchema"]["properties"]["mentions"]["enum"] == ["me"]


def test_the_column_and_its_index_are_migrated_and_modelled():
    # BASE: no column, no migration
    import pathlib
    cols = models.ChatMessage.__table__.columns
    assert "mentions" in cols
    assert any(ix.name == "ix_chat_msg_mentioned" for ix in models.ChatMessage.__table__.indexes)
    versions = pathlib.Path(__file__).resolve().parents[1] / "alembic" / "versions"
    adds = [p.name for p in versions.glob("*.py") if 'add_column("chat_messages", sa.Column("mentions"' in p.read_text()]
    assert len(adds) == 1, adds
