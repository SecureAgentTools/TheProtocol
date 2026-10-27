"""SEC-02 (§SECBATCH wave 3, 2026-10-16): with Redis unreachable, a socket's topic subscription returns, and the
worker's later connects and broadcasts do not wait behind it.

Measured on the base (1032dca8): ConnectionManager._ensure_topic_subscribed held the non-reentrant _pubsub_lock and,
with no Pub/Sub connection (Redis unreachable since the process started, or a listener that died), awaited
_ensure_pubsub, which waits for the same lock: the task waited on itself for ever while holding the lock. Every socket
subscribes its chat topic on connect (as a background task), so with Redis unreachable the first socket left the lock
held: the next socket's connect never sent "connected", and a topic broadcast (notify_agent_update and the others)
never returned. Even with Redis reachable, a first subscription before any listener had started waited on itself.

Why no test caught it: the socket tests replace the manager with a fake (test_twoagent_ws_topics_and_owner_notices) or
test the parts that take no lock; none ran the real manager with Redis unreachable.

The socket runs through FastAPI on the real router (/ws), driven as an ASGI websocket with every wait bounded; only the
socket's caller (its auth dependency), the session and Redis (get_redis raises: unreachable) are supplied.
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import websocket as WS

WAIT = 2.0          # seconds: everything here answers in milliseconds; on the base the waits never end


async def _redis_unreachable():
    raise ConnectionError("Redis unreachable (test)")


class _NoDb:
    async def execute(self, *a, **k):
        raise RuntimeError("no database in this test")


class Socket:
    """One ASGI websocket connection to the app, every wait bounded by WAIT."""

    def __init__(self, app, path="/ws"):
        self.to_app, self.from_app = asyncio.Queue(), asyncio.Queue()
        scope = {"type": "websocket", "asgi": {"version": "3.0"}, "scheme": "ws", "path": path,
                 "raw_path": path.encode(), "root_path": "", "query_string": b"", "headers": [],
                 "subprotocols": [], "client": ("127.0.0.1", 50000), "server": ("testserver", 80)}
        self.task = asyncio.create_task(app(scope, self.to_app.get, self.from_app.put))

    async def open(self):
        await self.to_app.put({"type": "websocket.connect"})
        msg = await asyncio.wait_for(self.from_app.get(), WAIT)
        assert msg["type"] == "websocket.accept", msg

    async def send_json(self, obj):
        await self.to_app.put({"type": "websocket.receive", "text": json.dumps(obj)})

    async def receive_json(self):
        msg = await asyncio.wait_for(self.from_app.get(), WAIT)
        assert msg["type"] == "websocket.send", msg
        return json.loads(msg["text"])


@pytest.fixture()
async def stray_tasks():
    """Cancels what a test leaves running (on the base: the tasks waiting on the lock for ever)."""
    before = set(asyncio.all_tasks())
    yield
    left = [t for t in asyncio.all_tasks() - before if t is not asyncio.current_task()]
    for t in left:
        t.cancel()
    await asyncio.gather(*left, return_exceptions=True)


@pytest.fixture()
def unreachable(monkeypatch, stray_tasks):
    monkeypatch.setattr(leader, "get_redis", _redis_unreachable)
    monkeypatch.setattr(WS, "manager", WS.ConnectionManager())       # a fresh manager, and lock, for this test


async def test_with_redis_unreachable_a_second_socket_connects_and_a_topic_broadcast_arrives(unreachable):
    app = FastAPI()
    app.include_router(WS.router)
    callers = [SimpleNamespace(id=1, email="d1@example.org", name="d1", is_admin=False),
               SimpleNamespace(id=2, email="d2@example.org", name="d2", is_admin=False)]

    async def _caller():
        return callers.pop(0)

    async def _db():
        yield _NoDb()

    app.dependency_overrides[WS.get_current_user_ws] = _caller
    app.dependency_overrides[get_db] = _db

    first = Socket(app)
    await first.open()
    assert (await first.receive_json())["type"] == "connected"
    await first.send_json({"type": "ping", "data": {"timestamp": 1}})      # its chat subscription has run meanwhile
    assert (await first.receive_json())["type"] == "pong"

    second = Socket(app)
    await second.open()
    hello = await second.receive_json()          # the base: TimeoutError, connect waits on the lock for ever
    assert hello["type"] == "connected", hello

    await asyncio.wait_for(WS.manager.broadcast_to_subscribers("chat:dev:2", {"type": "chat.message", "data": {}}),
                           WAIT)
    assert (await second.receive_json())["type"] == "chat.message"         # delivered on this worker without Redis


async def test_the_subscribe_path_returns_with_redis_unreachable(unreachable):
    m = WS.manager
    await asyncio.wait_for(m._ensure_topic_subscribed("agent:did:theprotocol:x"), WAIT)    # the base: TimeoutError
    await asyncio.wait_for(m._ensure_topic_subscribed("agent:did:theprotocol:x"), WAIT)    # and the lock is free again
    await asyncio.wait_for(m.broadcast_to_subscribers("agent:did:theprotocol:x", {"type": "agent.update"}), WAIT)
    assert m._pubsub is None and not m._pubsub_lock.locked()


class _PubSub:
    def __init__(self):
        self.channels = []

    async def subscribe(self, *channels):
        self.channels.extend(channels)

    async def get_message(self, **kw):
        await asyncio.sleep(0.01)
        return None

    async def unsubscribe(self, *a):
        pass

    async def close(self):
        pass


async def test_with_redis_reachable_a_first_subscription_starts_the_listener_and_subscribes(monkeypatch, stray_tasks):
    pubsub = _PubSub()

    async def _redis():
        return SimpleNamespace(pubsub=lambda: pubsub)

    monkeypatch.setattr(leader, "get_redis", _redis)
    m = WS.ConnectionManager()
    await asyncio.wait_for(m._ensure_topic_subscribed("agent:did:theprotocol:y"), WAIT)    # the base: TimeoutError
    assert pubsub.channels == [m.REDIS_BROADCAST_CHANNEL, f"{m.REDIS_TOPIC_PREFIX}agent:did:theprotocol:y"]
    assert m._pubsub_task is not None and not m._pubsub_task.done()
    m._pubsub_task.cancel()
