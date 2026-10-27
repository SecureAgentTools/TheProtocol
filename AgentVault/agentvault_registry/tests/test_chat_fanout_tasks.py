"""D6-826 (agentvault2-aa, 2026-10-26): a chat delivery cannot vanish, cannot fail unheard, and one slow notice holds
nobody else back.

The federation suite's chat_g1 control legs (the nightly pairs nt261025 and nt261026; four misses in the sixty runs
before) saw a message the host had stored never reach the other owner's hook, still nothing minutes later. Two shapes in
services/chat_service.fan_out_message could produce that, and both are measured here:
  * every delivery ran as asyncio.create_task(...) with the task dropped, and the loop keeps a task only weakly: a task
    nothing else holds can be collected before it completes, and a failure in one was never read (debug logs);
  * the owners' webhook was created only after every developer's offline notice had been awaited, and a notice ends in
    the themed mail: one hung notice held back the webhook, the WS sends after it and the next developer's notice.
RED at 1b7ba59f (V0643's cut): the four control tests below (the webhook, the WS sends, the next developer, the
collection); spawn() and deliver() do not exist there.

The tests drive asyncio.run themselves, so they run the same under any pytest-asyncio mode.
"""
from __future__ import annotations

import asyncio
import gc
import logging
import sys
import types
import weakref

AGENT = "did:theprotocol:sandbox-a.test:n"
MSG = {"id": "m-826", "seq": 3, "body": "control w->n"}


def _modules(monkeypatch, notify, dispatch, sent):
    """The three modules fan_out_message imports at call time, as stand-ins: the WS manager records its sends and finds
    nobody present; notify and the owner-scoped webhook dispatch are the test's."""
    class _Manager:
        async def broadcast_to_subscribers(self, topic, envelope):
            sent.append(topic)

        async def is_present(self, dev_id):
            return False

    ws = types.ModuleType("agentvault_registry.routers.websocket")
    ws.manager = _Manager()
    pn = types.ModuleType("agentvault_registry.background_tasks.push_notify")
    pn.notify = notify
    rh = types.ModuleType("agentvault_registry.background_tasks.reactor_helpers")
    rh.dispatch_webhook_for_agents = dispatch
    for mod in (ws, pn, rh):
        monkeypatch.setitem(sys.modules, mod.__name__, mod)


def _agent_with_owner():
    return [{"ptype": "agent", "agent_did": AGENT, "developer_id": None, "owner_developer_id": 7, "muted": False}]


def _two_developers():
    return [{"ptype": "developer", "agent_did": None, "developer_id": d, "owner_developer_id": d, "muted": False}
            for d in (1, 2)]


async def _hang(*a, **k):
    await asyncio.Event().wait()


async def _told_nothing(*a, **k):
    return 0


async def _until(cond, seconds=1.0):
    for _ in range(int(seconds / 0.01)):
        if cond():
            return True
        await asyncio.sleep(0.01)
    return cond()


class _Lines(logging.Handler):
    """chat_service's own log lines, read off its logger (independent of how the registry configures propagation)."""

    def __init__(self, cs):
        super().__init__(logging.INFO)
        self.cs, self.lines, self.level0 = cs, [], cs.logger.level

    def emit(self, record):
        self.lines.append(record.getMessage())

    def __enter__(self):
        self.cs.logger.addHandler(self)
        self.cs.logger.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        self.cs.logger.removeHandler(self)
        self.cs.logger.setLevel(self.level0)


def test_a_hung_notice_does_not_hold_the_owners_webhook(monkeypatch):
    from agentvault_registry.services import chat_service as cs
    told, sent = [], []

    async def dispatch(event_type, data, dids, source_label=""):
        told.append((event_type, list(dids), data["message"]["id"]))
        return 1
    _modules(monkeypatch, _hang, dispatch, sent)

    async def main():
        fan = asyncio.create_task(cs.fan_out_message("conv-826", "dm", dict(MSG), _agent_with_owner(), "W"))
        ok = await _until(lambda: bool(told))
        return ok, fan

    with _Lines(cs) as log:
        ok, _ = asyncio.run(main())
    assert ok, "the owner's hook was not told while the owner's notice hung"
    assert told == [("chat.message.received", [AGENT], "m-826")]
    assert any("chat.message.received for message m-826 (seq 3) in conv-826: 1 agent recipient(s), 1 hook(s) told" in ln
               for ln in log.lines), log.lines


def test_a_hung_notice_does_not_hold_the_ws_sends_after_it(monkeypatch):
    from agentvault_registry.services import chat_service as cs
    sent = []
    _modules(monkeypatch, _hang, _told_nothing, sent)

    async def main():
        fan = asyncio.create_task(cs.fan_out_message("conv-826", "dm", dict(MSG), _two_developers(), "W"))
        ok = await _until(lambda: len(sent) == 2)
        return ok, fan

    ok, _ = asyncio.run(main())
    assert ok, f"WS sends while the first developer's notice hung: {sent}"
    assert sent == ["chat:dev:1", "chat:dev:2"]


def test_a_hung_notice_is_given_up_and_the_next_developer_is_told(monkeypatch):
    from agentvault_registry.services import chat_service as cs
    monkeypatch.setattr(cs, "NOTIFY_BOUND_S", 0.05, raising=False)
    notified = []

    async def notify(kind, devs, **k):
        if devs == [1]:
            await asyncio.Event().wait()
        notified.append(devs[0])
        return 1
    _modules(monkeypatch, notify, _told_nothing, [])

    async def main():
        fan = asyncio.create_task(cs.fan_out_message("conv-826", "dm", dict(MSG), _two_developers(), "W"))
        ok = await _until(lambda: notified == [2])
        return ok, fan

    with _Lines(cs) as log:
        ok, _ = asyncio.run(main())
    assert ok, f"developers told while developer 1's notice hung: {notified}"
    assert any("the notice of message m-826 in conv-826 to developer 1 took over 0.05s: given up" in ln
               for ln in log.lines), log.lines


def test_a_delivery_task_nothing_else_holds_survives_a_collection(monkeypatch):
    """The control for the weak reference: the owner's webhook waits on something only its own frame holds (as an
    await on a resource nothing anchors would), the test drops every reference it could have, and collects."""
    from agentvault_registry.services import chat_service as cs
    held = []

    async def dispatch(event_type, data, dids, source_label=""):
        held.append(weakref.ref(asyncio.current_task()))
        await asyncio.get_running_loop().create_future()
    _modules(monkeypatch, _told_nothing, dispatch, [])

    async def main():
        await cs.fan_out_message("conv-826", "dm", dict(MSG), _agent_with_owner(), "W")
        if not await _until(lambda: bool(held)):
            return "the webhook never started"
        gc.collect()
        await asyncio.sleep(0)
        task = held[0]()
        return "alive" if task is not None and not task.done() else "collected before it finished"

    assert asyncio.run(main()) == "alive"


def test_a_spawned_task_that_raises_is_logged_with_its_name_and_released():
    from agentvault_registry.services import chat_service as cs

    async def boom():
        raise RuntimeError("the owner's hook could not be resolved")

    async def main():
        task = cs.spawn(boom(), what="the delivery of message m-826")
        assert task in cs._BACKGROUND
        await asyncio.sleep(0.05)
        return task

    with _Lines(cs) as log:
        task = asyncio.run(main())
    assert task.done() and task not in cs._BACKGROUND
    assert any("the delivery of message m-826 failed: RuntimeError: the owner's hook could not be resolved" in ln
               for ln in log.lines), log.lines


def test_deliver_names_the_message_and_its_recipients_kinds(monkeypatch):
    from agentvault_registry.services import chat_service as cs

    async def fails(*a, **k):
        raise ConnectionError("no route to the event store")
    monkeypatch.setattr(cs, "fan_out_message", fails)

    async def main():
        task = cs.deliver("conv-826", "dm", dict(MSG), _agent_with_owner() + _two_developers(), "W")
        await asyncio.sleep(0.05)
        return task

    with _Lines(cs) as log:
        task = asyncio.run(main())
    assert task.done() and not cs._BACKGROUND
    assert any("the delivery of message m-826 (seq 3) in conv-826 to 3 recipient(s) (agent, developer) failed: "
               "ConnectionError: no route to the event store" in ln for ln in log.lines), log.lines
