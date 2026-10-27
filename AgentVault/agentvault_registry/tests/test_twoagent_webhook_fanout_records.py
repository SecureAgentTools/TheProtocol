"""§TWOAGENT (2026-09-23): an event with two subscribers records BOTH deliveries.

`WebhookService.emit_event` delivers to every subscribed webhook concurrently and every task wrote its delivery row
into the ONE session it was given. An AsyncSession cannot run two operations at once, so two subscribers meant two
overlapping add+commit sequences; `gather(return_exceptions=True)` swallowed the refusal. Measured on the V0437
sandbox: one developer with two hooks on one event, both POSTs sent, NEITHER delivery recorded (the control with one
hook recorded 1), no error logged. A lost row is a lost retry too: `next_retry_at` lives on it.

The session here refuses an operation while another is in flight, as asyncpg does ("another operation is in
progress"), and the HTTP client yields, so two deliveries interleave the way they do live.

RED on 493ec628 (the pre-fix service): 2 of 3.
"""
from __future__ import annotations

import asyncio
import types

import pytest


@pytest.fixture(autouse=True)
def _receiver_resolves(monkeypatch):
    """SEC-14: the delivery connects to an address its own lookup checked; the receiver's name answers a public one."""
    from tests._doubles import resolve_names_publicly
    resolve_names_publicly(monkeypatch)


class _Session:
    """Refuses overlapping operations, like one asyncpg connection behind an AsyncSession."""

    def __init__(self, webhooks):
        self._webhooks = webhooks
        self._busy = False
        self.pending: list = []
        self.recorded: list = []

    async def execute(self, _stmt):
        rows = self._webhooks
        return types.SimpleNamespace(scalars=lambda: types.SimpleNamespace(all=lambda: list(rows)))

    def add(self, obj):
        if self._busy:
            raise RuntimeError("Session.add() during another operation's flush")
        self.pending.append(obj)

    async def commit(self):
        if self._busy:
            raise RuntimeError("another operation is in progress")
        self._busy = True
        try:
            await asyncio.sleep(0.01)      # a real flush yields to the loop
            self.recorded.extend(self.pending)
            self.pending.clear()
        finally:
            self._busy = False


class _Client:
    def __init__(self, status: int = 200):
        self.status = status
        self.urls: list = []

    async def post(self, url, content=None, headers=None, **kw):
        self.urls.append(url)
        await asyncio.sleep(0)             # let the other delivery run
        return types.SimpleNamespace(status_code=self.status, text="")


def _hooks(n: int):
    from agentvault_registry.models import DeveloperWebhook
    return [DeveloperWebhook(id=f"hook-{i}", developer_id=7, url=f"https://receiver-{i}.example/hook",
                             events=["chat.message.received"], secret="s" * 32, is_active=True, failure_count=0)
            for i in range(n)]


def _svc(client: _Client):
    from agentvault_registry.services.webhook_service import WebhookService
    svc = WebhookService()
    svc.client = client
    return svc


async def test_two_subscribers_record_two_deliveries():
    hooks = _hooks(2)
    db, client = _Session(hooks), _Client()
    n = await _svc(client).emit_event("chat.message.received", {"conversation_id": "c1"}, db, developer_id=7)
    assert n == 2 and len(client.urls) == 2
    assert sorted(d.webhook_id for d in db.recorded) == ["hook-0", "hook-1"]


async def test_a_failed_delivery_to_one_of_several_keeps_its_retry():
    hooks = _hooks(3)
    db, client = _Session(hooks), _Client(status=503)
    await _svc(client).emit_event("chat.message.received", {"conversation_id": "c1"}, db, developer_id=7)
    assert len(db.recorded) == 3
    assert all(d.next_retry_at is not None and d.response_status == 503 for d in db.recorded)
    assert all(h.failure_count == 1 for h in hooks)


async def test_a_single_delivery_needs_no_lock():
    """The direct callers (test, redeliver, admin) deliver one webhook with no lock, unchanged."""
    hooks = _hooks(1)
    db, client = _Session(hooks), _Client()
    d = await _svc(client).deliver_webhook(hooks[0], "chat.message.received", {"conversation_id": "c1"}, None, db)
    assert db.recorded == [d] and d.response_status == 200
