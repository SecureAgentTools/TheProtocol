"""V0650 (g) (2026-10-31, agentvault2-14): agents and developers get chat messages without polling.

Order gwo_e0c0c8b4d1a5c6a016077567. GET /api/v1/chat/sync takes `wait` (0 to 25 s) and `cursor`: with nothing new, the
call waits, holding no database connection and running no query, until fan_out_message (the post-commit point every send
reaches) wakes it, on this worker directly or on another over Redis (the `chat:wake` topic, which no socket may read), or
until the bound, where it answers empty. Every answer carries `next_cursor`.

The acceptance, measured here through FastAPI on the real chat router over real (SQLite) rows: a waiting call returns
within a second of a new message, and it returns empty at the bound; while idle it runs one query and hands its session
back. Cases marked BASE fail on V0649 (6c1f036b), where FastAPI drops the unknown `wait` and `cursor` and the route
answers at once, without next_cursor, and the manager has no waiters.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import types

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat as chat_router
from agentvault_registry.routers import websocket as WS
from agentvault_registry.security import get_current_actor_for_read
from agentvault_registry.services import chat_service as cs
from tests._sqlite_db import sqlite_db

AGENT = "did:theprotocol:eu.test:waiting-agent"
SENDER = "did:theprotocol:eu.test:sender"
CONV = "conv-sync-1"
KEY = "agt:" + AGENT.lower()


class LoggedDb:
    """The SQLite shim, logging what the request does with its session."""

    def __init__(self, inner):
        self.inner, self.log = inner, []

    async def execute(self, *a, **k):
        self.log.append("execute")
        return await self.inner.execute(*a, **k)

    async def close(self):
        self.log.append("close")

    def __getattr__(self, name):
        return getattr(self.inner, name)


def _read_deps():
    """The chat read dependency, and (where V0650 (m) is merged) its key-aware successor on the GET routes."""
    from agentvault_registry import security
    return [d for d in (get_current_actor_for_read, getattr(security, "get_current_actor_for_read_or_key", None)) if d]


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.Conversation, models.ConversationParticipant,
                   models.ChatMessage)
    s = db.sync
    s.add(models.Conversation(id=CONV, kind="dm", created_by_ptype="agent", created_by_id=SENDER))
    s.add(models.ConversationParticipant(id="p-1", conversation_id=CONV, ptype="agent", agent_did=AGENT, state="active"))
    s.add(models.ConversationParticipant(id="p-2", conversation_id=CONV, ptype="agent", agent_did=SENDER, state="active"))
    s.commit()
    return db


def _post(db, seq, *, conv=CONV, created_at=None, mid=None):
    m = models.ChatMessage(id=mid or f"m-{seq}", conversation_id=conv, seq=seq, sender_ptype="agent",
                           sender_id=SENDER, kind="text", body=f"hello {seq}", client_ref=f"c-{conv}-{seq}",
                           created_at=created_at or cs.message_clock())
    db.sync.add(m)
    db.sync.commit()
    return m


def _stub_delivery(monkeypatch):
    """The owners' hook and the offline notices fan_out_message spawns, as stand-ins (the wake is what is measured)."""
    async def _quiet(*a, **k):
        return 0
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")
    pn.notify = _quiet
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")
    rh.dispatch_webhook_for_agents = _quiet
    for mod in (pn, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)


@pytest.fixture()
async def env(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    monkeypatch.setattr(WS, "manager", WS.ConnectionManager())      # a fresh manager: this worker's waiters
    db = _seed()
    logged = LoggedDb(db)
    app = FastAPI()
    app.include_router(chat_router.router)

    async def _db():
        yield logged
    app.dependency_overrides[get_db] = _db
    caller = lambda: {"kind": "agent", "agent_did": AGENT, "agent": types.SimpleNamespace(name="waiting-agent")}
    for dep in _read_deps():
        app.dependency_overrides[dep] = caller
    before = set(asyncio.all_tasks())
    yield types.SimpleNamespace(app=app, db=db, logged=logged)
    left = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()]
    for t in left:          # a listener or a waiting call a failed case left behind
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)


async def _get(app, **params):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t", timeout=30) as c:
        return await c.get("/api/v1/chat/sync", params=params)


async def _start(env):
    """The cursor a client starts from: a plain call (nothing in the thread yet)."""
    first = (await _get(env.app)).json()
    assert first["messages"] == [] and first.get("next_cursor"), first
    return first["next_cursor"]


def _agent_recipient(did=AGENT, owner=7):
    return {"ptype": "agent", "agent_did": did, "developer_id": None, "owner_developer_id": owner, "muted": False}


# ─────────────────────────────── the acceptance ───────────────────────────────

async def test_a_waiting_call_returns_within_a_second_of_a_new_message(env, monkeypatch):
    # BASE: no next_cursor, and the call answers at once instead of waiting
    _stub_delivery(monkeypatch)
    cursor = await _start(env)
    task = asyncio.create_task(_get(env.app, wait=5, cursor=cursor))
    await asyncio.sleep(0.3)
    assert not task.done(), "the call answered without waiting"
    m = _post(env.db, 1)
    t0 = time.monotonic()
    await cs.fan_out_message(CONV, "dm", {"id": m.id, "seq": 1}, [_agent_recipient()], "sender")
    r = await asyncio.wait_for(task, 3.0)
    elapsed = time.monotonic() - t0
    body = r.json()
    assert r.status_code == 200, body
    assert elapsed < 1.0, f"answered {elapsed:.2f} s after the message"
    assert [x["id"] for x in body["messages"]] == [m.id]
    assert body["woken"] is True and body["wait_s"] == 5 and body["next_cursor"] != cursor


async def test_a_waiting_call_answers_empty_at_the_bound(env):
    # BASE: no next_cursor; the call answers at once
    cursor = await _start(env)
    t0 = time.monotonic()
    r = await _get(env.app, wait=1, cursor=cursor)
    elapsed = time.monotonic() - t0
    body = r.json()
    assert r.status_code == 200 and 0.9 <= elapsed < 3.0, (r.status_code, elapsed)
    assert body["messages"] == [] and body["woken"] is False and body["wait_s"] == 1 and body["next_cursor"]
    assert 900 <= body["waited_ms"] < 3000
    assert (await _get(env.app, cursor=body["next_cursor"])).json()["messages"] == []


async def test_while_it_waits_it_holds_no_connection_and_runs_no_query(env):
    # BASE: one query and an immediate answer, never a close-then-wait
    cursor = await _start(env)
    env.logged.log.clear()
    task = asyncio.create_task(_get(env.app, wait=3, cursor=cursor))
    await asyncio.sleep(0.4)
    assert env.logged.log == ["execute", "close"], env.logged.log    # one query, then the session handed back
    await asyncio.sleep(0.6)
    assert env.logged.log == ["execute", "close"], env.logged.log    # nothing while idle
    m = _post(env.db, 1)
    await WS.manager.wake_chat({KEY})
    body = (await asyncio.wait_for(task, 3.0)).json()
    assert [x["id"] for x in body["messages"]] == [m.id]
    assert env.logged.log == ["execute", "close", "execute"], env.logged.log   # exactly one more query, on the wake


async def test_a_plain_call_waits_for_nothing_and_registers_nothing(env):
    # control on the branch (wait=0 is today's call); BASE: no next_cursor
    _post(env.db, 1)
    body = (await _get(env.app)).json()
    assert [x["id"] for x in body["messages"]] == ["m-1"] and body["wait_s"] == 0 and body["next_cursor"]
    assert WS.manager.chat_waiter_count(KEY) == 0


# ─────────────────────────────── waking ───────────────────────────────

class _FakePubSub:
    def __init__(self):
        self.channels, self.queue = set(), asyncio.Queue()

    async def subscribe(self, *channels):
        self.channels.update(channels)

    async def get_message(self, ignore_subscribe_messages=True, timeout=1.0):
        try:
            return await asyncio.wait_for(self.queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def unsubscribe(self, *a):
        pass

    async def close(self):
        pass


class _FakeRedis:
    """One Redis two workers share: a publish reaches every pubsub subscribed to its channel."""

    def __init__(self):
        self.pubsubs = []

    def pubsub(self):
        ps = _FakePubSub()
        self.pubsubs.append(ps)
        return ps

    async def publish(self, channel, data):
        for ps in self.pubsubs:
            if channel in ps.channels:
                ps.queue.put_nowait({"type": "message", "channel": channel, "data": data})
        return 1


async def test_a_wake_on_another_worker_ends_the_wait(env, monkeypatch):
    # BASE: the manager has no wake_chat
    r = _FakeRedis()

    async def _redis():
        return r
    monkeypatch.setattr(leader, "get_redis", _redis)
    a, b = WS.ConnectionManager(), WS.ConnectionManager()
    monkeypatch.setattr(WS, "manager", a)                 # the worker serving the waiting call
    cursor = await _start(env)
    task = asyncio.create_task(_get(env.app, wait=5, cursor=cursor))
    await asyncio.sleep(0.3)
    m = _post(env.db, 1)
    t0 = time.monotonic()
    await b.wake_chat({KEY})                              # the message was sent through another worker
    body = (await asyncio.wait_for(task, 3.0)).json()
    assert time.monotonic() - t0 < 1.0
    assert [x["id"] for x in body["messages"]] == [m.id] and body["woken"] is True
    channel = f"{a.REDIS_TOPIC_PREFIX}{a.CHAT_WAKE_TOPIC}"
    assert channel in a._subscribed_channels and channel not in b._subscribed_channels   # the publisher listens to nothing
    assert b._pubsub is None


async def test_a_wake_that_brings_nothing_for_the_caller_keeps_it_waiting(env):
    # BASE: no wake_chat, no wait
    s = env.db.sync
    s.add(models.Conversation(id="conv-2", kind="dm", created_by_ptype="agent", created_by_id=SENDER))
    s.add(models.ConversationParticipant(id="p-3", conversation_id="conv-2", ptype="agent", agent_did=AGENT,
                                         state="pending"))
    s.commit()
    cursor = await _start(env)
    t0 = time.monotonic()
    task = asyncio.create_task(_get(env.app, wait=1, cursor=cursor))
    await asyncio.sleep(0.3)
    _post(env.db, 1, conv="conv-2")                       # a request the agent has not accepted: not its message yet
    await WS.manager.wake_chat({KEY})
    body = (await asyncio.wait_for(task, 3.0)).json()
    assert body["messages"] == [] and time.monotonic() - t0 >= 0.9 and body["woken"] is True


async def test_more_waits_than_the_cap_are_refused_with_a_sentence(env, monkeypatch):
    # BASE: both calls answer 200 at once
    monkeypatch.setattr(cs, "SYNC_WAITERS_PER_PRINCIPAL", 1)
    cursor = await _start(env)
    task = asyncio.create_task(_get(env.app, wait=1, cursor=cursor))
    await asyncio.sleep(0.3)
    r = await _get(env.app, wait=1, cursor=cursor)
    assert r.status_code == 429 and "waiting sync calls" in r.json()["detail"], r.text
    assert (await asyncio.wait_for(task, 3.0)).status_code == 200


async def test_a_cancelled_wait_leaves_no_waiter(env):
    # BASE: sync_wait does not exist
    task = asyncio.create_task(cs.sync_wait(env.logged, cs.Actor("agent", agent_did=AGENT), wait_s=5))
    await asyncio.sleep(0.3)
    assert WS.manager.chat_waiter_count(KEY) == 1
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert WS.manager.chat_waiter_count(KEY) == 0


@pytest.mark.parametrize("params,words", [
    ({"wait": 26}, None),
    ({"wait": -1}, None),
    ({"cursor": "not-a-cursor"}, "cursor is not one this registry gave out"),
    ({"cursor": "x", "since": "2026-10-31T00:00:00+00:00"}, "give since or cursor, not both"),
])
async def test_a_bad_wait_or_cursor_is_the_callers_422(env, params, words):
    # BASE: the unknown parameters are dropped and the call answers 200
    r = await _get(env.app, **params)
    assert r.status_code == 422, r.text
    if words:
        assert words in json.dumps(r.json())
    assert WS.manager.chat_waiter_count(KEY) == 0


def test_control_the_wake_topic_is_never_a_socket_topic():
    # control: passes on V0649 too (topic_allowed refuses every chat: topic but the caller's own)
    assert WS.topic_allowed({"id": "5"}, "chat:wake") is False
    assert WS.topic_allowed({"id": "5", "is_admin": True}, "chat:wake") is False


# ─────────────────────────────── the fan-out ───────────────────────────────

async def test_the_fan_out_wakes_the_owners_the_household_and_the_agents_once(monkeypatch):
    # BASE: fan_out_message wakes nobody
    _stub_delivery(monkeypatch)
    woken, sent = [], []

    class _Manager:
        async def broadcast_to_subscribers(self, topic, envelope):
            sent.append(topic)

        async def is_present(self, dev_id):
            return False

        async def wake_chat(self, keys):
            woken.append(set(keys))
    monkeypatch.setattr(WS, "manager", _Manager())
    recipients = [{"ptype": "developer", "agent_did": None, "developer_id": 3, "owner_developer_id": 3, "muted": False},
                  _agent_recipient("did:theprotocol:eu.test:Mixed-Case", owner=7)]
    await cs.fan_out_message(CONV, "dm", {"id": "m-9", "seq": 9}, recipients, "sender", sender_owner_dev_id=9)
    assert woken == [{"dev:3", "dev:7", "dev:9", "agt:did:theprotocol:eu.test:mixed-case"}]
    assert sorted(sent) == ["chat:dev:3", "chat:dev:7", "chat:dev:9"]


async def test_control_a_manager_without_waiters_still_gets_the_socket_sends(monkeypatch):
    # control: passes on V0649 too (an older manager, or a stand-in, has no wake_chat)
    _stub_delivery(monkeypatch)
    sent = []

    class _Old:
        async def broadcast_to_subscribers(self, topic, envelope):
            sent.append(topic)

        async def is_present(self, dev_id):
            return False
    monkeypatch.setattr(WS, "manager", _Old())
    await cs.fan_out_message(CONV, "dm", {"id": "m-9", "seq": 9}, [_agent_recipient()], "sender")
    assert sent == ["chat:dev:7"]
