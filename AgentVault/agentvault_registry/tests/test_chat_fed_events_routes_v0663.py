"""V0663 (order gwo_9dce94d939aff2fa8ea4f91c): the two federation doors for events (routers/chat_federation.py). /deliver tells an
event envelope from a message envelope and gives the event to the mirror's receive; /relay-event is the host's door for a request a
resident relayed. Both answer a ChatError as its own HTTP status (a 503 "not yet" is what makes the host send an event again), push to
this registry's members only when something changed, and never let a missed live push fail a change already stored."""
from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry.core.federation_auth import require_peer_registry_identity
from agentvault_registry.database import get_db
from agentvault_registry.routers import chat_federation as R
from agentvault_registry.services import chat_fed_events as fev
from agentvault_registry.services import chat_federation as fed
from agentvault_registry.services import chat_service as cs

PEER = "https://a.example"


def _app():
    app = FastAPI()
    app.include_router(R.router)

    async def _db():
        yield object()
    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[require_peer_registry_identity] = lambda: PEER
    return app


def _post(path, body):
    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_app()), base_url="http://t") as c:
            return await c.post(path, json=body)
    return asyncio.run(go())


EVENT = {"v": 1, "host_registry": PEER, "conversation": {"id": "r1", "kind": "room"},
         "event": {"id": "e1", "type": "edit", "message_seq": 3, "body": "x", "rev": 1}}


def test_an_event_envelope_goes_to_the_mirrors_receive_and_the_members_hear_it(monkeypatch):
    told = []

    async def receive(db, envelope, peer):
        assert peer == PEER and envelope["event"]["id"] == "e1"
        return {"conversation_id": "mir-1", "duplicate": False, "type": "edit", "message_id": "mm3"}

    async def announce(db, conv_id, event, *, message_id=None, actor_display=""):
        told.append((conv_id, event["type"], message_id))
    monkeypatch.setattr(fev, "receive_event", receive)
    monkeypatch.setattr(fev, "announce", announce)
    r = _post("/api/v1/federation/chat/deliver", EVENT)
    assert r.status_code == 200 and r.json()["duplicate"] is False
    assert told == [("mir-1", "edit", "mm3")]


def test_a_repeat_is_answered_ok_and_pushes_nothing(monkeypatch):
    told = []

    async def receive(db, envelope, peer):
        return {"conversation_id": "mir-1", "duplicate": True}

    async def announce(*a, **k):
        told.append(1)
    monkeypatch.setattr(fev, "receive_event", receive)
    monkeypatch.setattr(fev, "announce", announce)
    r = _post("/api/v1/federation/chat/deliver", EVENT)
    assert r.status_code == 200 and r.json()["duplicate"] is True and told == []


def test_the_not_yet_answer_is_a_503_so_the_host_sends_the_event_again_and_a_failed_push_fails_nothing(monkeypatch):
    async def not_yet(db, envelope, peer):
        raise cs.ChatError(503, "the message this event is about has not been delivered here yet")
    monkeypatch.setattr(fev, "receive_event", not_yet)
    r = _post("/api/v1/federation/chat/deliver", EVENT)
    assert r.status_code == 503 and "not been delivered here yet" in r.json()["detail"]

    async def receive(db, envelope, peer):
        return {"conversation_id": "mir-1", "duplicate": False, "type": "edit", "message_id": "mm3"}

    async def boom(*a, **k):
        raise RuntimeError("socket gone")
    monkeypatch.setattr(fev, "receive_event", receive)
    monkeypatch.setattr(fev, "announce", boom)
    assert _post("/api/v1/federation/chat/deliver", EVENT).status_code == 200      # the change is stored; only the push missed


def test_control_a_message_envelope_still_goes_to_receive_delivery(monkeypatch):
    seen = []

    async def delivery(db, envelope, peer):
        seen.append(envelope["message"]["seq"])
        return {"conversation_id": "c", "duplicate": True}

    async def no_event(*a, **k):
        raise AssertionError("a message must not reach the event receive")
    monkeypatch.setattr(fed, "receive_delivery", delivery)
    monkeypatch.setattr(fev, "receive_event", no_event)
    r = _post("/api/v1/federation/chat/deliver", {"v": 1, "host_registry": PEER, "conversation": {"id": "r1"}, "message": {"seq": 4}})
    assert r.status_code == 200 and seen == [4]


RELAY = {"conversation_ref": "room-1", "actor_key": f"dev:5@{PEER}", "actor_display": "A", "type": "edit", "message_seq": 2, "body": "n"}


def test_relay_event_answers_the_hosts_result_without_its_private_fan_out_and_tells_the_members(monkeypatch):
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    told = []

    async def apply(db, req, peer):
        assert peer == PEER and req["type"] == "edit" and req["message_seq"] == 2
        conv = type("C", (), {"id": "room-1"})()
        return {"message": {"id": "m2", "body": "n"}, "changed": True, "conversation_id": "room-1",
                "_fan": {"conv": conv, "event": {"type": "edit"}, "actor_key": req["actor_key"], "display": "A", "message": {"id": "m2"}}}

    async def announce(db, conv_id, event, *, message_id=None, actor_display=""):
        told.append((conv_id, event["type"], message_id, actor_display))
    monkeypatch.setattr(fev, "host_apply_relayed", apply)
    monkeypatch.setattr(fev, "announce", announce)
    r = _post("/api/v1/federation/chat/relay-event", RELAY)
    assert r.status_code == 200 and "_fan" not in r.json() and r.json()["changed"] is True
    assert told == [("room-1", "edit", "m2", "A")]


def test_relay_event_gives_the_hosts_refusal_as_its_own_status_and_validates_the_request(monkeypatch):
    monkeypatch.setattr(fed, "federation_enabled", lambda: True)
    async def refuse(db, req, peer):
        raise cs.ChatError(403, "only whoever wrote a message changes it")
    monkeypatch.setattr(fev, "host_apply_relayed", refuse)
    r = _post("/api/v1/federation/chat/relay-event", RELAY)
    assert r.status_code == 403 and "only whoever wrote" in r.json()["detail"]
    assert _post("/api/v1/federation/chat/relay-event", {**RELAY, "type": "room"}).status_code == 422    # a resident may not ask for it
    assert _post("/api/v1/federation/chat/relay-event", {**RELAY, "message_seq": 0}).status_code == 422
