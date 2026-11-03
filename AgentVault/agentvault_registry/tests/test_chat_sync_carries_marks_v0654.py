"""V0654 (aq), item 24 (session-lead, the sessions' room seq 1092; found on seq 1075, the bridge's first post): the chat's sync
feed (GET /api/v1/chat/sync, what every session's watcher reads) carries how each line was sent (sent_with), whether an
agent's line was sent by its owner (sent_by_owner) and whom it names (mentions), as the thread read does
(serialize_message). Its items held none of them, so chat_link 2.16 read every developer line back from the thread to
tell his signed-in hand from a key's.

Over real (SQLite) rows through chat_service.sync_since. BASE (V0653, f8f1993fb): none of the three fields is there.
"""
from __future__ import annotations

import datetime

from agentvault_registry import models
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

UTC = datetime.timezone.utc
READER = "did:theprotocol:eu.test:reader"
AGENT = "did:theprotocol:eu.test:session-tester"
CONV = "conv-marks-1"
T0 = datetime.datetime(2026, 11, 2, 16, 0, tzinfo=UTC)


def _db():
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage)
    s = db.sync
    s.add(models.Conversation(id=CONV, kind="dm", created_by_ptype="agent", created_by_id=AGENT))
    s.add(models.ConversationParticipant(id="p-1", conversation_id=CONV, ptype="agent", agent_did=READER, state="active"))
    lines = [
        dict(id="m-1", seq=1, sender_ptype="developer", sender_id="6", body="@reader approved", sent_with="session",
             mentions=[{"key": cs.principal_key("agent", READER), "name": "reader"}]),
        dict(id="m-2", seq=2, sender_ptype="developer", sender_id="6", body="approved", sent_with="api_key"),
        dict(id="m-3", seq=3, sender_ptype="agent", sender_id=AGENT, body="done", sent_with="agent",
             sent_by_developer_id=6),
        dict(id="m-4", seq=4, sender_ptype="developer", sender_id="6", body="drafted for me", sent_with="assistant"),
        dict(id="m-5", seq=5, sender_ptype="agent", sender_id=AGENT, body="gone", sent_with="agent",
             deleted_at=T0 + datetime.timedelta(minutes=9), mentions=[{"key": "agt:x"}]),
    ]
    for i, d in enumerate(lines):
        s.add(models.ChatMessage(conversation_id=CONV, kind="text", client_ref=f"c-{d['seq']:04d}-x",
                                 created_at=T0 + datetime.timedelta(minutes=i), **d))
    s.commit()
    return db


async def test_every_line_says_how_it_was_sent_who_sent_it_and_whom_it_names():
    out = await cs.sync_since(_db(), cs.Actor("agent", agent_did=READER), (T0 - datetime.timedelta(hours=1)).isoformat())
    got = {m["id"]: (m["sent_with"], m["sent_by_owner"], [x.get("key") for x in m["mentions"]]) for m in out["messages"]}
    assert got == {
        "m-1": ("session", False, [cs.principal_key("agent", READER)]),
        "m-2": ("api_key", False, []),
        "m-3": ("agent", True, []),
        "m-4": ("assistant", False, []),
        "m-5": ("agent", False, []),        # a deleted line names nobody any more
    }


async def test_a_line_from_before_v0653_says_nothing_was_recorded():
    db = _db()
    db.sync.add(models.ChatMessage(id="m-0", conversation_id=CONV, seq=6, sender_ptype="developer", sender_id="6",
                                   kind="text", body="old", client_ref="c-old-0001", created_at=T0 + datetime.timedelta(minutes=30)))
    db.sync.commit()
    out = await cs.sync_since(db, cs.Actor("agent", agent_did=READER), (T0 + datetime.timedelta(minutes=29)).isoformat())
    [m] = out["messages"]
    assert (m["id"], m["sent_with"], m["sent_by_owner"], m["mentions"]) == ("m-0", None, False, [])
