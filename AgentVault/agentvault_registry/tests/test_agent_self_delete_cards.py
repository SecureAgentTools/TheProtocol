"""§MCPTEST30 (V0640): an agent's own delete retires its cards, as its owner's delete does.

DELETE /api/v1/agents/me (the agent's token) revoked the agent and touched its card for the peers, and left the card
active; DELETE /api/v1/developers/me/agents/{did} (the owner's token) deactivates the agent's cards (OWL24). Measured
2026-10-24: every MCP tester throwaway that deleted itself kept an active card (187 on sbx-alpha, 4 on each sandbox
operator), and the operators' two newest were listed active on their parent frame. The test drives the route through
FastAPI's TestClient with a recording session: the agent's active cards are deactivated in the delete's one commit, the
ledger event and the two webhooks still go out, and an agent with no card is deleted as before.
"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql.elements import TextClause

from agentvault_registry import security
from agentvault_registry.background_tasks import reactor_helpers as RH
from agentvault_registry.database import get_db
from agentvault_registry.routers import agents as agents_router

from tests._doubles import StrictEmitter  # noqa: E402

DID = "did:theprotocol:sbx-alpha.theprotocol.cloud:7c0d3a52-1b9e-4f6a-8e2d-4a5b6c7d8e9f"


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    def __init__(self, rows=(), rowcount=0):
        self._rows, self.rowcount = rows, rowcount

    def scalars(self):
        return _Scalars(self._rows)


class FakeDB:
    """Answers the card read with the agent's cards and the ENFPROP touch (raw SQL) with how many it would move."""

    def __init__(self, cards):
        self.cards, self.commits, self.statements = cards, 0, []

    async def execute(self, stmt, *a, **kw):
        self.statements.append(stmt)
        if isinstance(stmt, TextClause):
            return _Result(rowcount=sum(1 for c in self.cards if c.is_active))
        return _Result(rows=[c for c in self.cards if c.is_active])

    async def commit(self):
        self.commits += 1


class _Manager:
    def __init__(self):
        self.sent = []

    async def broadcast(self, message, exclude_user=None, audience=None):   # websocket.ConnectionManager.broadcast
        self.sent.append((message.get("type"), audience))


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
    hooks = []
    manager = _Manager()

    async def _dispatch(event_type, event_data, agent_dids, *, source_label="reactor"):
        hooks.append((event_type, dict(event_data)))
        return 1

    monkeypatch.setattr(agents_router, "event_emitter", emitter)
    monkeypatch.setattr(agents_router, "manager", manager)
    monkeypatch.setattr(RH, "dispatch_webhook_for_agents", _dispatch)

    def _make(cards):
        agent = SimpleNamespace(did=DID, status="active", creator_developer_id=42)
        db = FakeDB(cards)
        app = FastAPI()
        app.include_router(agents_router.router)

        async def fake_agent():
            return agent

        async def fake_db():
            yield db

        app.dependency_overrides[security.get_current_agent] = fake_agent
        app.dependency_overrides[get_db] = fake_db
        return TestClient(app), db, agent

    return _make, emitter, hooks, manager


def test_the_agents_own_delete_retires_its_cards_in_the_one_commit(rig):
    make, emitter, hooks, manager = rig
    cards = [SimpleNamespace(id=1, is_active=True), SimpleNamespace(id=2, is_active=True)]
    client, db, agent = make(cards)
    with client:
        r = client.delete("/api/v1/agents/me")
        assert r.status_code == 204, r.text
        assert _wait_for(lambda: len(hooks) == 2 and emitter.of_type("AgentStatusChanged"))
    assert agent.status == "revoked"
    assert [c.is_active for c in cards] == [False, False], "a revoked agent's card must not stay listed"
    assert db.commits == 1, "the cards go in the same commit as the revocation"
    assert {t for t, _ in hooks} == {"agent.deleted", "agent.status_changed"}
    assert emitter.assert_received("AgentStatusChanged")["data"]["new_status"] == "revoked"
    assert manager.sent == [("agent.deleted", "user_42")]


def test_an_agent_with_no_card_is_deleted_as_before(rig):
    make, emitter, hooks, _ = rig
    client, db, agent = make([])
    with client:
        assert client.delete("/api/v1/agents/me").status_code == 204
        assert _wait_for(lambda: len(hooks) == 2)
    assert agent.status == "revoked" and db.commits == 1
