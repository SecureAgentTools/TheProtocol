"""§MCPTEST30 (2026-10-01) — the legacy contract read keeps the v2 party rule.

GET /contracts/{id} is the legacy view over the same spine row GET /contracts/v2/{cid} reads, and it had no party rule:
measured on sbx-alpha (V0508), an agent that is no party to a completed contract read all of it through
getContractById (200) while getContractV2 refused it (403). An agent reads a contract it is a party to, or an open
offer; a developer JWT reads as before.
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import contracts as C

ROW = {"id": "ctr_abc", "client_did": "did:theprotocol:client", "provider_did": "did:theprotocol:provider",
       "status": "completed"}


@pytest.mark.parametrize("actor,row,may", [
    ({"kind": "agent", "agent_did": "did:theprotocol:client"}, ROW, True),
    ({"kind": "agent", "agent_did": "did:theprotocol:provider"}, ROW, True),
    ({"kind": "agent", "agent_did": "did:theprotocol:stranger"}, ROW, False),
    ({"kind": "agent", "agent_did": "did:theprotocol:stranger"}, {**ROW, "status": "offered", "provider_did": None}, True),
    # §MCPTEST30 (V0556): a PRIVATE offer (a provider named) is party-only, the v2 rule's own words
    ({"kind": "agent", "agent_did": "did:theprotocol:stranger"}, {**ROW, "status": "offered"}, False),
    ({"kind": "agent", "agent_did": "did:theprotocol:provider"}, {**ROW, "status": "offered"}, True),
    ({"kind": "agent", "agent_did": "did:theprotocol:stranger"}, {**ROW, "status": "draft"}, False),
    ({"kind": "developer", "developer_id": 8}, ROW, True),
])
def test_the_rule(actor, row, may):
    assert C._agent_may_read(actor, row) is may


def test_the_route_refuses_a_non_party_agent_and_answers_a_party(monkeypatch):
    async def resolve(db, cid):
        return dict(ROW)

    async def m1(db, cid):
        return None
    monkeypatch.setattr(C, "_resolve", resolve)
    monkeypatch.setattr(C, "_m1", m1)
    monkeypatch.setattr(C, "_to_response", lambda c, m: {"ref": c["id"]})
    with pytest.raises(HTTPException) as e:
        asyncio.run(C.get_contract("ctr_abc", db=None, actor={"kind": "agent", "agent_did": "did:theprotocol:stranger"}))
    assert e.value.status_code == 403 and "party" in str(e.value.detail)
    out = asyncio.run(C.get_contract("ctr_abc", db=None, actor={"kind": "agent", "agent_did": "did:theprotocol:client"}))
    assert out == {"ref": "ctr_abc"}


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
