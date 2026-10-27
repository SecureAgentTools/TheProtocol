"""§TWOAGENT #2 (2026-09-23) — the knocker hears that its request was ACCEPTED.

Measured on ASIA (V0430): #1 pushes a stranger's knock to the recipient's owner (`chat.request.received`), but when the
recipient accepts, nothing reaches the knocker. `chat.message.received` fires only for a MESSAGE, and an accept is a
state change, so the run's knocker (the courier) polled its thread for minutes to learn that the door had opened.

Now `chat.request.accepted` is in the vocabulary and `set_state` sends it after the commit, owner-scoped: to the owner
of an agent knocker, or to a developer knocker itself. Only a real pending -> active flip counts. A DECLINE sends
nothing, on purpose: a refusal the knocker cannot see is the consent half of the Requests lane.

RED on V0430: the event is not in the vocabulary, the helpers do not exist and an accept sends nothing. The controls (a
decline sends nothing; a notice is never broadcast) pass on both trees.
"""
from __future__ import annotations

import asyncio
import types

from agentvault_registry.services import chat_service as cs

KNOCKER = "did:theprotocol:asia.test:courier"
TARGET = "did:theprotocol:asia.test:assay-child"


def _conv(created_by_ptype="agent", created_by_id=KNOCKER):
    return types.SimpleNamespace(id="conv-1", kind="dm", created_by_ptype=created_by_ptype, created_by_id=created_by_id)


def _row(state="pending", ptype="agent", did=TARGET, dev=None):
    return types.SimpleNamespace(ptype=ptype, agent_did=did, developer_id=dev, state=state)


def test_the_vocabulary_names_the_event():
    from agentvault_registry.services.webhook_service import WebhookService
    assert "chat.request.accepted" in WebhookService.SUPPORTED_EVENTS


def test_an_accept_of_a_pending_knock_names_the_knocker():
    n = cs.accepted_knock_notice(_conv(), "pending", "active", _row())
    assert n == {"conversation_id": "conv-1", "kind": "dm", "knocker_ptype": "agent", "knocker_id": KNOCKER,
                 "accepted_by_ptype": "agent", "accepted_by": TARGET}


def test_only_a_real_flip_counts():
    assert cs.accepted_knock_notice(_conv(), "pending", "left", _row()) is None     # a decline: silent by design
    assert cs.accepted_knock_notice(_conv(), "active", "left", _row()) is None      # a leave
    assert cs.accepted_knock_notice(_conv(created_by_id=TARGET), "pending", "active", _row()) is None  # own thread


async def test_the_notice_goes_to_the_knockers_owner_only(monkeypatch):
    got: list = []

    async def _owner_dispatch(event, data, dids, source_label="endpoint"):
        got.append((event, tuple(dids), data.get("accepted_by_name")))
        return 1

    async def _scoped_or_broadcast(event, data, *, source_label="reactor", developer_id=None):
        got.append((event, "developer", developer_id))
        return 1
    from agentvault_registry.background_tasks import reactor_helpers as rh
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _owner_dispatch)
    monkeypatch.setattr(rh, "dispatch_webhook_event", _scoped_or_broadcast)
    await cs.notify_request_accepted(cs.accepted_knock_notice(_conv(), "pending", "active", _row()), "Assay Child")
    await cs.notify_request_accepted(
        cs.accepted_knock_notice(_conv("developer", "41"), "pending", "active", _row()), "Assay Child")
    assert got == [("chat.request.accepted", (KNOCKER,), "Assay Child"),
                   ("chat.request.accepted", "developer", 41)], got


def _wire_set_state(monkeypatch, row):
    sent: list = []

    async def _get(db, cid):
        return _conv()

    async def _member(db, conv, actor, **kw):
        return row

    async def _names(db, keys):
        return {k: "Assay Child" for k in keys}

    async def _notify(notice, name):
        sent.append((notice["knocker_id"], notice["accepted_by"], name))
        return 1
    monkeypatch.setattr(cs, "_get_conversation", _get)
    monkeypatch.setattr(cs, "resolve_membership", _member)
    monkeypatch.setattr(cs, "display_names", _names)
    monkeypatch.setattr(cs, "notify_request_accepted", _notify, raising=False)
    return sent


class _Db:
    async def commit(self):
        return None


async def _act(action):
    actor = cs.Actor("agent", agent_did=TARGET, display_name=TARGET)
    out = await cs.set_state(_Db(), "conv-1", actor, action)
    for _ in range(5):
        await asyncio.sleep(0)
    return out


async def test_an_accept_tells_the_knocker_after_the_commit(monkeypatch):
    sent = _wire_set_state(monkeypatch, _row("pending"))
    out = await _act("accept")
    assert out == {"conversation_id": "conv-1", "my_state": "active"}
    assert sent == [(KNOCKER, TARGET, "Assay Child")], sent


async def test_control_a_decline_tells_nobody(monkeypatch):
    sent = _wire_set_state(monkeypatch, _row("pending"))
    out = await _act("decline")
    assert out["my_state"] == "left"
    assert sent == []
