"""§SECBATCH wave 2 (2026-10-16): the registry's public ledger feed withholds personal ids, as its public reads do since
D6-606 (wave 1).

After every event it emits, the registry broadcasts the event on `system.events`, the topic its public /ws/events
subscribes every visitor to (no credential) and that anyone may subscribe to on the main socket. It sent the event as
emitted: a developer's TEG account id is built from the developer's e-mail address (identifiers.developer_teg_did), and
an event can carry a plain address, so every transfer that touched a developer's account named that developer's address
to anyone watching. What this pins, through FastAPI on the real /ws/events route and the emitter's own broadcast:
- a visitor's feed shows the account by its opaque public id and withholds the address; an agent DID is untouched;
- the event handed to the broadcast (what the ledger stores) is not changed by it.
"""
from __future__ import annotations

import asyncio
import copy
import json
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.event_emitter import EventEmitter
from agentvault_registry.routers import websocket as WS

WALLET = "did:theprotocol:alice.smith_at_example.com"
AGENT = "did:theprotocol:6f1c2a8e-0b1d-4c3e-9f00-sec2agent"


def test_a_visitor_on_the_public_feed_gets_no_address(monkeypatch):
    # The manager's Redis fan-out is network: without it the manager delivers locally. (Its Redis bootstrap, reached
    # with no Redis at all, takes its non-reentrant _pubsub_lock twice and never returns, so it is stubbed here.)
    async def _no_redis(*_args, **_kwargs):
        return None

    monkeypatch.setattr(WS.manager, "_ensure_pubsub", _no_redis)
    monkeypatch.setattr(WS.manager, "_ensure_topic_subscribed", _no_redis)
    monkeypatch.setattr(WS.manager, "_get_redis", _no_redis)
    payload = {"event_type": "TokensTransferred", "aggregate_id": WALLET, "aggregate_type": "Agent",
               "data": {"from": WALLET, "to": AGENT, "amount": "5", "note": "for bob@example.org"},
               "source_service": "registry"}
    sent = copy.deepcopy(payload)
    app = FastAPI()
    app.include_router(WS.router)
    with TestClient(app) as client, client.websocket_connect("/ws/events") as ws:
        while ws.receive_json().get("type") != "subscribed":   # the manager greets first ("connected")
            pass
        client.portal.call(EventEmitter()._broadcast_to_ws, payload, {"id": "evt-1"})
        client.portal.call(asyncio.sleep, 0.1)
        ws.send_json({"type": "ping", "data": {"timestamp": 1}})
        got = []
        while True:
            msg = ws.receive_json()
            if msg.get("type") == "pong":
                break
            got.append(msg)
    events = [m["data"] for m in got if m.get("type") == "event"]
    assert len(events) == 1, got
    text = json.dumps(events)
    assert "alice" not in text and "_at_" not in text and "@" not in text, text
    event = events[0]
    assert re.fullmatch(r"account:[0-9a-f]{16}", event["aggregate_id"]), event
    assert event["data"]["from"] == event["aggregate_id"] and event["data"]["to"] == AGENT
    assert payload == sent, "the broadcast changed the event it was handed"
