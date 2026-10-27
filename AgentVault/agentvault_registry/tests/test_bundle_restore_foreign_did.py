"""§MCPTEST30 (2026-10-01) — a bundle never installs an agent under a DID a mirrored foreign agent holds here.

Copy and mirror installs keep the bundle's own DID, and the clash check asked only the `agents` table. A mirror of a
FOREIGN agent holds its DID in agent_cards.agent_did with no agents row, so an uploaded bundle naming that DID made a
LOCAL agent under it, owned by the installer, with fresh working credentials. The mint's own net (did_is_taken) is
asked now: such a DID is renamed in a copy when the caller asked for rename, and skipped otherwise.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.services.bundles import service as S

FOREIGN = "did:theprotocol:peer.example:3f6c1a52-0d1e-4c8e-9b7a-2f4d5e6a7b8c"
INSTALLER = 8


class _R:
    def __init__(self, row=None):
        self._row = row

    def first(self):
        return self._row

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


class MirrorDB:
    """This registry mirrors FOREIGN (an agent_cards row) and has no agents row for it."""

    def __init__(self):
        self.inserted_agents = []

    async def execute(self, stmt, params=None):
        sql = str(stmt)
        if "INSERT INTO agents" in sql:
            self.inserted_agents.append((params or {}).get("did"))
            return _R()
        if "FROM agent_cards" in sql and "agent_cards.agent_did" in sql:
            bound = stmt.compile().params
            return _R(("card-1",) if FOREIGN in bound.values() else None)
        return _R()

    async def commit(self):
        return None

    async def rollback(self):
        return None


@pytest.fixture
def one_foreign_payload(monkeypatch):
    payload = {"did": FOREIGN, "name": "Somebody Else", "agent_card": {"description": "theirs"}}
    monkeypatch.setattr(S.fmt, "unpack_bundle", lambda data: ({"exporter": {}}, [payload], None, []))


def _restore(db, **kw):
    try:
        return asyncio.run(S.restore_bundle(db=db, installer_dev_id=INSTALLER, uploaded_bytes=b"tpb", **kw))
    except Exception as e:  # noqa: BLE001 — past the INSERT the fake has no rows; what was inserted is the question
        return {"raised": type(e).__name__}


@pytest.mark.parametrize("kw", [dict(conflict_resolution="skip"), dict(conflict_resolution="overwrite"),
                                dict(conflict_resolution="rename", mode="mirror")])
def test_a_mirror_held_did_is_skipped(one_foreign_payload, kw):
    db = MirrorDB()
    out = _restore(db, **kw)
    assert db.inserted_agents == [], "no local agent under a DID a foreign mirror holds"
    assert any("already holds that DID" in w for w in out.get("warnings", [])), out


def test_a_copy_asked_to_rename_gets_a_fresh_did(one_foreign_payload):
    db = MirrorDB()
    _restore(db, conflict_resolution="rename")
    assert len(db.inserted_agents) == 1 and db.inserted_agents[0] != FOREIGN
    assert db.inserted_agents[0].startswith("did:theprotocol:")


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
