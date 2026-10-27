"""§TWOAGENT G1 step 4c (2026-09-23) — a hosted message and its delivery rows commit together, or not at all.

Map item 8, the at-least-once hole. Both host paths committed the message in its own transaction and queued its
delivery rows AFTER, in a second one: `_send_and_fan_out` only logged an enqueue failure ("never fail a local send on
federation"), and relay-send answered a 500 to the sender's home while the message stood stored at the host. A retry of
the same client_ref then returned "duplicate" before any enqueue. Either way a hosted message could exist that no other
registry would ever receive, and the sender's home never learned its canonical seq. Now the rows are written after the
flush and before the commit (`before_commit`), and a failure stores nothing and says so (503, retry).

RED on d9228a66: every test but the control.
"""
from __future__ import annotations

import types

import pytest


class _R:
    def __init__(self, v=None):
        self.v = v

    def scalars(self):
        return self

    def first(self):
        return self.v

    def scalar_one(self):
        return self.v[0]


class _Db:
    """Logs the order of the writes; the dedup lookup finds nothing and the seq update answers `seq`."""

    def __init__(self, seq):
        self.seq, self.log = seq, []

    async def execute(self, stmt, params=None):
        if "UPDATE conversations" in str(stmt):
            self.log.append("seq")
            return _R((self.seq,))
        return _R(None)

    def add(self, o):
        self.log.append("add")

    async def flush(self):
        self.log.append("flush")

    async def commit(self):
        self.log.append("commit")

    async def rollback(self):
        self.log.append("rollback")


def _chat(monkeypatch):
    from agentvault_registry.services import chat_service as cs

    async def _open(*a, **k):
        return None
    monkeypatch.setattr(cs, "room_posting_gate", _open)
    return cs


async def test_a_hosted_message_and_its_delivery_rows_commit_together(monkeypatch):
    cs = _chat(monkeypatch)
    db = _Db(5)

    async def _queue(m):
        db.log.append(f"queue:{m.seq}")
    msg, dup = await cs.insert_message(db, types.SimpleNamespace(id="c1", kind="dm"),
                                       types.SimpleNamespace(state="active", last_read_seq=0),
                                       cs.Actor("agent", agent_did="did:theprotocol:p", display_name="P"),
                                       "text", "hello", None, "ref-12345678", before_commit=_queue)
    assert dup is False and db.log[-3:] == ["flush", "queue:5", "commit"]


async def test_the_host_stores_a_relayed_message_with_its_delivery_rows(monkeypatch):
    cs = _chat(monkeypatch)
    db = _Db(7)

    async def _queue(m):
        db.log.append(f"queue:{m.seq}")
    msg, dup = await cs.insert_remote_message(db, types.SimpleNamespace(id="c1", kind="dm"),
                                              types.SimpleNamespace(state="active"),
                                              "did:theprotocol:w@https://sandbox-b.test", "W", "text", "hi", None,
                                              "ref-12345678", before_commit=_queue)
    assert dup is False and db.log[-3:] == ["flush", "queue:7", "commit"]


def _sender(monkeypatch, fed_on: bool):
    if fed_on:
        monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    else:
        monkeypatch.delenv("CHAT_FEDERATION_ENABLED", raising=False)
    from agentvault_registry.routers import chat as chat_router
    from agentvault_registry.services import chat_federation as fed
    cs = _chat(monkeypatch)

    async def _yes(*a, **k):
        return True

    async def _named(db, actor):
        return actor

    async def _none(*a, **k):
        return None

    async def _no_one(*a, **k):
        return []
    monkeypatch.setattr(cs, "_rate_gate", _yes)
    monkeypatch.setattr(chat_router, "_named_sender", _named)
    monkeypatch.setattr(chat_router, "_sender_owner_dev_id", _none)
    monkeypatch.setattr(cs, "recipients_snapshot", _no_one)
    monkeypatch.setattr(cs, "fan_out_message", _none)
    return chat_router, fed, cs


async def test_when_the_delivery_rows_cannot_be_written_nothing_is_stored(monkeypatch):
    chat_router, fed, cs = _sender(monkeypatch, fed_on=True)

    async def _boom(*a, **k):
        raise RuntimeError("the outbox table is unreachable")
    monkeypatch.setattr(fed, "enqueue_delivery", _boom)
    db = _Db(9)
    with pytest.raises(cs.ChatError) as e:
        await chat_router._send_and_fan_out(db, types.SimpleNamespace(id="c1", kind="dm", host_registry=None),
                                            types.SimpleNamespace(state="active", last_read_seq=0),
                                            cs.Actor("agent", agent_did="did:theprotocol:p", display_name="P"),
                                            "text", "hello", None, "ref-12345678")
    assert e.value.status_code == 503 and "commit" not in db.log and "rollback" in db.log


async def test_control_without_federation_a_send_carries_no_hook(monkeypatch):
    chat_router, fed, cs = _sender(monkeypatch, fed_on=False)
    seen: dict = {}

    async def _insert(db, conv, row, sender, kind, body, card, client_ref, reply_to=None, **kw):
        seen.update(kw)
        return types.SimpleNamespace(seq=3, id="m1"), False
    monkeypatch.setattr(cs, "insert_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"seq": m.seq})
    out = await chat_router._send_and_fan_out(_Db(3), types.SimpleNamespace(id="c1", kind="dm", host_registry=None),
                                              types.SimpleNamespace(state="active"),
                                              cs.Actor("agent", agent_did="did:theprotocol:p", display_name="P"),
                                              "text", "hello", None, "ref-12345678")
    assert out["seq"] == 3 and seen.get("before_commit") is None


async def test_relay_send_queues_inside_the_insert_and_refuses_by_name_when_it_cannot(monkeypatch):
    monkeypatch.setenv("CHAT_FEDERATION_ENABLED", "true")
    from fastapi import HTTPException
    from agentvault_registry.routers import chat_federation as route
    from agentvault_registry.services import chat_federation as fed
    from agentvault_registry.services import chat_service as cs
    conv = types.SimpleNamespace(id="host-conv-1", kind="dm", host_registry=None)
    part = types.SimpleNamespace(ptype="remote", remote_key="did:theprotocol:w@https://sandbox-b.test", state="active")
    calls: list = []

    class _Q:
        n = 0

        async def execute(self, stmt, params=None):
            self.n += 1
            return _R(conv if self.n == 1 else part)

        async def commit(self):
            calls.append("commit")

        async def rollback(self):
            calls.append("rollback")

    async def _yes(*a, **k):
        return True

    async def _allowed(db, base):
        return "sandbox-b"

    async def _insert(db, c, p, key, disp, kind, body, card, ref, **kw):
        hook = kw.get("before_commit")
        calls.append("hook" if hook else "no-hook")
        if hook:
            await hook(types.SimpleNamespace(seq=4))
        return types.SimpleNamespace(seq=4), False

    async def _boom(*a, **k):
        raise RuntimeError("the outbox table is unreachable")
    monkeypatch.setattr(fed, "assert_peer_allowed", _allowed)
    monkeypatch.setattr(fed, "caller_is", _yes)
    monkeypatch.setattr(fed, "fed_rate_ok", _yes)
    async def _no_one(*a, **k):
        return []

    async def _none(*a, **k):
        return None
    monkeypatch.setattr(fed, "enqueue_delivery", _boom)
    monkeypatch.setattr(cs, "insert_remote_message", _insert)
    monkeypatch.setattr(cs, "serialize_message", lambda m: {"seq": m.seq})
    monkeypatch.setattr(cs, "recipients_snapshot", _no_one)
    monkeypatch.setattr(cs, "fan_out_message", _none)
    req = route.RelaySend(conversation_ref="host-conv-1", sender_key="did:theprotocol:w@https://sandbox-b.test",
                          client_ref="ref-12345678", body="hi")
    with pytest.raises(HTTPException) as e:
        await route.relay_send(req, peer="spiffe://sandbox-b.test/service/registry", db=_Q())
    assert e.value.status_code == 503 and calls == ["hook", "rollback"]
