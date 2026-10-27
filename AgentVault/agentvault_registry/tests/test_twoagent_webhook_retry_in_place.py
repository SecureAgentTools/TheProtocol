"""§TWOAGENT #33 (2026-09-23) — a failed webhook delivery is retried IN PLACE, so a recovered endpoint gets it ONCE.

Measured on sbx-alpha (V0428): a webhook.test answered 404 at 11:06:42Z, the url was healed, and the same event then
arrived at 11:08:12, 11:09:12 and 11:10:12, each answered 200, each under a NEW delivery id, none carrying
X-TheProtocol-Retry, until the webhook was deactivated. The live worker re-sent through deliver_webhook (a fresh row
every cycle) and never touched the original, which stayed eligible (retry_count 0, next_retry_at past, status 404)
forever. The method the docs describe (same id, retry header) had no caller.

Pinned through the real deliver_webhook / retry_delivery / _retry_pending / redeliver_delivery with doubles that
record what would go on the wire. RED on the pre-change tree: every test except the two controls at the end.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import importlib
import json
import types
from datetime import datetime, timedelta, timezone

import pytest

ws = importlib.import_module("agentvault_registry.services.webhook_service")
worker = importlib.import_module("agentvault_registry.background_tasks.webhook_retry_worker")
from agentvault_registry import models  # noqa: E402


@pytest.fixture(autouse=True)
def _receiver_resolves(monkeypatch):
    """SEC-14: the delivery connects to an address its own lookup checked; the receiver's name answers a public one."""
    from tests._doubles import resolve_names_publicly
    resolve_names_publicly(monkeypatch)


SECRET = "ab" * 32
AGENT = "did:theprotocol:eu.theprotocol.cloud:0f1e2d3c-0000-4000-8000-000000000001"
# a data dict carrying its OWN "data" key: the redeliver rail used to unwrap it one level too far
DATA = {"message": "hi", "data": {"nested": 1}}


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.text = "ok" if code < 300 else "nope"


class _Client:
    def __init__(self, code=200):
        self.code = code
        self.received = []

    async def post(self, url, **kw):
        self.received.append({"url": url, **kw})
        return _Resp(self.code)


class _Db:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _hook(**kw):
    d = dict(id="wh1", url="http://receiver.invalid/hook", secret=SECRET, failure_count=0, is_active=True,
             last_triggered_at=None, developer_id=7)
    d.update(kw)
    return types.SimpleNamespace(**d)


def _first(code=404):
    """The REAL first delivery, so the stored row is exactly what production writes."""
    svc = ws.WebhookService()
    svc.client = _Client(code)
    hook = _hook()
    d = _run(svc.deliver_webhook(hook, "webhook.test", DATA, AGENT, _Db()))
    return d, hook, json.loads(svc.client.received[0]["content"])


def _retry(d, hook, code):
    svc = ws.WebhookService()
    svc.client = _Client(code)
    _run(svc.retry_delivery(d, hook, _Db()))
    return svc.client.received[0]


def test_the_row_stores_the_envelope_as_sent():
    d, _, sent = _first()
    assert d.payload == sent, "the row must hold the envelope that went on the wire, not only its data"


def test_a_retry_resends_the_same_delivery():
    d, hook, first = _first(404)
    assert d.next_retry_at is not None and d.retry_count == 0
    got = _retry(d, hook, 200)
    h = got["headers"]
    body = json.loads(got["content"])
    assert h["X-TheProtocol-Delivery-ID"] == d.id and body["id"] == d.id, "a retry is the SAME delivery"
    assert h["X-TheProtocol-Retry"] == "1" and body["retry_count"] == 1
    assert body["event"] == "webhook.test" and body["data"] == DATA and body["agent_did"] == AGENT
    assert body["original_timestamp"] == first["timestamp"]
    assert hmac.compare_digest(hmac.new(SECRET.encode(), got["content"], hashlib.sha256).hexdigest(),
                               h["X-TheProtocol-Signature"]), "the raw body is still what was signed"
    # the ORIGINAL row carries the outcome and leaves the worker's selection (next_retry_at IS NOT NULL)
    assert d.retry_count == 1 and d.response_status == 200 and d.next_retry_at is None
    assert hook.failure_count == 0


def test_a_failed_retry_schedules_the_next_slot():
    d, hook, _ = _first(404)
    before = datetime.now(timezone.utc)
    _retry(d, hook, 500)
    assert d.retry_count == 1 and d.response_status == 500
    delay = ws.WebhookService.RETRY_DELAYS[1]
    assert before + delay - timedelta(seconds=5) <= d.next_retry_at <= datetime.now(timezone.utc) + delay
    assert hook.failure_count == 2  # the first delivery's failure + this one


def test_the_last_retry_schedules_nothing():
    d, hook, _ = _first(404)
    d.retry_count = ws.WebhookService.MAX_RETRIES - 1
    _retry(d, hook, 500)
    assert d.retry_count == ws.WebhookService.MAX_RETRIES and d.next_retry_at is None


def test_a_pre_v0429_row_is_rebuilt_around_its_data():
    at = datetime(2026, 9, 23, 11, 6, 42, tzinfo=timezone.utc)
    old = models.WebhookDelivery(id="d-old", webhook_id="wh1", event_type="agent.suspended",
                                 payload={"reason": "x", "data": {"k": 1}}, delivered_at=at, retry_count=0)
    env = ws.WebhookService.stored_envelope(old)
    assert env == {"id": "d-old", "event": "agent.suspended", "data": {"reason": "x", "data": {"k": 1}},
                   "timestamp": at.isoformat(), "agent_did": None}


# ── the worker: one retry per due row, in place; nothing minted ──────────────────────────────────────────────────

class _Result:
    def __init__(self, rows):
        self.rows = rows

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None


class _Session:
    def __init__(self, results):
        self.results = list(results)

    async def execute(self, stmt):
        return self.results.pop(0)

    async def commit(self):
        return None

    def add(self, obj):
        return None


class _CM:
    def __init__(self, sess):
        self.sess = sess

    async def __aenter__(self):
        return self.sess

    async def __aexit__(self, *a):
        return False


def test_the_worker_retries_in_place_and_mints_nothing(monkeypatch):
    d, hook, _ = _first(404)
    calls = {"retry": [], "deliver": []}

    async def _retry_rec(self, delivery, webhook, db):
        calls["retry"].append((delivery, webhook))
        return delivery

    async def _deliver_rec(self, *a, **k):
        calls["deliver"].append((a, k))
        return types.SimpleNamespace(id="fresh", response_status=200)
    monkeypatch.setattr(ws.WebhookService, "retry_delivery", _retry_rec, raising=False)
    monkeypatch.setattr(ws.WebhookService, "deliver_webhook", _deliver_rec)
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _CM(_Session([_Result([d]), _Result([hook])])))
    retried, failed = _run(worker._retry_pending())
    assert calls["deliver"] == [], "the worker must not mint a fresh delivery for a retry"
    assert [c[0] for c in calls["retry"]] == [d] and (retried, failed) == (1, 0)


# ── the manual redeliver rail: a NEW delivery by design, but the same event, data and agent_did ─────────────────

def _redeliver(monkeypatch, original):
    wh = importlib.import_module("agentvault_registry.routers.webhooks")
    got = {}

    async def _owned(webhook_id, dev_id, db):
        return _hook()

    async def _deliver_rec(self, webhook, event_type, data, agent_did, db):
        got.update(event_type=event_type, data=data, agent_did=agent_did)
        return types.SimpleNamespace(id="fresh", response_status=200)
    monkeypatch.setattr(wh, "_get_owned_webhook", _owned)
    monkeypatch.setattr(ws.WebhookService, "deliver_webhook", _deliver_rec)
    _run(wh.redeliver_delivery("wh1", original.id, developer=types.SimpleNamespace(id=7), db=_Session([_Result([original])])))
    return got


def test_a_redelivery_keeps_the_event_data_and_agent_did(monkeypatch):
    d, _, _ = _first(200)
    got = _redeliver(monkeypatch, d)
    assert got == {"event_type": "webhook.test", "data": DATA, "agent_did": AGENT}


def test_a_redelivery_of_a_pre_v0429_row_does_not_unwrap_its_data(monkeypatch):
    old = models.WebhookDelivery(id="d-old", webhook_id="wh1", event_type="agent.suspended",
                                 payload={"reason": "x", "data": {"k": 1}}, retry_count=0)
    got = _redeliver(monkeypatch, old)
    assert got["data"] == {"reason": "x", "data": {"k": 1}} and got["event_type"] == "agent.suspended"


# ── controls: green before and after ─────────────────────────────────────────────────────────────────────────────

def test_control_a_first_delivery_that_fails_is_scheduled_one_minute_out():
    before = datetime.now(timezone.utc)
    d, hook, _ = _first(404)
    delay = ws.WebhookService.RETRY_DELAYS[0]
    assert d.response_status == 404 and before + delay - timedelta(seconds=5) <= d.next_retry_at
    assert hook.failure_count == 1


def test_control_the_worker_still_returns_a_pair_when_nothing_is_due(monkeypatch):
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _CM(_Session([_Result([])])))
    assert _run(worker._retry_pending()) == (0, 0)
