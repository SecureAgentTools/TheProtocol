"""V0658 (n) (order gwo_2a1a2a21af4e9a6f45f97e23; the Commander, room seq 1838: in the desktop console other members' new
messages do not appear until F5). Measured on sbx-beta 2026-11-08 (V0659): one account with 6 sockets, 20 posts, 3 sockets
got all 20 and 3 got nothing, not even the metrics broadcast; one socket alone got 10 of 10 in 4 runs of 4.

The cause: the ConnectionManager kept ONE socket per user per worker (`active_connections[user_id] = websocket`). A second
socket of the same person on the same gunicorn worker (his desktop console and his phone, a second tab) replaced the
first, which stayed open and went silent; `disconnect(user_id)` dropped the user whichever socket closed; and every
connect reset the user's topic subscriptions.

Pinned here on a real ConnectionManager with fake sockets (no Redis: delivery is the local half the Pub/Sub listener
calls): every socket of a user gets a personal send, a broadcast and a topic send; closing one leaves the others live;
a socket that fails is dropped alone; a second connect keeps the user's subscriptions. Red on v0659/cut 966b74944.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.routers import websocket as WS


class FakeSocket:
    def __init__(self, name: str, fail: bool = False):
        self.name, self.fail, self.got = name, fail, []
        self.headers = {}

    async def accept(self, subprotocol=None):
        return None

    async def send_json(self, message):
        if self.fail:
            raise RuntimeError(f"{self.name} is gone")
        self.got.append(message.get("type"))


@pytest.fixture()
def mgr(monkeypatch):
    m = WS.ConnectionManager()

    async def _none():
        return None
    monkeypatch.setattr(m, "_get_redis", _none)          # no Redis: the local half only

    async def _present(*_a, **_k):
        return None
    monkeypatch.setattr(m, "mark_present", _present)
    monkeypatch.setattr(m, "clear_present", _present)
    return m


def run(c):
    return asyncio.run(c)


def _two(mgr, user="6"):
    a, b = FakeSocket("desktop"), FakeSocket("phone")
    run(mgr.connect(a, user, {"id": user, "email": "x@example.org"}))
    run(mgr.connect(b, user, {"id": user, "email": "x@example.org"}))
    a.got.clear(); b.got.clear()           # the "connected" frames
    return a, b


def test_a_personal_send_reaches_every_socket_of_the_user(mgr):
    a, b = _two(mgr)
    run(mgr.send_personal_message({"type": "notification", "data": {}}, "6"))
    assert a.got == ["notification"] and b.got == ["notification"]


def test_a_broadcast_reaches_every_socket_of_the_user(mgr):
    a, b = _two(mgr)
    run(mgr._local_broadcast({"type": "metrics.update", "data": {}}))
    assert a.got == ["metrics.update"] and b.got == ["metrics.update"]


def test_a_topic_send_reaches_every_socket_and_a_second_connect_keeps_the_subscriptions(mgr):
    a = FakeSocket("desktop")
    run(mgr.connect(a, "6", {"id": "6"}))
    mgr.subscribe("6", "chat:dev:6", a)        # what the endpoint does for every socket at its connect
    b = FakeSocket("phone")
    run(mgr.connect(b, "6", {"id": "6"}))   # used to reset subscriptions["6"] to an empty set, silencing a's topic
    assert "chat:dev:6" in mgr.subscriptions["6"]
    mgr.subscribe("6", "chat:dev:6", b)
    a.got.clear(); b.got.clear()
    run(mgr._local_broadcast_to_subscribers("chat:dev:6", {"type": "chat.message", "data": {}}))
    assert a.got == ["chat.message"] and b.got == ["chat.message"]


def test_closing_one_socket_leaves_the_others_live(mgr):
    a, b = _two(mgr)
    mgr.disconnect("6", a)
    run(mgr.send_personal_message({"type": "notification", "data": {}}, "6"))
    assert a.got == [] and b.got == ["notification"]
    assert "6" in mgr.active_connections          # still present: presence reads this
    mgr.disconnect("6", b)
    assert "6" not in mgr.active_connections and "6" not in mgr.subscriptions


def test_a_failing_socket_is_dropped_alone(mgr):
    a, b = _two(mgr)
    a.fail = True
    run(mgr._local_broadcast({"type": "metrics.update", "data": {}}))
    run(mgr.send_personal_message({"type": "notification", "data": {}}, "6"))
    assert b.got == ["metrics.update", "notification"]
    assert "6" in mgr.active_connections and mgr._sockets_of("6") == [b]     # the failing one went, alone


def test_the_endpoints_close_their_own_socket():
    """Every socket endpoint passes its own socket to disconnect, so a close never drops a sibling."""
    import inspect
    src = inspect.getsource(WS)
    bare = [line.strip() for line in src.splitlines()
            if "manager.disconnect(" in line and "," not in line.split("manager.disconnect(")[1]]
    assert bare == [], f"disconnect calls without their socket: {bare}"


def test_a_topic_is_kept_per_socket(mgr):
    """session-lead's seq 2495: subscriptions per socket. One tab unsubscribing a topic leaves the person's other socket
    subscribed; a socket that never subscribed to a topic gets none of it."""
    a, b = _two(mgr)
    mgr.subscribe("6", "agent:x", a)
    mgr.subscribe("6", "agent:x", b)
    mgr.unsubscribe("6", "agent:x", a)
    run(mgr._local_broadcast_to_subscribers("agent:x", {"type": "agent.updated", "data": {}}))
    assert a.got == [] and b.got == ["agent.updated"]
    assert "agent:x" in mgr.subscriptions["6"]
    mgr.subscribe("6", "agent:y", a)
    run(mgr._local_broadcast_to_subscribers("agent:y", {"type": "agent.updated", "data": {}}))
    assert a.got == ["agent.updated"] and b.got == ["agent.updated"]      # b got only agent:x's


def test_a_person_is_hidden_only_when_every_socket_is(mgr):
    a, b = _two(mgr)
    mgr.mark_shown("6", False, a)          # the phone in a pocket
    assert "6" not in mgr._hidden            # the desktop is still in view
    mgr.mark_shown("6", False, b)
    assert "6" in mgr._hidden
    mgr.mark_shown("6", True, a)
    assert "6" not in mgr._hidden
    mgr.disconnect("6", a)                   # the visible one closes: the hidden one is all that is left
    assert "6" in mgr._hidden


def test_a_reply_goes_to_the_socket_that_asked(mgr):
    a, b = _two(mgr)
    run(mgr.send_personal_message({"type": "subscribed", "data": {}}, "6", a))
    assert a.got == ["subscribed"] and b.got == []


def test_the_topic_subscribe_task_is_held_until_it_ends(mgr):
    async def go():
        a = FakeSocket("desktop")
        await mgr.connect(a, "6", {"id": "6"})
        mgr.subscribe("6", "chat:dev:6", a)
        held = set(mgr._bg)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        return held, set(mgr._bg)
    held, after = run(go())
    assert len(held) == 1 and after == set()


def test_the_greeting_goes_to_the_new_socket_only(mgr):
    """The "connected" frame is the new socket's own: the console emits every frame by its type, so a greeting sent to
    every socket of the person told the other tabs "connected" again (a "Connected" toast off the chat routes) each
    time the person opened another tab or the phone. Measured on the V0659 recut 8efa157b9691: with 6 sockets of one
    account, socket 0 got 6 greetings and socket 5 one."""
    a = FakeSocket("desktop")
    run(mgr.connect(a, "6", {"id": "6"}))
    b = FakeSocket("phone")
    run(mgr.connect(b, "6", {"id": "6"}))
    assert a.got == ["connected"] and b.got == ["connected"]
