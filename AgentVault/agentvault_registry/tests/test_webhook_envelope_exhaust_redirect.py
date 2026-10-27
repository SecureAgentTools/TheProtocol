"""§DOCSFIX D6-762, D6-764, D6-765 (2026-10-16): three webhook delivery defects.

D6-762: the envelope's top-level `agent_did` read null on every event: no dispatch passed it to the service. The events
about one agent carry it as `data.agent_did`; the envelope now names it, and stays null for an event about no agent.

D6-764: the WebhookRetryExhausted notice (the other webhooks' `webhook.retry_exhausted` and the email) carried the
idempotency key `webhook_exhausted:<webhook id>`, which the event store keeps unique forever: a webhook re-enabled and
disabled again was never announced again. The key now names the attempt that disabled it (delivery and retry count),
still deterministic for that one attempt.

D6-765: a 3xx answer counted as a failed attempt and scheduled a retry, and the retry worker selected only rows with
no status or 400 and above, so the row showed a retry that never ran. The worker now retries every non-2xx answer, as
the service scheduled it.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import types

import pytest

from sqlalchemy.dialects import postgresql

ws = importlib.import_module("agentvault_registry.services.webhook_service")
worker = importlib.import_module("agentvault_registry.background_tasks.webhook_retry_worker")
EE = importlib.import_module("agentvault_registry.event_emitter")


@pytest.fixture(autouse=True)
def _receiver_resolves(monkeypatch):
    """SEC-14: the delivery connects to an address its own lookup checked; the receiver's name answers a public one."""
    from tests._doubles import resolve_names_publicly
    resolve_names_publicly(monkeypatch)


AGENT = "did:theprotocol:asia.theprotocol.cloud:2a3b4c5d-0000-4000-8000-000000000007"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Resp:
    def __init__(self, code):
        self.status_code = code
        self.text = "ok" if code < 300 else "nope"


class _Client:
    def __init__(self, code=200):
        self.code = code
        self.received = []

    async def post(self, url, **kw):
        self.received.append(json.loads(kw["content"]))
        return _Resp(self.code)


def _hook(**kw):
    d = dict(id="wh1", url="http://receiver.invalid/hook", secret="ab" * 32, failure_count=0, is_active=True,
             last_triggered_at=None, developer_id=7, events=["payment.received"])
    d.update(kw)
    return types.SimpleNamespace(**d)


class _Db:
    def __init__(self, hooks=()):
        self.hooks = list(hooks)

    async def execute(self, stmt):
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: self.hooks))

    def add(self, obj):
        pass

    async def commit(self):
        pass


def _emit(data):
    svc = ws.WebhookService()
    svc.client = _Client(200)
    count = _run(svc.emit_event("payment.received", data, _Db([_hook()]), developer_id=7))
    assert count == 1
    return svc.client.received[0]


def test_the_envelope_names_the_agent_the_event_is_about():
    env = _emit({"agent_did": AGENT, "amount": "2.5", "currency": "ACU"})
    assert env["agent_did"] == AGENT and env["data"]["agent_did"] == AGENT


def test_an_event_about_no_agent_keeps_it_null():
    env = _emit({"amount": "2.5"})
    assert env["agent_did"] is None


class _Recorder:
    def __init__(self):
        self.received = []

    def emit_background(self, event_type, aggregate_id, data, aggregate_type="Agent", metadata=None,
                        idempotency_key=None, max_retries=3):
        self.received.append({"event_type": event_type, "idempotency_key": idempotency_key, "data": data})


def _disable_once(monkeypatch, rec):
    """One delivery that tips a webhook at 9 consecutive failures over the limit of 10."""
    monkeypatch.setattr(EE, "get_event_emitter", lambda: rec)
    svc = ws.WebhookService()
    svc.client = _Client(500)
    hook = _hook(failure_count=ws.WebhookService.MAX_CONSECUTIVE_FAILURES - 1)
    d = _run(svc.deliver_webhook(hook, "payment.received", {"agent_did": AGENT}, AGENT, _Db()))
    assert hook.is_active is False
    return d


def test_every_disable_episode_is_announced(monkeypatch):
    rec = _Recorder()
    first = _disable_once(monkeypatch, rec)
    second = _disable_once(monkeypatch, rec)      # the webhook was re-enabled, failed ten times again
    keys = [r["idempotency_key"] for r in rec.received if r["event_type"] == "WebhookRetryExhausted"]
    assert len(keys) == 2 and keys[0] != keys[1], keys
    assert keys[0].startswith("webhook_exhausted:wh1:") and first.id in keys[0] and second.id in keys[1]


def _worker_sql(monkeypatch):
    seen = []

    class _S:
        async def execute(self, stmt):
            seen.append(str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})))
            return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: []))

    class _CM:
        async def __aenter__(self):
            return _S()

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: _CM())
    assert _run(worker._retry_pending()) == (0, 0)
    return seen[0]


def test_the_worker_retries_a_redirect_like_any_failed_attempt(monkeypatch):
    sql = _worker_sql(monkeypatch)
    assert "webhook_deliveries.response_status >= 300" in sql, sql
    assert "webhook_deliveries.response_status IS NULL" in sql, sql


def test_control_a_redirect_answer_is_a_failed_attempt_with_a_retry_slot():
    svc = ws.WebhookService()
    svc.client = _Client(302)
    hook = _hook()
    d = _run(svc.deliver_webhook(hook, "payment.received", {"agent_did": AGENT}, AGENT, _Db()))
    assert d.response_status == 302 and d.next_retry_at is not None and hook.failure_count == 1
