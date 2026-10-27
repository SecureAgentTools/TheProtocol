"""§TWOAGENT #4 (2026-09-23) — a webhook delivery's body IS the bytes its signature covers.

Measured on EU and ASIA with two independent receivers: every delivery verified by the documented recipe
(HMAC-SHA256 hex over json.dumps(payload, sort_keys=True)) and NONE verified over the raw body, because the sender
signed the sorted serialisation and then let httpx POST `json=payload` (insertion order). The industry recipe — HMAC
over the raw bytes received — therefore failed on every delivery, and a receiver in any language but Python had to
re-implement Python's json.dumps byte for byte to verify at all.

Now the sender signs one string and sends exactly that string, so BOTH recipes verify: the raw-body HMAC, and the
documented one (re-serialising sorted JSON of these bytes yields these bytes). Pinned through the real
`deliver_webhook`, with a client double that records what would go on the wire.

RED on the pre-change tree: all three (no `content` bytes were sent: httpx serialised `json=payload` itself).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import types

import pytest


import importlib

# the services package re-exports the module-level INSTANCE under the module's own name, so import the module
ws = importlib.import_module("agentvault_registry.services.webhook_service")


@pytest.fixture(autouse=True)
def _receiver_resolves(monkeypatch):
    """SEC-14: the delivery connects to an address its own lookup checked; the receiver's name answers a public one."""
    from tests._doubles import resolve_names_publicly
    resolve_names_publicly(monkeypatch)

SECRET = "0f" * 32


class _Resp:
    status_code = 200
    text = "ok"


class _Client:
    def __init__(self):
        self.received = []

    async def post(self, url, **kw):
        self.received.append(kw)
        return _Resp()


class _Db:
    def add(self, obj):
        self.obj = obj

    async def commit(self):
        return None


def _deliver(data):
    svc = ws.WebhookService()
    svc.client = _Client()
    hook = types.SimpleNamespace(id="wh1", url="http://receiver.invalid/hook", secret=SECRET, failure_count=0,
                                 is_active=True, last_triggered_at=None)
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(svc.deliver_webhook(hook, "chat.message.received", data, None, _Db()))
    finally:
        loop.close()
    assert len(svc.client.received) == 1
    return svc.client.received[0]


# a payload whose insertion order differs from sorted order, with a non-ASCII character (a real chat body)
DATA = {"conversation_id": "c1", "kind": "dm",
        "message": {"id": "m1", "body": "Grüße aus Brüssel", "sender_id": "did:x", "seq": 1}}


def test_the_raw_body_verifies():
    kw = _deliver(DATA)
    body = kw.get("content")
    assert isinstance(body, (bytes, bytearray)), "the body must be the exact signed bytes"
    sig = kw["headers"]["X-TheProtocol-Signature"]
    assert hmac.compare_digest(hmac.new(SECRET.encode(), bytes(body), hashlib.sha256).hexdigest(), sig)


def test_the_documented_recipe_still_verifies():
    kw = _deliver(DATA)
    parsed = json.loads(kw["content"])
    sig = kw["headers"]["X-TheProtocol-Signature"]
    assert hmac.compare_digest(hmac.new(SECRET.encode(), json.dumps(parsed, sort_keys=True).encode(), hashlib.sha256).hexdigest(), sig)
    assert parsed["data"] == DATA and parsed["event"] == "chat.message.received"


def test_the_sender_no_longer_lets_httpx_serialise():
    kw = _deliver(DATA)
    assert "json" not in kw and kw["headers"]["Content-Type"] == "application/json"
