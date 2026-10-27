"""§MCPTEST30 (2026-10-01) — an imported or cloned agent's card is ITS card: linked, named, and never another agent's.

Found while tracing why every MCP tester run on sbx-alpha left agents with no card: the import made the card with the DID
only inside its JSON and agent_cards.agent_did NULL, so every reader that joins on agent_did (discovery, the card rails,
an agent's deletion) saw a cardless agent, and deleting the agent left its card active (sandbox: 296 such cards, 85 for
revoked agents; EU and ASIA: none, nobody imported there). Beside it: the export looked a card up by its JSON DID among
the developer's cards and, finding none, returned the developer's FIRST card (another agent's), and a clone's card kept
the source's name. Each test fails against the code before the fix (its control).
"""
from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

import importlib  # noqa: E402

# the package re-exports the service INSTANCE under the module's name, so import the module itself
EIS = importlib.import_module("agentvault_registry.services.export_import_service")

NEW = "did:theprotocol:new-agent"
OTHER = "did:theprotocol:other-agent"


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Rows:
    def __init__(self, rows):
        self.rows = rows

    def scalar_one_or_none(self):
        return self.rows[0] if self.rows else None

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self.rows), first=lambda: self.rows[0] if self.rows else None)


class _DB:
    """Answers the three questions the card code asks, read from the compiled statement: the card LINKED to a DID
    (agent_cards.agent_did = ...), the developer's cards (agent_cards.developer_id = ...), and the agent row."""

    def __init__(self, linked=None, developer_cards=(), agent=None):
        self.linked, self.developer_cards, self.agent, self.added = linked, list(developer_cards), agent, []

    def add(self, obj):
        self.added.append(obj)

    async def execute(self, stmt):
        sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "FROM agent_cards" in sql and "agent_cards.agent_did = " in sql:
            return _Rows([self.linked] if self.linked is not None else [])
        if "FROM agent_cards" in sql and "agent_cards.developer_id = " in sql:
            return _Rows(self.developer_cards)
        if "FROM agents" in sql:
            return _Rows([self.agent] if self.agent is not None else [])
        raise AssertionError(f"unexpected statement: {sql[:120]}")


def test_an_imported_card_is_linked_to_its_agent():
    db = _DB()
    _run(EIS.ExportImportService()._import_agent_card(NEW, {"name": "Imported", "description": "d"}, 7, db))
    assert len(db.added) == 1, db.added
    card = db.added[0]
    assert card.agent_did == NEW, "the card names its agent in agent_did, the column every reader joins on"
    assert card.card_data["did"] == NEW and card.name == "Imported" and card.developer_id == 7 and card.is_active


def test_an_overwrite_updates_the_card_that_survived_the_agent():
    """An overwrite hard-deletes the old agent and not its card (no foreign key), and agent_did is unique: a second
    linked card for the same DID would be refused by the index."""
    survivor = SimpleNamespace(agent_did=NEW, card_data={"did": NEW, "name": "Old"}, name="Old", description="",
                               developer_id=7, is_active=False, updated_at=None)
    db = _DB(linked=survivor)
    _run(EIS.ExportImportService()._import_agent_card(NEW, {"name": "New", "description": "fresh"}, 7, db))
    assert db.added == [], "no second card for one agent"
    assert survivor.name == "New" and survivor.card_data["name"] == "New" and survivor.is_active is True


def test_an_export_never_carries_another_agents_card():
    agent = SimpleNamespace(did=NEW, creator_developer_id=7)
    strangers = [SimpleNamespace(agent_did=None, card_data={"did": OTHER, "name": "Someone else"})]
    got = _run(EIS.ExportImportService()._get_agent_card(NEW, _DB(developer_cards=strangers, agent=agent)))
    assert got is None, "no card is better than a stranger's: the import makes one from the agent's own name"


def test_an_export_finds_the_linked_card_and_an_old_unlinked_import():
    agent = SimpleNamespace(did=NEW, creator_developer_id=7)
    linked = SimpleNamespace(agent_did=NEW, card_data={"did": NEW, "name": "Mine"})
    assert _run(EIS.ExportImportService()._get_agent_card(NEW, _DB(linked=linked, agent=agent))) is linked
    old_import = SimpleNamespace(agent_did=None, card_data={"did": NEW, "name": "Mine, before the link"})
    found = _run(EIS.ExportImportService()._get_agent_card(
        NEW, _DB(developer_cards=[SimpleNamespace(agent_did=None, card_data={"did": OTHER}), old_import], agent=agent)))
    assert found is old_import


def test_a_clone_card_carries_the_clone_name():
    svc = EIS.ExportImportService()
    seen = {}

    async def export_agent(**kw):
        return {"agent": {"did": "did:theprotocol:source", "name": "Source"},
                "agent_card": {"name": "Source", "description": "d"}, "metadata": {"original_did": "did:theprotocol:source"}}

    async def import_agent(import_data, developer_id, db, conflict_resolution, dry_run):
        seen.update(import_data)
        return None, {"success": False, "errors": ["stopped by the test"], "warnings": []}

    svc.export_agent = export_agent
    svc.import_agent = import_agent
    _run(svc.clone_agent("did:theprotocol:source", 7, db=None, new_name="phase5-clone-1"))
    assert seen["agent"]["name"] == "phase5-clone-1"
    assert seen["agent_card"]["name"] == "phase5-clone-1", "the clone's card says what the clone is called"
