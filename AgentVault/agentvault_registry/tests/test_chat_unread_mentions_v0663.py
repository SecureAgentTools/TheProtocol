"""V0663 (order 418, his request seq 3349): the conversation list says how many unread messages name the caller.

The statement is read as PostgreSQL would run it (JSONB containment is not SQLite's); the helper's three answers (a count per
room, an empty set, None when the read failed: a count that could not be taken is not a zero); the list's wiring to it; and
the bell's own read of the caller's unread mentions (GET /api/v1/chat/mentions)."""
from __future__ import annotations

import types

import pytest
from sqlalchemy.dialects import postgresql

from agentvault_registry.services import chat_service as cs

DEV = cs.Actor("developer", developer_id=6, display_name="him")
AGENT = cs.Actor("agent", agent_did="did:theprotocol:eu.test:Scout-1", display_name="Scout")


def _compiled(actor, floors):
    c = cs.unread_mention_stmt(actor, floors).compile(dialect=postgresql.dialect())
    return " ".join(str(c).split()), c.params


def test_the_statement_counts_mentions_of_the_caller_above_each_rooms_mark_not_deleted_not_its_own():
    sql, params = _compiled(DEV, {"room-a": 4, "room-b": 0})
    assert "chat_messages.mentions @>" in sql
    assert [{"key": "dev:6"}] in params.values()                          # the caller's own stored key, nothing else
    assert sql.count("chat_messages.conversation_id =") == 2 and sql.count("chat_messages.seq >") == 2
    vals = list(params.values())
    assert "room-a" in vals and "room-b" in vals and 4 in vals and 0 in vals
    assert "chat_messages.deleted_at IS NULL" in sql
    assert "NOT (chat_messages.sender_ptype = " in sql and "chat_messages.sender_id = " in sql
    assert "developer" in params.values() and "6" in params.values()      # not its own line
    assert "GROUP BY chat_messages.conversation_id" in sql


def test_an_agents_own_messages_are_excluded_by_its_did_whatever_the_case():
    sql, params = _compiled(AGENT, {"r": 1})
    assert "lower(chat_messages.sender_id) = " in sql
    assert "did:theprotocol:eu.test:scout-1" in params.values() and "agent" in params.values()
    assert [{"key": AGENT.key}] in params.values()


def test_all_and_everyone_are_not_a_mention_of_the_caller():
    # the statement asks the stored mentions column for the caller's own key and never reads the body: @all names nobody there
    sql, _ = _compiled(DEV, {"r": 1})
    assert "chat_messages.body" not in sql


class _Db:
    def __init__(self, rows=None, boom=False):
        self.rows, self.boom, self.n = rows or [], boom, 0

    async def execute(self, stmt):
        self.n += 1
        if self.boom:
            raise RuntimeError("boom")
        return types.SimpleNamespace(all=lambda: self.rows)


@pytest.mark.asyncio
async def test_the_helper_answers_a_count_per_room_an_empty_set_and_none_when_the_read_failed():
    assert await cs.unread_mention_counts(_Db([("a", 3)]), DEV, {"a": 0, "b": 0}) == {"a": 3}
    db = _Db()
    assert await cs.unread_mention_counts(db, DEV, {}) == {} and db.n == 0       # nothing to ask: no statement
    assert await cs.unread_mention_counts(_Db(boom=True), DEV, {"a": 0}) is None  # not a zero


def test_the_list_carries_the_count_and_the_third_state():
    src = open(cs.__file__).read()
    assert '"unread_mentions": None if mention_counts is None else int(mention_counts.get(cid, 0))' in src
    assert "mention_counts = await unread_mention_counts(db, actor, mention_floors)" in src
    # the floor is the LOWEST mark among the caller's own participant rows (a developer reads through his agents' rows too)
    assert "min(marks)" in src


def test_the_rows_statement_reads_the_same_conditions_newest_first_and_bounded():
    c = cs.unread_mention_rows_stmt(DEV, {"room-a": 4}, 20).compile(dialect=postgresql.dialect())
    sql = " ".join(str(c).split())
    assert "chat_messages.mentions @>" in sql and "chat_messages.deleted_at IS NULL" in sql
    assert "ORDER BY chat_messages.created_at DESC, chat_messages.id DESC" in sql and "LIMIT" in sql and "GROUP BY" not in sql
    assert [{"key": "dev:6"}] in c.params.values() and 20 in c.params.values()


def test_the_floor_of_a_room_is_the_lowest_mark_among_the_callers_own_rows():
    P = types.SimpleNamespace
    mk = lambda **kw: P(ptype="developer", developer_id=6, agent_did=None, **kw)          # noqa: E731
    ag = lambda **kw: P(ptype="agent", developer_id=None, agent_did="did:a", **kw)        # noqa: E731
    other = P(ptype="developer", developer_id=9, agent_did=None, last_read_seq=0, hidden_before_seq=0)
    parts = {"r1": [mk(last_read_seq=10, hidden_before_seq=0), ag(last_read_seq=3, hidden_before_seq=5), other],
             "r2": [other]}
    floors = cs.mention_floors_of(parts, {"dev:6", cs.principal_key("agent", "did:a")})
    assert floors == {"r1": 5}                       # max(read, hidden) per row, then the lowest row; r2 holds none of ours


@pytest.mark.asyncio
async def test_the_bell_read_says_unavailable_when_a_rooms_count_failed_never_zero(monkeypatch):
    async def listing(db, actor, **kw):
        return {"conversations": [{"id": "a", "unread_mentions": 2, "kind": "org", "title": "T"},
                                  {"id": "b", "unread_mentions": None, "kind": "org", "title": "U"}]}
    monkeypatch.setattr(cs, "list_conversations", listing)
    out = await cs.unread_mention_items(None, DEV, limit=20)
    assert out == {"mentions": [], "total": None, "available": False}


@pytest.mark.asyncio
async def test_the_bell_read_is_an_honest_zero_when_no_room_has_a_mention(monkeypatch):
    async def listing(db, actor, **kw):
        return {"conversations": [{"id": "a", "unread_mentions": 0, "kind": "org", "title": "T"}]}
    monkeypatch.setattr(cs, "list_conversations", listing)
    assert await cs.unread_mention_items(None, DEV) == {"mentions": [], "total": 0, "available": True}


@pytest.mark.asyncio
async def test_the_bell_read_carries_the_rooms_title_the_sender_the_seq_and_a_bounded_preview(monkeypatch):
    from sqlalchemy import select
    from agentvault_registry import models
    from tests._sqlite_db import sqlite_db
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant, models.ChatMessage)
    s = db.sync
    for i, n in ((6, "Him"), (9, "Scout Owner")):
        s.add(models.Developer(id=i, name=n, email=f"d{i}@example.test", hashed_password="x"))
    s.add(models.Conversation(id="room-a", kind="org", org_id="o", title="Sessions", created_by_ptype="developer", created_by_id="9"))
    s.add(models.ConversationParticipant(id="p6", conversation_id="room-a", ptype="developer", developer_id=6, state="active",
                                         last_read_seq=2))
    s.add(models.ConversationParticipant(id="p9", conversation_id="room-a", ptype="developer", developer_id=9, state="active"))
    long = "x" * 400
    for n, (seq, body) in enumerate(((1, "old"), (3, "short @him"), (4, long))):
        s.add(models.ChatMessage(id=f"m{seq}", conversation_id="room-a", seq=seq, sender_ptype="developer", sender_id="9",
                                 kind="text", body=body, client_ref=f"r{seq}", mentions=[{"key": "dev:6"}]))
    s.commit()

    async def listing(db_, actor, **kw):
        return {"conversations": [{"id": "room-a", "unread_mentions": 2, "kind": "org", "title": "Sessions"}]}
    monkeypatch.setattr(cs, "list_conversations", listing)

    async def names(db_, keys):          # the names read is PostgreSQL's (= ANY(...))
        return {"dev:9": "Scout Owner"}
    monkeypatch.setattr(cs, "display_names", names)
    # SQLite has no JSONB containment: the rows come from the same floors, without it
    monkeypatch.setattr(cs, "unread_mention_rows_stmt", lambda actor, floors, limit: select(models.ChatMessage).where(
        models.ChatMessage.conversation_id == "room-a", models.ChatMessage.seq > floors["room-a"]).order_by(
        models.ChatMessage.seq.desc()).limit(limit))
    out = await cs.unread_mention_items(db, DEV, limit=20)
    assert out["total"] == 2 and out["available"] is True
    assert [m["seq"] for m in out["mentions"]] == [4, 3]                # above the mark of 2, newest first
    top = out["mentions"][0]
    assert top["conversation_id"] == "room-a" and top["title"] == "Sessions" and top["kind"] == "org"
    assert len(top["preview"]) == cs.MENTION_PREVIEW + 1 and top["preview"].endswith("…")
    assert out["mentions"][1]["preview"] == "short @him" and out["mentions"][1]["sender"] == "Scout Owner"
