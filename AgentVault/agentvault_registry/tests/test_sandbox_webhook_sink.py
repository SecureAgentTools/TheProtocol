"""§MCPTEST30 V0637 (agentvault2-aa, 2026-10-24): the sandbox's webhook sink, held to agentvault2-d6's four conditions.

(a) a positive flag, default off, and off the path answers exactly as an unknown route does;
(b) an unknown webhook id and a bad signature get the same refusal, the compare constant-time;
(c) the body is read with a cap before the verify, and nothing about it is logged;
(d) off -> the unknown route's answer, a good signature -> 204, a bad one -> the same answer as an unknown id.

The good delivery is made by WebhookService.deliver_webhook itself: its one send (`_post_to_checked_address`) is handed
to the sink in-process, so the sink is measured against the bytes and headers the delivery code really sends.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
from urllib.parse import urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import DBAPIError
from starlette.routing import NoMatchFound

from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import sandbox_webhook_sink as sink
from agentvault_registry.services.webhook_service import WebhookService

KNOWN = "6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b"
UNKNOWN = "0b1c2d3e-4f50-4617-8293-a4b5c6d7e8f9"
LEGACY = "wh-0123456789abcdef"                      # the legacy route's id shape
SECRET = "whsec-test-0123456789abcdef0123456789abcdef"
SIG = sink.SIGNATURE_HEADER


class _Session:
    """The sink's one read: a webhook's secret by id. Records each id asked for."""

    def __init__(self):
        self.asked = []

    async def execute(self, stmt):
        wid = next(iter(stmt.compile().params.values()))
        self.asked.append(wid)
        if "\x00" in wid:                    # what Postgres does with a NUL in a text value (CharacterNotInRepertoire)
            raise DBAPIError("SELECT developer_webhooks.secret", {}, Exception('invalid byte sequence for encoding "UTF8": 0x00'))
        return SimpleNamespace(scalar_one_or_none=lambda: SECRET if wid in (KNOWN, LEGACY) else None)


def _app(monkeypatch, flag):
    if flag is None:
        monkeypatch.delenv(sink.FLAG, raising=False)
    else:
        monkeypatch.setenv(sink.FLAG, flag)
    app = FastAPI()
    register_error_handlers(app)
    mounted = sink.mount(app)
    session = _Session()

    async def _db():
        yield session
    app.dependency_overrides[get_db] = _db
    return app, mounted, session


def _signed(body: bytes) -> str:
    return WebhookService()._sign_payload(body.decode("utf-8"), SECRET)


def _without_instance(r):
    j = r.json()
    return {k: v for k, v in j.items() if k != "instance"}


# (a) and (d): off is an unknown route

@pytest.mark.parametrize("flag", [None, "", "false", "0", "off", "no", "enabled-ish"])
def test_off_the_path_answers_exactly_as_an_unknown_route(monkeypatch, flag):
    app, mounted, _ = _app(monkeypatch, flag)
    assert mounted is False
    with pytest.raises(NoMatchFound):          # FastAPI keeps an included router whole: ask the app, not app.routes
        app.url_path_for("webhook_sink", webhook_id=KNOWN)
    bare = FastAPI()                       # an app that never saw the module, with the same error handlers
    register_error_handlers(bare)
    body = b'{"id":"x"}'
    path = f"{sink.PATH}/{KNOWN}"
    off = TestClient(app, raise_server_exceptions=False).post(path, content=body, headers={SIG: _signed(body)})
    unknown = TestClient(bare, raise_server_exceptions=False).post(path, content=body, headers={SIG: _signed(body)})
    assert off.status_code == unknown.status_code == 404
    assert off.content == unknown.content
    assert off.headers.get("content-type") == unknown.headers.get("content-type")


@pytest.mark.parametrize("flag", ["true", "1", "yes", "on", " TRUE "])
def test_on_mounts_the_one_route(monkeypatch, flag):
    app, mounted, _ = _app(monkeypatch, flag)
    assert mounted is True
    assert app.url_path_for("webhook_sink", webhook_id=KNOWN) == f"{sink.PATH}/{KNOWN}"


# (d): a delivery made by the delivery code is taken

class _DeliveryDb:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        pass


@pytest.mark.asyncio
async def test_a_delivery_signed_by_the_delivery_code_is_taken(monkeypatch, caplog):
    app, _, session = _app(monkeypatch, "true")
    client = TestClient(app, raise_server_exceptions=False)
    sent = {}

    async def _to_the_sink(self, url, body, headers):        # the delivery's one send, handed to the sink in-process
        sent.update(body=body, headers=headers)
        return client.post(urlsplit(url).path, content=body, headers=headers)
    monkeypatch.setattr(WebhookService, "_post_to_checked_address", _to_the_sink)
    webhook = SimpleNamespace(id=KNOWN, url=f"https://sandbox.example.test{sink.PATH}/{KNOWN}", secret=SECRET,
                              is_active=True, failure_count=0, last_triggered_at=None)
    caplog.set_level(logging.DEBUG)
    delivery = await WebhookService().deliver_webhook(
        webhook=webhook, event_type="test.ping", data={"message": "TheProtocol webhook test"}, agent_did=None,
        db=_DeliveryDb())
    assert delivery.response_status == 204, delivery.error_message
    assert delivery.error_message is None
    assert session.asked == [KNOWN]
    # (c) neither the body nor the signature reaches a log line
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert sent["headers"][SIG] not in logged
    assert sent["body"].decode() not in logged


# (b) and (d): one refusal for everything else

def _refusals(monkeypatch):
    app, _, session = _app(monkeypatch, "true")
    c = TestClient(app, raise_server_exceptions=False)
    body = b'{"event":"test.ping","id":"d1"}'
    return session, {
        "a bad signature": c.post(f"{sink.PATH}/{KNOWN}", content=body, headers={SIG: _signed(b'{"other":1}')}),
        "no signature": c.post(f"{sink.PATH}/{KNOWN}", content=body),
        "an unknown id": c.post(f"{sink.PATH}/{UNKNOWN}", content=body, headers={SIG: _signed(body)}),
        "a malformed id": c.post(f"{sink.PATH}/{'x' * 65}", content=body, headers={SIG: _signed(body)}),
        "a NUL in the id": c.post(f"{sink.PATH}/{KNOWN[:-1]}%00", content=body, headers={SIG: _signed(body)}),
        "an upper-case id": c.post(f"{sink.PATH}/{KNOWN.upper()}", content=body, headers={SIG: _signed(body)}),
        "a body over the cap": c.post(f"{sink.PATH}/{KNOWN}", content=b"x" * (sink.MAX_BODY + 1),
                                      headers={SIG: _signed(b"x" * (sink.MAX_BODY + 1))}),
    }


def test_a_bad_signature_gets_the_same_answer_as_an_unknown_id(monkeypatch):
    session, answers = _refusals(monkeypatch)
    reference = answers["an unknown id"]
    assert reference.status_code == 403
    for what, r in answers.items():
        assert r.status_code == reference.status_code, what
        assert _without_instance(r) == _without_instance(reference), what
        assert r.json()["detail"] == sink.REFUSED, what
    said = " ".join(json.dumps(_without_instance(r)).lower() for r in answers.values())   # `instance` echoes the path
    for telling in ("not found", "unknown", "signature", "secret", KNOWN, "too large"):
        assert telling.lower() not in said
    # the unknown id and the bad signature both asked for a secret; a malformed id and a body over the cap were
    # refused before the query (a NUL would otherwise reach Postgres and answer 500)
    assert sorted(session.asked) == sorted([UNKNOWN, KNOWN, KNOWN])


@pytest.mark.parametrize("wid", [KNOWN, LEGACY])
def test_control_the_same_body_signed_with_the_secret_is_taken(monkeypatch, wid):
    """The refusals above are the verify's, not a sink that refuses everything: the same request, rightly signed, for
    both id shapes the registry mints."""
    app, _, _ = _app(monkeypatch, "true")
    body = b'{"event":"test.ping","id":"d1"}'
    r = TestClient(app, raise_server_exceptions=False).post(f"{sink.PATH}/{wid}", content=body,
                                                            headers={SIG: _signed(body)})
    assert r.status_code == 204 and r.content == b""
