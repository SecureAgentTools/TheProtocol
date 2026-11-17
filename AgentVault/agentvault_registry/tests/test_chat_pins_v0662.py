"""V0662 (OurChat lane, order gwo_173e400022a85073f908044b): pinned messages.

PUT/DELETE .../messages/{id}/pin and GET .../pins: a pin keeps a line where the thread finds it again; everyone who reads the
thread sees the same pins; who may pin follows who may speak for the thread (a member in a direct thread, a room's owner and
moderators in a room); ten at most; a line taken back loses its pin; the thread hears the change and nobody is woken.
Measured through the real chat router over real (SQLite) rows. Every case fails on b4591d1af (the search slice), where the
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
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

AUTHOR = "did:theprotocol:eu.test:session-tester"
OTHER = "did:theprotocol:eu.test:session-lead"
STRANGER = "did:theprotocol:eu.test:nobody"
CONV = "conv-pin-1"
BASE = f"/api/v1/chat/conversations/{CONV}/messages"
PINS = f"/api/v1/chat/conversations/{CONV}/pins"
from agentvault_registry.services import chat_pins as cp


def run(coro):
    return asyncio.run(coro)


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


async def _say(env, text, as_did=AUTHOR):
    env.n = getattr(env, "n", 0) + 1
    r = await _call(env, "POST", BASE, as_did=as_did, json={"kind": "text", "body": text, "client_ref": f"text-{env.n:08d}"})
    assert r.status_code == 201, r.text
    return r.json()["message"]


def _pin(env, mid, as_did=OTHER):
    return _call(env, "PUT", f"{BASE}/{mid}/pin", as_did=as_did)


def _unpin(env, mid, as_did=OTHER):
    return _call(env, "DELETE", f"{BASE}/{mid}/pin", as_did=as_did)


def _pins(env, as_did=OTHER):
    return _call(env, "GET", PINS, as_did=as_did)


def _as_room(env, owner=AUTHOR):
    s = env.db.sync
    conv = s.get(models.Conversation, CONV)
    conv.kind = "room"
    for p in s.query(models.ConversationParticipant).filter_by(conversation_id=CONV).all():
        p.role = "owner" if p.agent_did == owner else "member"
    s.commit()


def test_the_rules_are_ten_pins_and_threads_that_take_them():
    assert cp.MAX_PINS == 10 and set(cp.PINNABLE_KINDS) == {"dm", "agent_service", "group", "org", "room"}
    assert cp.refusal("dm", "text", deleted=False, pins_now=9, already=False) is None                  # control
    assert "10 pins" in cp.refusal("dm", "text", deleted=False, pins_now=10, already=False)
    assert cp.refusal("dm", "text", deleted=False, pins_now=10, already=True) is None                  # already one of them
    assert "taken back" in cp.refusal("dm", "text", deleted=True, pins_now=0, already=False)
    assert "system" in cp.refusal("dm", "system", deleted=False, pins_now=0, already=False)
    assert "no pins" in cp.refusal("support", "text", deleted=False, pins_now=0, already=False)


def test_a_member_pins_a_line_and_everyone_reads_the_same_pin(env):
    async def go():
        m = await _say(env, "the plan: ship on Friday")
        r = await _pin(env, m["id"])
        assert r.status_code == 200, r.text
        assert r.json() == {"message_id": m["id"], "conversation_id": CONV, "pinned": True, "count": 1, "added": True}
        for who in (OTHER, AUTHOR):
            got = (await _pins(env, as_did=who)).json()
            assert got["max"] == 10 and got["can_pin"] is True
            assert [p["message"]["body"] for p in got["pins"]] == ["the plan: ship on Friday"]
            assert got["pins"][0]["pinned_by"]["id"] == OTHER and got["pins"][0]["at"]
            assert got["pins"][0]["message"]["sender_name"] == AUTHOR.split(":")[-1]
        r = await _pin(env, m["id"])
        assert r.json()["added"] is False and r.json()["count"] == 1
        assert env.db.sync.query(models.ChatPin).count() == 1
    run(go())


def test_the_newest_pin_is_first_and_a_pin_can_be_taken_off(env):
    async def go():
        a = await _say(env, "first")
        b = await _say(env, "second")
        await _pin(env, a["id"])
        await _pin(env, b["id"])
        # SQLite stamps a second, Postgres a microsecond: the order under test is the pin's own time, so say it
        for mid, at in ((a["id"], "2026-11-13 12:00:00"), (b["id"], "2026-11-13 12:00:05")):
            env.db.sync.query(models.ChatPin).filter_by(message_id=mid).update({"created_at": datetime.datetime.fromisoformat(at)})
        env.db.sync.commit()
        assert [p["message"]["body"] for p in (await _pins(env)).json()["pins"]] == ["second", "first"]
        r = await _unpin(env, b["id"])
        assert r.status_code == 200 and r.json()["removed"] is True and r.json()["count"] == 1
        assert [p["message"]["body"] for p in (await _pins(env)).json()["pins"]] == ["first"]
        r = await _unpin(env, b["id"])
        assert r.json()["removed"] is False and r.json()["count"] == 1
    run(go())


def test_a_thread_keeps_ten_pins(env):
    async def go():
        ids = [(await _say(env, f"line {i}"))["id"] for i in range(11)]
        for mid in ids[:10]:
            assert (await _pin(env, mid)).status_code == 200
        r = await _pin(env, ids[10])
        assert r.status_code == 409 and "10 pins" in r.text
        assert (await _pin(env, ids[0])).json()["added"] is False                                    # control: one it has
        await _unpin(env, ids[3])
        assert (await _pin(env, ids[10])).status_code == 200
    run(go())


def test_a_line_taken_back_loses_its_pin_and_cannot_be_pinned(env):
    async def go():
        m = await _say(env, "oops")
        await _pin(env, m["id"])
        await _call(env, "DELETE", f"{BASE}/{m['id']}", as_did=AUTHOR)
        assert (await _pins(env)).json()["pins"] == []
        assert env.db.sync.query(models.ChatPin).count() == 0
        r = await _pin(env, m["id"])
        assert r.status_code == 409 and "taken back" in r.text
    run(go())


def test_in_a_room_only_its_owner_and_moderators_pin(env):
    async def go():
        m = await _say(env, "house rules", as_did=OTHER)
        _as_room(env, owner=AUTHOR)
        r = await _pin(env, m["id"], as_did=OTHER)                                                    # a member
        assert r.status_code == 403 and "owner and moderators" in r.text
        assert env.db.sync.query(models.ChatPin).count() == 0
        assert (await _pins(env, as_did=OTHER)).json()["can_pin"] is False
        r = await _pin(env, m["id"], as_did=AUTHOR)                                                   # the owner
        assert r.status_code == 200
        assert (await _pins(env, as_did=AUTHOR)).json()["can_pin"] is True
        assert [p["message"]["body"] for p in (await _pins(env, as_did=OTHER)).json()["pins"]] == ["house rules"]   # all read it
        assert (await _unpin(env, m["id"], as_did=OTHER)).status_code == 403
        assert (await _unpin(env, m["id"], as_did=AUTHOR)).json()["removed"] is True
    run(go())


def test_a_support_thread_keeps_no_pins(env):
    async def go():
        m = await _say(env, "help")
        env.db.sync.get(models.Conversation, CONV).kind = "support"
        env.db.sync.commit()
        r = await _pin(env, m["id"])
        assert r.status_code == 409 and "no pins" in r.text
        got = (await _pins(env)).json()
        assert got["pins"] == [] and got["can_pin"] is False
    run(go())


def test_the_thread_hears_a_pin_once_and_no_one_is_woken(env):
    async def go():
        m = await _say(env, "keep this")
        woken, sent = len(env.mgr.woken), len(env.mgr.sent)
        await _pin(env, m["id"])
        new = [e for _, e in env.mgr.sent[sent:]]
        assert {e["type"] for e in new} == {"chat.pins_changed"}
        assert new[0]["data"]["message"] == {"id": m["id"], "conversation_id": CONV, "pinned": True, "count": 1}
        assert len(env.mgr.woken) == woken
        sent = len(env.mgr.sent)
        await _pin(env, m["id"])                                                                       # a repeat: no one told
        assert len(env.mgr.sent) == sent
        await _unpin(env, m["id"])
        assert env.mgr.sent[-1][1]["data"]["message"]["pinned"] is False
    run(go())


def test_a_stranger_pins_and_reads_nothing_and_the_floor_hides_what_came_before(env):
    async def go():
        a = await _say(env, "early")
        b = await _say(env, "late")
        await _pin(env, a["id"])
        await _pin(env, b["id"])
        assert (await _pin(env, a["id"], as_did=STRANGER)).status_code in (403, 404, 409)
        assert (await _pins(env, as_did=STRANGER)).status_code in (403, 404, 409)
        s = env.db.sync
        row = s.query(models.ConversationParticipant).filter_by(conversation_id=CONV, agent_did=OTHER).one()
        row.hidden_before_seq = 1
        s.commit()
        assert [p["message"]["body"] for p in (await _pins(env, as_did=OTHER)).json()["pins"]] == ["late"]
        assert len((await _pins(env, as_did=AUTHOR)).json()["pins"]) == 2                              # control
    run(go())
