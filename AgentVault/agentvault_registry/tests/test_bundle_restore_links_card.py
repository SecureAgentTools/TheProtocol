"""§MCPTEST30 (V0638): a restored agent's card is linked to the agent (agent_cards.agent_did).

The restore inserted the card with the agent's DID only inside its JSON (card_data.did and humanReadableId), so every
reader that joins on agent_cards.agent_did (discovery, the card rails, an agent's deletion) saw an agent with no card
and a card with no agent, and deleting the agent left its card active: the class the import fixed on 2026-10-01
(export_import_service._import_agent_card). Pinned: the card insert carries the new agent's DID, the same one the agent
insert carries (it fails on the service before V0638).
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.services.bundles import service as S

SOURCE = "did:theprotocol:sandbox-a.theprotocol.cloud:6d1f6f3e-1c39-4b8e-9a63-5d1b2c7e8f90"
INSTALLER = 8


class _R:
    def first(self):
        return None

    def scalar(self):
        return None

    def scalars(self):
        return self

    def all(self):
        return []

    def mappings(self):
        return self

    @property
    def rowcount(self):
        return 1


class RecordingDB:
    def __init__(self):
        self.agents, self.cards = [], []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO agents" in sql:
            self.agents.append(dict(params or {}))
        elif "INSERT INTO agent_cards" in sql:
            self.cards.append((sql, dict(params or {})))
        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def one_payload(monkeypatch):
    payload = {"did": SOURCE, "name": "API Test Agent Primary", "agent_card": {}}
    monkeypatch.setattr(S.fmt, "unpack_bundle", lambda data: ({"exporter": {}}, [payload], None, []))


async def _no_clash(db, did):
    return False


def test_the_restored_card_names_its_agent(one_payload, monkeypatch):
    from agentvault_registry.routers import onboarding
    monkeypatch.setattr(onboarding, "did_is_taken", _no_clash)
    db = RecordingDB()
    try:
        asyncio.run(S.restore_bundle(db=db, installer_dev_id=INSTALLER, uploaded_bytes=b"tpb",
                                     conflict_resolution="rename"))
    except Exception:  # noqa: BLE001 — past the inserts the fake has no rows; what was inserted is the question
        pass
    assert len(db.agents) == 1 and len(db.cards) == 1
    sql, params = db.cards[0]
    assert "agent_did" in sql.split("VALUES")[0]
    assert params.get("did") == db.agents[0]["did"]

