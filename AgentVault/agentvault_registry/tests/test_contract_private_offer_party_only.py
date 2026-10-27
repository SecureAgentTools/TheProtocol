"""§MCPTEST30 (V0556): a private contract offer is read by its parties only, through both views of the spine row.

The v2 detail's own comment said "open offers are browsable; concluded/private agreements are party-only" while its code
let any agent read every OFFERED contract, so a private offer naming another provider (engageAgent's, §XHIRE's) was
readable by any agent holding its id (spine ids are 96 random bits, so the id had to leak first). One rule now,
contracts_v2.agent_may_read, asked by GET /contracts/v2/{cid} and by the legacy GET /contracts/{id}.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import contracts as legacy
from agentvault_registry.routers import contracts_v2 as v2

CLIENT, PROVIDER, STRANGER = "did:theprotocol:client", "did:theprotocol:provider", "did:theprotocol:stranger"
PRIVATE = {"client_did": CLIENT, "provider_did": PROVIDER, "status": "offered"}
OPEN = {"client_did": CLIENT, "provider_did": None, "status": "offered"}
DONE = {"client_did": CLIENT, "provider_did": PROVIDER, "status": "completed"}


def agent(did):
    return {"kind": "agent", "agent_did": did}


MATRIX = [
    (agent(STRANGER), PRIVATE, False),     # the defect: a private offer read by an agent that is no party to it
    (agent(PROVIDER), PRIVATE, True),      # the named provider reads the offer made to it
    (agent(CLIENT), PRIVATE, True),
    (agent(STRANGER), OPEN, True),         # an open offer stays browsable
    (agent(STRANGER), {**OPEN, "provider_did": ""}, True),
    (agent(STRANGER), DONE, False),
    (agent(PROVIDER), DONE, True),
    (agent(STRANGER), {**OPEN, "status": "draft"}, False),
    ({"kind": "developer", "developer_id": 8}, PRIVATE, True),   # a developer JWT reads as before
]


@pytest.mark.parametrize("actor,row,may", MATRIX)
def test_one_rule_for_both_views(actor, row, may):
    assert v2.agent_may_read(actor, row) is may
    assert legacy._agent_may_read(actor, row) is may


class _Rows:
    def mappings(self):
        return self

    def all(self):
        return []

    def first(self):
        return None


class _Db:
    async def execute(self, *a, **k):
        return _Rows()


@pytest.fixture()
def detail(monkeypatch):
    def use(row):
        async def _none(db, cid):
            return None

        async def _load(db, cid):
            return dict(row, id="ctr_test")
        monkeypatch.setattr(v2, "_require_enabled", lambda: None)
        monkeypatch.setattr(v2, "_replica_row", _none)
        monkeypatch.setattr(v2, "_must_load", _load)
        monkeypatch.setattr(v2, "_contract_out", lambda c: {"id": c["id"], "status": c["status"]})
    return use


async def test_the_v2_detail_refuses_a_private_offer_to_a_stranger(detail):
    detail(PRIVATE)
    with pytest.raises(HTTPException) as e:
        await v2.get_contract_v2("ctr_test", actor=agent(STRANGER), db=_Db())
    assert e.value.status_code == 403 and "Not a party" in str(e.value.detail)


async def test_the_v2_detail_still_shows_an_open_offer_and_the_parties_their_own(detail):
    for row, who in ((OPEN, STRANGER), (PRIVATE, PROVIDER), (PRIVATE, CLIENT)):
        detail(row)
        out = await v2.get_contract_v2("ctr_test", actor=agent(who), db=_Db())
        assert out == {"id": "ctr_test", "status": "offered", "milestones": [], "events": []}, (row, who)
