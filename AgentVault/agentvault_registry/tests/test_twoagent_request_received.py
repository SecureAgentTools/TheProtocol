"""§TWOAGENT #1 (2026-09-23) — a stranger's knock on an AGENT is pushed to the agent's owner.

Measured on EU and on ASIA (V0425/V0426): a dm from another developer's agent lands the target agent's row 'pending'
(its Requests lane), and `chat.message.received` never fires for it, because `recipients_snapshot` selects ACTIVE
participants only. A webhook-driven agent therefore could not hear a first contact at all; it had to poll
`GET /api/v1/chat/conversations?state=requests`. The puppet's auto-accept could never trigger from a push.

Now `chat.request.received` is in the vocabulary and the conversation-create route sends it, owner-scoped, when (and
only when) the target is an agent whose row came out 'pending'.

RED on V0429: the event is not in the vocabulary, the helpers do not exist and the route sends nothing. The controls (a
sibling's thread, born active, sends no request notice; a notice is never broadcast) pass on both trees.
"""
from __future__ import annotations

import asyncio
import types

import pytest

from agentvault_registry.routers import chat as chat_router
from agentvault_registry.services import chat_service as cs

CALLER = "did:theprotocol:eu.test:stranger"
TARGET = "did:theprotocol:asia.test:assay"


def test_the_vocabulary_names_the_event():
    from agentvault_registry.services.webhook_service import WebhookService
    assert "chat.request.received" in WebhookService.SUPPORTED_EVENTS


async def test_the_notice_goes_to_the_recipients_owner_only(monkeypatch):
    received: list = []

    async def _owner_dispatch(event, data, dids, source_label="endpoint"):
        received.append((event, tuple(dids), sorted(data)))
        return 1

    async def _broadcast(*a, **k):
        received.append(("BROADCAST",))
        return 1
    from agentvault_registry.background_tasks import reactor_helpers as rh
    monkeypatch.setattr(rh, "dispatch_webhook_for_agents", _owner_dispatch)
    monkeypatch.setattr(rh, "dispatch_webhook_event", _broadcast)
    await cs.notify_request_received("conv-1", "dm", TARGET, {"id": "m1", "body": "hello"}, "Stranger")
    assert received == [("chat.request.received", (TARGET,),
                         ["answer_with", "conversation_id", "kind", "message", "recipient_agent_did", "sender_name"])]


def _wire_route(monkeypatch, target_state):
    sent: list = []
    conv = types.SimpleNamespace(id="conv-1", kind="dm")
    my_row = types.SimpleNamespace(state="active")

    async def _create(db, actor, kind, t_type, t_id, intro_payment_ref=None):
        return conv, True, my_row

    async def _send(db, conv, my_row, actor, kind, body, card, client_ref, reply_to=None, **kw):
        return {"id": "m1", "seq": 1, "body": body}

    async def _pending(db, conv, t_type, t_id):
        return t_id if (t_type == "agent" and target_state == "pending") else None

    async def _notify(conv_id, kind, did, message, sender_name):
        sent.append((conv_id, did, message.get("body"), sender_name))
        return 1
    monkeypatch.setattr(cs, "create_conversation", _create)
    monkeypatch.setattr(chat_router, "_send_and_fan_out", _send)
    monkeypatch.setattr(cs, "pending_agent_target", _pending, raising=False)
    monkeypatch.setattr(cs, "notify_request_received", _notify, raising=False)
    return sent


async def _knock():
    req = chat_router.ConversationCreate(kind="dm", target=chat_router.TargetSpec(ptype="agent", agent_did=TARGET),
                                         first_message=chat_router.FirstMessage(body="R2 knock", client_ref="ref-12345678"))
    actor = {"kind": "agent", "agent_did": CALLER, "agent": types.SimpleNamespace(name="Stranger")}
    out = await chat_router.create_conversation(req=req, actor_dict=actor, db=None)
    for _ in range(5):
        await asyncio.sleep(0)
    return out


async def test_a_knock_on_an_agent_notifies_its_owner(monkeypatch):
    sent = _wire_route(monkeypatch, "pending")
    await _knock()
    assert sent == [("conv-1", TARGET, "R2 knock", "Stranger")], sent


async def test_control_a_thread_born_active_sends_no_request_notice(monkeypatch):
    sent = _wire_route(monkeypatch, "active")
    await _knock()
    assert sent == []
