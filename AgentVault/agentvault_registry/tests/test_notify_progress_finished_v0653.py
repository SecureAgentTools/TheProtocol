"""V0653: chat.progress_finished, a progress card's verdict told (session-lead, the sessions' room seq 716; his approval
of the missing notices, sessionlogs2026/NOTIFICATION_GAPS_2026-10-31.md: "in-app (a proof or roll, with its verdict)").

The card's closing update (passed, failed, cancelled) tells every developer who takes part in the thread and has not
muted it, the updater excepted when the updater is a developer; a session's verdict reaches its owner in the room. An
update that is not a verdict, and any other card, tells nobody. The rule (chat_service.notify_progress_finished) with
its recipients supplied, and the route over real SQLite rows in an organization room. BASE: on a5ef48ddd (V0652) the
function does not exist and the route tells nobody.
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

SESSION = "did:theprotocol:eu.test:session-tester"
OTHER = "did:theprotocol:eu.test:session-lead"
ROOM = "room-sessions"


def run(coro):
    return asyncio.run(coro)


def progress(state="running", title="V0653 pair proof", note=None):
    d = {"title": title, "state": state}
    if note is not None:
        d["note"] = note
    return {"v": 1, "type": "progress", "data": d}


def _push_stub(monkeypatch):
    told = []
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")

    async def _notify(type_key, devs, **kw):
        told.append((type_key, sorted(devs), kw))
        return len(list(devs))

    def _spawn(coro):
        asyncio.get_event_loop().create_task(coro)
    pn.notify, pn.spawn_notice = _notify, _spawn
    monkeypatch.setitem(sys.modules, pn.__name__, pn)
    import agentvault_registry.background_tasks as bt
    monkeypatch.setattr(bt, "push_notify", pn, raising=False)
    return told


# ── the rule, its recipients supplied ─────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def rule(monkeypatch):
    told = _push_stub(monkeypatch)
    recips = []

    async def _recips(db, conv, sender):
        return list(recips)
    monkeypatch.setattr(cs, "recipients_snapshot", _recips)
    return types.SimpleNamespace(told=told, recips=recips, conv=types.SimpleNamespace(id=ROOM, kind="org"))


def _agent(name="session-tester"):
    return types.SimpleNamespace(ptype="agent", developer_id=None, agent_did=SESSION, display_name=name)


def _dev(dev_id, name="maintainer"):
    return types.SimpleNamespace(ptype="developer", developer_id=dev_id, agent_did=None, display_name=name)


def _r(ptype, dev=None, muted=False, did=None):
    return {"key": f"{ptype}:{dev or did}", "ptype": ptype, "developer_id": dev, "agent_did": did, "muted": muted,
            "owner_developer_id": dev if ptype == "developer" else 6}


def test_a_verdict_tells_the_threads_people_and_a_sessions_owner_among_them(rule):
    rule.recips[:] = [_r("developer", 6), _r("developer", 9, muted=True), _r("agent", did=OTHER)]

    async def go():
        devs = await cs.notify_progress_finished(None, rule.conv, {"card": progress("passed", note="48 of 48")}, _agent())
        await asyncio.sleep(0.01)
        return devs
    assert run(go()) == [6]                      # 9 muted the room; an agent is told through its owner's own seat
    (type_key, devs, kw), = rule.told
    assert type_key == "chat.progress_finished" and devs == [6]
    assert kw["title"] == "V0653 pair proof: passed" and kw["message"] == "session-tester: 48 of 48"
    assert kw["tags"] == "white_check_mark" and kw["click"] == f"/ui#/pocket/ourchat/{ROOM}"


def test_a_developer_is_not_told_their_own_verdict(rule):
    rule.recips[:] = [_r("developer", 7)]

    async def go():
        devs = await cs.notify_progress_finished(None, rule.conv, {"card": progress("failed")}, _dev(6))
        await asyncio.sleep(0.01)
        return devs
    assert run(go()) == [7]
    assert rule.told[0][2]["title"] == "V0653 pair proof: failed" and rule.told[0][2]["tags"] == "x"
    assert rule.told[0][2]["message"] == "maintainer closed it failed"


def test_not_a_verdict_or_not_a_progress_card_tells_nobody(rule):
    rule.recips[:] = [_r("developer", 6)]

    async def go():
        a = await cs.notify_progress_finished(None, rule.conv, {"card": progress("running")}, _agent())
        b = await cs.notify_progress_finished(None, rule.conv, {"card": {"type": "approval.decided",
                                                                            "data": {"used": True}}}, _agent())
        c = await cs.notify_progress_finished(None, rule.conv, {"kind": "text", "body": "passed"}, _agent())
        await asyncio.sleep(0.01)
        return a, b, c
    assert run(go()) == (None, None, None) and rule.told == []


def test_a_room_with_nobody_to_tell_tells_nobody(rule):
    rule.recips[:] = [_r("agent", did=OTHER), _r("developer", 6, muted=True)]

    async def go():
        return await cs.notify_progress_finished(None, rule.conv, {"card": progress("cancelled")}, _agent())
    assert run(go()) == [] and rule.told == []


# ── the route, over real rows ───────────────────────────────────────────────────────────────────────────────

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
    told = _push_stub(monkeypatch)
    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = _Manager()
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")

    async def _quiet(*a, **k):
        return 0
    rh.dispatch_webhook_for_agents = _quiet
    for mod in (ws, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)

    async def _names(db, keys):
        return {k: k.split(":")[-1] for k in keys}
    monkeypatch.setattr(cs, "display_names", _names)

    async def _owners(db, dids):
        return {d: 6 for d in dids}
    monkeypatch.setattr(cs, "agent_owner_map", _owners)
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage, models.ChatCardUpdate, models.ChatBlock)
    s = db.sync
    s.connection().connection.driver_connection.create_function(
        "now", 0, lambda: datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    # a direct thread of two sessions and their owner (the room's kind does not change who is told)
    s.add(models.Conversation(id=ROOM, kind="dm", created_by_ptype="agent", created_by_id=SESSION))
    s.add(models.ConversationParticipant(id="p-0", conversation_id=ROOM, ptype="agent", agent_did=SESSION, state="active"))
    s.add(models.ConversationParticipant(id="p-1", conversation_id=ROOM, ptype="agent", agent_did=OTHER, state="active"))
    s.add(models.ConversationParticipant(id="p-2", conversation_id=ROOM, ptype="developer", developer_id=6,
                                         state="active"))
    s.commit()
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield db
    app.dependency_overrides[get_db] = _db
    caller = lambda: {"kind": "agent", "agent_did": SESSION, "agent": types.SimpleNamespace(name=SESSION)}
    from agentvault_registry import security
    for dep in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)):
        if dep:
            app.dependency_overrides[dep] = caller
    return types.SimpleNamespace(app=app, db=db, told=told)


async def _call(env, method, path, **kw):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=env.app), base_url="http://t", timeout=30) as c:
        r = await c.request(method, path, **kw)
    await asyncio.sleep(0.05)
    return r


def test_the_route_tells_the_owner_once_the_verdict_lands_and_not_before(env):
    async def go():
        r = await _call(env, "POST", f"/api/v1/chat/conversations/{ROOM}/messages",
                        json={"kind": "card", "card": progress(), "client_ref": "progress-v0653-01"})
        assert r.status_code == 201, r.text
        mid = r.json()["message"]["id"]
        put = lambda card: _call(env, "PUT", f"/api/v1/chat/conversations/{ROOM}/messages/{mid}/card", json={"card": card})
        assert (await put(progress("running", note="console shard 2"))).status_code == 200
        before = [t for t in env.told if t[0] == "chat.progress_finished"]
        r2 = await put(progress("passed", note="48 of 48"))
        assert r2.status_code == 200 and r2.json()["changed"] is True
        after = [t for t in env.told if t[0] == "chat.progress_finished"]
        return before, after
    before, after = run(go())
    assert before == []
    assert len(after) == 1 and after[0][1] == [6] and after[0][2]["title"] == "V0653 pair proof: passed"
