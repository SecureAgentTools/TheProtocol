"""V0650 (g) (2026-10-31, agentvault2-14): the chat sync cursor misses nothing and returns nothing twice.

Order gwo_e0c0c8b4d1a5c6a016077567. A bare timestamp cursor is not lossless: two messages can share an instant (a page
boundary between them drops one), and a message can commit after a later one (a cursor past the later one skips it).
The sync answer's next_cursor is a keyset (created_at, id) plus the ids already returned inside the last SYNC_SETTLE_S
seconds, and every writer stamps created_at right after it takes the message's seq (the column's default is the
TRANSACTION start, which for a service.result can be minutes before the row is visible).

Over real (SQLite) rows through chat_service.sync_since, with distinct AND shared timestamps (§DIRFEED-2: distinct ones
pass with or without a tie-break). Cases marked BASE fail on V0649 (6c1f036b), where sync_since takes no cursor and
answers none, and the writers stamp nothing.
"""
from __future__ import annotations

import ast
import base64
import datetime
import json
import pathlib

import pytest

from agentvault_registry import models
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

UTC = datetime.timezone.utc
AGENT = "did:theprotocol:eu.test:reader"
SENDER = "did:theprotocol:eu.test:sender"
CONV = "conv-cursor-1"


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage)
    s = db.sync
    s.add(models.Conversation(id=CONV, kind="dm", created_by_ptype="agent", created_by_id=SENDER))
    s.add(models.ConversationParticipant(id="p-1", conversation_id=CONV, ptype="agent", agent_did=AGENT, state="active"))
    s.commit()
    return db


def _post(db, seq, *, created_at, mid):
    db.sync.add(models.ChatMessage(id=mid, conversation_id=CONV, seq=seq, sender_ptype="agent", sender_id=SENDER,
                                   kind="text", body=f"m{seq}", client_ref=f"c-{seq}", created_at=created_at))
    db.sync.commit()


def _actor():
    return cs.Actor("agent", agent_did=AGENT)


def _ids(out):
    return [m["id"] for m in out["messages"]]


def test_the_cursor_round_trips_and_a_foreign_one_is_the_callers_422():
    # BASE: no codec
    t = datetime.datetime(2026, 10, 31, 5, 0, 0, 123456, tzinfo=UTC)
    seen = [("m-1", t), ("m-2", t + datetime.timedelta(seconds=1))]
    assert cs.decode_sync_cursor(cs.encode_sync_cursor(t, "m-0", seen)) == (t, "m-0", seen)
    assert cs.decode_sync_cursor(cs.encode_sync_cursor(t, None, [])) == (t, None, [])

    def b64(obj):
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    for bad in ["", "not base64 at all!", b64([1, 2]), b64({"v": 2, "t": t.isoformat()}),
                b64({"v": 1, "t": "yesterday"}), b64({"v": 1, "t": t.isoformat(), "i": 5}),
                b64({"v": 1, "t": t.isoformat(), "s": [["m", t.isoformat()]] * (cs.SYNC_SEEN_MAX + 1)}),
                "A" * 5000]:
        with pytest.raises(cs.ChatError) as e:
            cs.decode_sync_cursor(bad)
        assert e.value.status_code == 422 and "cursor is not one this registry gave out" in e.value.detail


@pytest.mark.parametrize("age_s", [0, 60], ids=["inside-the-overlap", "behind-the-horizon"])
async def test_two_messages_at_one_instant_page_one_by_one(monkeypatch, age_s):
    # BASE: sync_since takes no cursor
    monkeypatch.setattr(cs, "SYNC_MAX", 1)
    db = _seed()
    at = cs.message_clock() - datetime.timedelta(seconds=age_s)
    _post(db, 1, created_at=at, mid="m-b")
    _post(db, 2, created_at=at, mid="m-a")
    cursor = cs.encode_sync_cursor(at - datetime.timedelta(seconds=10), None, [])
    pages = []
    for _ in range(3):
        out = await cs.sync_since(db, _actor(), None, cursor=cursor)
        pages.append(_ids(out))
        cursor = out["next_cursor"]
    assert sorted(pages[0] + pages[1]) == ["m-a", "m-b"] and len(pages[0]) == len(pages[1]) == 1, pages
    assert pages[2] == [], pages


async def test_a_message_that_commits_after_a_later_one_is_returned_once():
    # BASE: sync_since answers no cursor
    db = _seed()
    later = cs.message_clock()
    _post(db, 3, created_at=later, mid="m-later")
    first = await cs.sync_since(db, _actor(), None)
    assert _ids(first) == ["m-later"]
    # stamped half a second before m-later, visible only now (its transaction committed after m-later's)
    _post(db, 2, created_at=later - datetime.timedelta(seconds=0.5), mid="m-earlier")
    second = await cs.sync_since(db, _actor(), None, cursor=first["next_cursor"])
    assert _ids(second) == ["m-earlier"]
    third = await cs.sync_since(db, _actor(), None, cursor=second["next_cursor"])
    assert _ids(third) == []


def test_the_cursor_remembers_at_most_its_bound_and_never_moves_back():
    # BASE: no next_sync_cursor
    now = datetime.datetime(2026, 10, 31, 5, 0, 0, tzinfo=UTC)
    rows = [(f"m-{k:03d}", now - datetime.timedelta(seconds=1) + datetime.timedelta(microseconds=k))
            for k in range(100)]
    t, i, seen = cs.next_sync_cursor(now - datetime.timedelta(hours=1), None, [], rows, False, now)
    n = cs.SYNC_SEEN_MAX
    assert len(seen) == n and [mid for mid, _ in seen] == [r[0] for r in rows[-n:]]
    assert (t, i) == (rows[-n - 1][1], rows[-n - 1][0])          # the keyset moved to the newest id it forgot
    # a call that reads at an earlier time (a skewed worker) never moves the cursor back
    t2, i2, seen2 = cs.next_sync_cursor(t, i, seen, [], False, now - datetime.timedelta(minutes=5))
    assert (t2, i2) == (t, i) and seen2 == seen
    # a quiet call moves the horizon forward and forgets what it no longer re-reads
    t3, i3, seen3 = cs.next_sync_cursor(t, i, seen, [], False, now + datetime.timedelta(minutes=5))
    assert t3 == now + datetime.timedelta(minutes=5) - datetime.timedelta(seconds=cs.SYNC_SETTLE_S)
    assert i3 is None and seen3 == []


async def test_the_legacy_since_still_skips_a_row_at_since_and_answers_a_cursor():
    # BASE: no next_cursor in the answer
    db = _seed()
    at = cs.message_clock() - datetime.timedelta(minutes=5)
    _post(db, 1, created_at=at, mid="m-at")
    _post(db, 2, created_at=at + datetime.timedelta(seconds=1), mid="m-after")
    out = await cs.sync_since(db, _actor(), at.isoformat())
    assert _ids(out) == ["m-after"] and out["next_cursor"]
    assert _ids(await cs.sync_since(db, _actor(), None, cursor=out["next_cursor"])) == []


class _Recording:
    def __init__(self, inner):
        self.inner, self.sql = inner, []

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        return await self.inner.execute(stmt, params)


async def test_the_statement_orders_by_time_then_id_and_carries_the_keyset_and_the_skip():
    # BASE: ORDER BY created_at alone, no keyset, no skip
    db = _Recording(_seed())
    now = cs.message_clock()
    cursor = cs.encode_sync_cursor(now - datetime.timedelta(seconds=30), "m-0",
                                   [("m-1", now - datetime.timedelta(seconds=1))])
    await cs.sync_since(db, _actor(), None, cursor=cursor)
    sql = db.sql[0]
    assert "ORDER BY m.created_at ASC, m.id ASC" in sql
    assert "(m.created_at > :ts OR (m.created_at = :ts AND m.id > :tid))" in sql and "m.id NOT IN" in sql


# ─────────────────────────────── the writers ───────────────────────────────

def _writers_without_the_clock(root: pathlib.Path):
    """Every ChatMessage(...) call under root that does not pass created_at=<...>message_clock()."""
    out = []
    for path in sorted(root.rglob("*.py")):
        if {"static", "node_modules"} & set(path.relative_to(root).parts):
            continue                 # the console's tree holds no writer (and node_modules may hold Python 2)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if name != "ChatMessage":
                continue
            value = next((k.value for k in node.keywords if k.arg == "created_at"), None)
            clock = isinstance(value, ast.Call) and (getattr(value.func, "id", None)
                                                     or getattr(value.func, "attr", None)) == "message_clock"
            if not clock:
                out.append(f"{path.relative_to(root)}:{node.lineno}")
    return out


def test_every_chat_message_writer_stamps_the_message_clock():
    # BASE: names services/chat_service.py twice and services/chat_federation.py once
    package = pathlib.Path(cs.__file__).resolve().parents[1]
    assert _writers_without_the_clock(package) == []


def test_control_the_writer_gate_refuses_the_old_shape(tmp_path):
    # control: passes on both trees (the gate itself)
    (tmp_path / "w.py").write_text("old = ChatMessage(conversation_id=c, seq=1)\n"
                                   "new = models.ChatMessage(seq=2, created_at=cs.message_clock())\n")
    assert _writers_without_the_clock(tmp_path) == ["w.py:1"]
