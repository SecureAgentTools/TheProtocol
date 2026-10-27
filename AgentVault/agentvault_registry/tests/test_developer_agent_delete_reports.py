"""§DOCSFIX D6-267 (2026-10-16): a developer's delete of its agent reports itself like the agent's own delete.

DELETE /api/v1/agents/me (the agent's token) writes AgentStatusChanged to the ledger and sends agent.deleted and
agent.status_changed to the owner's webhooks. DELETE /api/v1/developers/me/agents/{did} (the owner's token) revoked the
agent and deactivated its cards and reported nothing: no ledger event, no webhook. The test drives the owner's route
through FastAPI's TestClient with a recording session, a strict emitter and a recording webhook dispatcher; an agent
that is already revoked reports nothing again.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import event_emitter as EE, security
from agentvault_registry.background_tasks import reactor_helpers as RH
from agentvault_registry.database import get_db
from agentvault_registry.routers import developers

from tests._doubles import StrictEmitter  # noqa: E402

DID = "did:theprotocol:eu.theprotocol.cloud:5a1f0c2e-8d4b-4c1e-9f3a-2b7d6e8c9a10"


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, one=None, rows=()):
        self._one, self._rows = one, rows

    def scalar_one_or_none(self):
        return self._one

    def scalars(self):
        return _Scalars(self._rows)


class FakeDB:
    def __init__(self, agent, cards):
        self._answers = [_Result(one=agent), _Result(rows=cards)]
        self.commits = 0

    async def execute(self, stmt, *a, **kw):
        return self._answers.pop(0) if self._answers else _Result()

    async def commit(self):
        self.commits += 1


def _wait_for(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.02)
    return pred()


@pytest.fixture
def rig(monkeypatch):
    emitter = StrictEmitter()
    sent = []

    async def _dispatch(event_type, event_data, *, source_label="reactor", developer_id=None):
        sent.append((event_type, dict(event_data), developer_id))
        return 1

    monkeypatch.setattr(EE, "get_event_emitter", lambda: emitter)
    monkeypatch.setattr(RH, "dispatch_webhook_event", _dispatch)

    def _make(status):
        agent = SimpleNamespace(did=DID, status=status, creator_developer_id=42)
        card = SimpleNamespace(id=9, is_active=True)
        db = FakeDB(agent, [card])
        app = FastAPI()
        app.include_router(developers.router)

        async def fake_dev():
            return SimpleNamespace(id=42, email="owner@test.local", is_admin=False)

        async def fake_db():
            yield db

        app.dependency_overrides[security.get_current_developer] = fake_dev
        app.dependency_overrides[get_db] = fake_db
        return TestClient(app), db, agent, card

    return _make, emitter, sent


def test_the_owners_delete_writes_the_ledger_event_and_both_webhooks(rig):
    make, emitter, sent = rig
    client, db, agent, card = make("active")
    with client:
        r = client.delete(f"/developers/me/agents/{DID}")
        assert r.status_code == 204, r.text
        assert _wait_for(lambda: len(sent) == 2 and emitter.of_type("AgentStatusChanged"))
    assert agent.status == "revoked" and card.is_active is False and db.commits == 1
    ev = emitter.assert_received("AgentStatusChanged")
    assert ev["aggregate_id"] == DID
    assert ev["data"] == {"old_status": "active", "new_status": "revoked", "reason": "developer_deletion"}
    by_type = {t: (d, dev) for t, d, dev in sent}
    assert set(by_type) == {"agent.deleted", "agent.status_changed"}
    assert by_type["agent.deleted"] == ({"agent_did": DID, "mode": "soft", "deleted_by": "developer"}, 42)
    assert by_type["agent.status_changed"] == (
        {"agent_did": DID, "old_status": "active", "new_status": "revoked", "reason": "developer_delete"}, 42)


def test_a_suspended_agent_reports_its_real_old_status(rig):
    make, emitter, sent = rig
    client, _, _, _ = make("suspended")
    with client:
        assert client.delete(f"/developers/me/agents/{DID}").status_code == 204
        assert _wait_for(lambda: len(sent) == 2 and emitter.of_type("AgentStatusChanged"))
    assert emitter.assert_received("AgentStatusChanged")["data"]["old_status"] == "suspended"


def test_an_agent_already_revoked_reports_nothing_again(rig):
    make, emitter, sent = rig
    client, _, _, card = make("revoked")
    with client:
        assert client.delete(f"/developers/me/agents/{DID}").status_code == 204
        time.sleep(0.3)
    assert card.is_active is False
    assert sent == []
    emitter.assert_nothing_received()
