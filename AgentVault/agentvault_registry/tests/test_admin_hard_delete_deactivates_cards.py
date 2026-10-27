"""§MCPTEST30 V0637 (agentvault2-aa, 2026-10-24): an administrator's hard delete of an agent deactivates its cards.

The MCP tester's earn_agent_admin lifecycle hard-deletes a second agent of its own (deleteAdminAgent), and its card
stayed active and listed, naming an agent that no longer exists: seven such cards on sbx-alpha, two per run on each
sandbox operator (agentvault2-66's read-only count, 2026-10-24). The owner's own delete deactivates every active card
of the agent (developers.py, OWL24); the hard delete deleted the row and left the cards. It now deactivates them in
the same transaction, before the row goes, and never deletes them (the federation feed carries an inactive card to
every mirror, where a deleted one would stay a ghost there).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentvault_registry import schemas
from agentvault_registry.background_tasks import reactor_helpers
from agentvault_registry.routers import admin_agents

DID = "did:theprotocol:6f1c2a9e-3b4d-4e5f-8a7b-9c0d1e2f3a4b"


class _Db:
    """The hard delete's reads: the agent, its active stakes, its open disputes, and its active cards."""

    def __init__(self):
        self.agent = SimpleNamespace(did=DID, liquid_balance=0, staked_balance=0, creator_developer_id=3,
                                     created_at=None)
        self.cards = [SimpleNamespace(id=1, is_active=True), SimpleNamespace(id=2, is_active=True)]
        self.deleted, self.commits, self.card_queries = [], 0, []

    async def execute(self, stmt):
        sql = str(stmt)
        params = list(stmt.compile().params.values())
        if "count(" in sql:
            return SimpleNamespace(scalar=lambda: 0)
        if "FROM agent_cards" in sql:
            self.card_queries.append(params)
            mine = DID in params
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: list(self.cards) if mine else []))
        return SimpleNamespace(scalar_one_or_none=lambda: self.agent if DID in params else None)

    async def delete(self, obj):
        self.deleted.append(obj)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_a_hard_delete_deactivates_the_agents_cards_in_its_transaction(monkeypatch):
    async def _quiet(*_a, **_k):
        return None
    monkeypatch.setattr(admin_agents, "_emit_admin_action", _quiet)
    monkeypatch.setattr(reactor_helpers, "dispatch_webhook_event", _quiet)
    db = _Db()
    answer = await admin_agents.hard_delete_agent(
        DID, schemas.AgentHardDeleteRequest(reason="MCP tester: its own agent, removed", confirm_did=DID),
        db=db, admin=SimpleNamespace(id=1))
    assert [c.is_active for c in db.cards] == [False, False]
    assert db.deleted == [db.agent] and db.commits == 1
    assert len(db.card_queries) == 1 and DID in db.card_queries[0]     # the agent's own cards, active ones
    assert "2 card(s) deactivated" in answer.message
