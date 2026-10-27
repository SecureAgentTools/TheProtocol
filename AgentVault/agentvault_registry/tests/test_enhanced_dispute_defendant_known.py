"""POST /disputes/enhanced/log asks the question POST /disputes/ asks (§DIDWIDEN-1): is the defendant an agent this
registry knows? It filed a real dispute against any well-formed DID until 2026-10-24 (agentvault2-66, found earning
logEnhancedDispute's success path for the MCP tester). A refused filing writes no dispute row."""
import asyncio
import types

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import disputes as _disputes
from agentvault_registry.routers import disputes_enhanced as de


class _Stop(Exception):
    pass


def _file(monkeypatch, known: bool):
    async def _known(db, did):
        return known
    written = []

    async def _create(**kw):
        written.append(kw)
        raise _Stop()                       # the row write is as far as this test needs to see
    monkeypatch.setattr(_disputes, "defendant_known", _known)
    monkeypatch.setattr(de.crud_disputes, "create_dispute", _create)
    data = de.EnhancedDisputeCreate(defendant_agent_id="did:theprotocol:00000000-0000-4000-8000-00000000d15b",
                                    reason_code="OTHER", brief_description="a defendant this registry may not know")
    agent = types.SimpleNamespace(did="did:theprotocol:00000000-0000-4000-8000-0000000c0de1", id=1)
    class _Db:                              # the route rolls back on any failure of the write
        async def rollback(self):
            return None
    try:
        return asyncio.run(de.log_dispute(data, db=_Db(), current_agent=agent)), written
    except HTTPException as e:
        if written:                         # the write was reached (and the route answered its failure)
            raise _Stop() from e
        raise


def test_a_defendant_nobody_knows_is_refused_before_any_row_is_written(monkeypatch):
    with pytest.raises(HTTPException) as e:
        _file(monkeypatch, known=False)
    assert e.value.status_code == 404 and "not known to this registry" in str(e.value.detail)


def test_a_known_defendant_reaches_the_dispute_row(monkeypatch):
    # the control: the guard refuses the unknown defendant only, so a known one goes on to the write
    with pytest.raises(_Stop):
        _file(monkeypatch, known=True)
