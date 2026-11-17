"""V0662 (OurChat lane, order gwo_173e400022a85073f908044b): reactions to a message.

One word from a closed list (ack, agree, thanks, done, question, look), once per person and word, taken off again. The room
sees the count, each reader sees which words are their own; a reaction wakes no sync call and notifies no one. Measured
through the real chat router over real (SQLite) rows. Every case fails on 1a5f4c699 (the console edit slice), where the
routes, the table and the rules module do not exist, except the ones marked control.
"""
from __future__ import annotations

import asyncio
import datetime
import sys
import types

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_reactions as cr
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

AUTHOR = "did:theprotocol:eu.test:session-tester"
OTHER = "did:theprotocol:eu.test:session-lead"
STRANGER = "did:theprotocol:eu.test:nobody"
CONV = "conv-react-1"
BASE = f"/api/v1/chat/conversations/{CONV}/messages"


def run(coro):
    return asyncio.run(coro)


# ── the pure rules ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_words_are_a_closed_list_of_plain_words():
    assert cr.VOCAB == ("ack", "agree", "thanks", "done", "question", "look")
    assert all(w.isascii() and w.isalpha() for w in cr.VOCAB)                                # no emoji, ever
    assert cr.valid("ack") and not cr.valid("") and not cr.valid("like") and not cr.valid(None) and not cr.valid(3)


def test_a_summary_counts_each_word_marks_mine_and_keeps_the_order():
    rows = [("thanks", "agent:b"), ("ack", "agent:a"), ("thanks", "agent:a"), ("bogus", "agent:a")]
    got = cr.summarize(rows, {"agent:a"})
    assert got == [{"key": "ack", "count": 1, "mine": True}, {"key": "thanks", "count": 2, "mine": True}]
    assert cr.summarize(rows, {"agent:zzz"}) == [{"key": "ack", "count": 1, "mine": False},
                                                {"key": "thanks", "count": 2, "mine": False}]
    assert cr.summarize([], {"agent:a"}) == []


def test_a_taken_back_or_system_message_takes_no_reaction():
    assert cr.refusal("text", deleted=False) is None                                         # control
    assert "taken back" in cr.refusal("text", deleted=True)
    assert "system" in cr.refusal("system", deleted=False)


@pytest.fixture(autouse=True)
def _fresh_rate_counts():
    cs._LOCAL_RL.clear()
    yield
    cs._LOCAL_RL.clear()


class _Manager:
    def __init__(self):
        self.sent, self.woken = [], []

    async def broadcast_to_subscribers(self, topic, envelope):
        self.sent.append((topic, envelope))

    async def wake_chat(self, keys):
        self.woken.append(set(keys))

    async def is_present(self, dev_id):
        return False


@pytest.fixture()
def env(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    mgr = _Manager()
    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = mgr
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")

    async def _quiet(*a, **k):
        return 0
    pn.notify = _quiet
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")
    rh.dispatch_webhook_for_agents = _quiet
    for mod in (ws, pn, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    async def _names(db, keys):
        return {k: k.split(":")[-1] for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    async def _owners(db, dids):
        return {d: {AUTHOR: 6, OTHER: 7}.get(d) for d in dids}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatCardUpdate, models.ChatMessageEdit, models.ChatPin, models.ChatReaction, models.ChatBlock,
                   models.GuildWorkOrder, models.GuildOrderEvent, models.GuildBid)
    s = db.sync
    # the send's own UPDATE stamps last_message_at with now(), which SQLite does not have
    s.connection().connection.driver_connection.create_function(
        "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    s.add(models.Conversation(id=CONV, kind="dm", created_by_ptype="agent", created_by_id=AUTHOR))
    for i, did in enumerate((AUTHOR, OTHER)):
        s.add(models.ConversationParticipant(id=f"p-{i}", conversation_id=CONV, ptype="agent", agent_did=did,
                                             state="active"))
    s.commit()
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    who = {"did": AUTHOR}
    caller = lambda: {"kind": "agent", "agent_did": who["did"], "agent": types.SimpleNamespace(name=who["did"])}
    from agentvault_registry import security
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep:
            app.dependency_overrides[dep] = caller
    return types.SimpleNamespace(app=app, db=db, who=who, mgr=mgr)


async def _call(env, method, path, as_did=AUTHOR, **kw):
    env.who["did"] = as_did
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        r = await c.request(method, path, **kw)
    await asyncio.sleep(0.05)              # the background fan-out
    return r


async def _say(env, text="well said", ref="text-00000001", as_did=AUTHOR):
    r = await _call(env, "POST", BASE, as_did=as_did, json={"kind": "text", "body": text, "client_ref": ref})
    assert r.status_code == 201, r.text
    return r.json()["message"]


def _react(env, mid, word, as_did=OTHER):
    return _call(env, "PUT", f"{BASE}/{mid}/reactions/{word}", as_did=as_did)


def _unreact(env, mid, word, as_did=OTHER):
    return _call(env, "DELETE", f"{BASE}/{mid}/reactions/{word}", as_did=as_did)


def test_a_reaction_is_one_row_and_a_repeat_changes_nothing(env):
    async def go():
        m = await _say(env)
        r = await _react(env, m["id"], "thanks")
        assert r.status_code == 200, r.text
        assert r.json()["added"] is True and r.json()["reactions"] == [{"key": "thanks", "count": 1, "mine": True}]
        r = await _react(env, m["id"], "thanks")
        assert r.json()["added"] is False and r.json()["reactions"][0]["count"] == 1
        assert env.db.sync.query(models.ChatReaction).count() == 1
    run(go())


def test_the_count_is_the_room_s_and_mine_is_each_reader_s(env):
    async def go():
        m = await _say(env)
        await _react(env, m["id"], "agree", as_did=OTHER)
        r = await _react(env, m["id"], "agree", as_did=AUTHOR)
        assert r.json()["reactions"] == [{"key": "agree", "count": 2, "mine": True}]
        await _react(env, m["id"], "look", as_did=OTHER)
        page = (await _call(env, "GET", BASE, as_did=AUTHOR)).json()["messages"]
        got = {x["key"]: x for x in page[0]["reactions"]}
        assert got["agree"] == {"key": "agree", "count": 2, "mine": True}
        assert got["look"] == {"key": "look", "count": 1, "mine": False}
        page = (await _call(env, "GET", BASE, as_did=OTHER)).json()["messages"]
        assert {x["key"]: x["mine"] for x in page[0]["reactions"]} == {"agree": True, "look": True}
    run(go())


def test_a_message_nobody_reacted_to_says_so_with_an_empty_list(env):
    async def go():
        await _say(env)
        page = (await _call(env, "GET", BASE, as_did=OTHER)).json()["messages"]
        assert page[0]["reactions"] == []
    run(go())


def test_a_reaction_can_be_taken_off_and_only_the_own_one(env):
    async def go():
        m = await _say(env)
        await _react(env, m["id"], "done", as_did=OTHER)
        await _react(env, m["id"], "done", as_did=AUTHOR)
        r = await _unreact(env, m["id"], "done", as_did=OTHER)
        assert r.status_code == 200 and r.json()["removed"] is True
        assert r.json()["reactions"] == [{"key": "done", "count": 1, "mine": False}]       # the author's stays
        r = await _unreact(env, m["id"], "done", as_did=OTHER)
        assert r.json()["removed"] is False and r.json()["reactions"][0]["count"] == 1
        r = await _unreact(env, m["id"], "done", as_did=AUTHOR)
        assert r.json()["reactions"] == []
        assert env.db.sync.query(models.ChatReaction).count() == 0
    run(go())


def test_only_the_closed_words_are_taken(env):
    async def go():
        m = await _say(env)
        for bad in ("like", "thumbs_up", "%F0%9F%91%8D"):
            r = await _react(env, m["id"], bad)
            assert r.status_code == 422 and "one of: ack, agree" in r.text, bad
        assert (await _unreact(env, m["id"], "like")).status_code == 422
        assert env.db.sync.query(models.ChatReaction).count() == 0
    run(go())


def test_a_taken_back_message_takes_no_reaction_and_neither_does_a_stranger(env):
    async def go():
        m = await _say(env)
        await _call(env, "DELETE", f"{BASE}/{m['id']}", as_did=AUTHOR)
        r = await _react(env, m["id"], "ack")
        assert r.status_code == 409 and "taken back" in r.text
        m2 = await _say(env, "second", ref="text-00000002")
        r = await _react(env, m2["id"], "ack", as_did=STRANGER)
        assert r.status_code in (403, 404, 409) and env.db.sync.query(models.ChatReaction).count() == 0
        assert (await _react(env, m2["id"], "ack", as_did=OTHER)).status_code == 200          # control: a member may
    run(go())


def test_the_thread_hears_the_counts_and_no_one_is_woken_or_told(env):
    async def go():
        m = await _say(env)
        woken, sent = len(env.mgr.woken), len(env.mgr.sent)
        await _react(env, m["id"], "question")
        new = [e for _, e in env.mgr.sent[sent:]]
        assert new and {e["type"] for e in new} == {"chat.message_reaction"}
        data = new[0]["data"]["message"]
        assert data["id"] == m["id"] and data["word"] == "question"
        assert data["reactions"] == [{"key": "question", "count": 1}]                       # counts only: no `mine`
        assert data["by"] == {"ptype": "agent", "id": OTHER}
        assert len(env.mgr.woken) == woken                                                  # no sync wake
        await _unreact(env, m["id"], "question")
        assert env.mgr.sent[-1][1]["data"]["message"]["reactions"] == []
    run(go())


def test_a_repeat_and_a_miss_tell_no_one(env):
    async def go():
        m = await _say(env)
        await _react(env, m["id"], "ack")
        sent = len(env.mgr.sent)
        await _react(env, m["id"], "ack")
        await _unreact(env, m["id"], "agree")
        assert len(env.mgr.sent) == sent
    run(go())


def test_a_thread_another_registry_reaches_takes_the_reaction_here_and_the_registry_is_told(env, monkeypatch):
    """V0663 (order gwo_9dce94d939aff2fa8ea4f91c): hosted here, so the reaction lands here and an event goes to the registries that
    have a member (the wire is pinned in test_chat_fed_events_v0663)."""
    from agentvault_registry.services import chat_fed_events as fev
    told = []

    async def publish(db, conv, event):
        told.append(event)
        return 1

    async def key(db, actor):
        return "dev:1@https://a.example"
    monkeypatch.setattr(fev, "publish", publish)
    monkeypatch.setattr(fev, "local_actor_key", key)

    async def go():
        m = await _say(env)
        s = env.db.sync
        s.add(models.ConversationParticipant(id="p-remote", conversation_id=CONV, ptype="remote",
                                             remote_key="dev:5@https://b.example", state="active"))
        s.commit()
        r = await _react(env, m["id"], "ack")
        assert r.status_code == 200
        assert s.query(models.ChatReaction).count() == 1
        assert told == [{"type": "reaction", "message_seq": m["seq"], "word": "ack", "on": True, "actor": "dev:1@https://a.example"}]
    run(go())
