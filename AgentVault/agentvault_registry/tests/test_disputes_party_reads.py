"""§SECFIX D6-465 (2026-10-16, his word): a dispute is read by the owners of its parties and by the administrators
who rule on disputes; nobody else.

Measured on the base (14520b9f) through these same requests: GET /api/v1/disputes/ listed every dispute of the
registry, evidence included, to any developer credential; GET /api/v1/disputes/{id} returned any dispute to any
developer credential; GET /api/v1/disputes/agent/{did} listed any agent's disputes to any developer credential. Only
an AGENT credential was held to its own disputes.

Why no test caught it: no test ever read a dispute as a developer who owns neither party. tests/test_disputes_list_order
compiles the list's statement (its order), with no caller at all; the API tester's sweep and the MCP tester's
dispute_paths lifecycle read GET /disputes/ and GET /disputes/{id} with the sandbox ADMIN's developer token (who may
read every dispute, then and now) and passed on any 2xx, or on any status under "any"; the console suite's lifecycle 33
read every state back as the complainant's owner, a party. It now also asks a developer who is no party
(e2e/suite/lifecycles/33-disputes.spec.ts, step a-developer-who-is-no-party-reads-nothing).

The routes run through FastAPI on the real router over real (SQLite) rows; only the session and the caller are
supplied.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models, security
from agentvault_registry.database import get_db
from agentvault_registry.routers import disputes
from tests._sqlite_db import sqlite_db

ADMIN, OWNER_A, OWNER_B, OWNER_S, NOBODY, ENFORCER = 1, 2, 3, 4, 5, 6
A1, B1, S1 = ("did:theprotocol:aaaaaaaa-0000-4000-8000-000000000001",
              "did:theprotocol:bbbbbbbb-0000-4000-8000-000000000002",
              "did:theprotocol:cccccccc-0000-4000-8000-000000000003")
T0 = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)


def _seed():
    db = sqlite_db(models.Developer, models.Agent, models.Dispute, models.Evidence)
    s = db.sync
    db.devs = {}
    for i in (ADMIN, OWNER_A, OWNER_B, OWNER_S, NOBODY, ENFORCER):
        db.devs[i] = models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x",
                                      is_admin=(i == ADMIN), admin_enforcement=(i == ENFORCER))
        s.add(db.devs[i])
    for n, (did, owner) in enumerate(((A1, OWNER_A), (B1, OWNER_B), (S1, OWNER_S)), start=1):
        s.add(models.Agent(id=n, did=did, client_id=f"c{n}", hashed_client_secret="x", creator_developer_id=owner))
    d1 = models.Dispute(id=1, complainant_did=A1, defendant_did=B1, status="OPEN", created_at=T0, updated_at=T0)
    d2 = models.Dispute(id=2, complainant_did=S1, defendant_did=B1, status="OPEN",
                        created_at=T0 + dt.timedelta(hours=1), updated_at=T0 + dt.timedelta(hours=1))
    s.add_all([d1, d2])
    s.add(models.Evidence(id=1, dispute_id=1, submitter_did=A1, evidence_data={"amount": 5}, created_at=T0))
    s.commit()
    return db


@pytest.fixture()
def call():
    db = _seed()
    app = FastAPI()
    app.include_router(disputes.router)
    who = {}

    async def _db():
        yield db

    def _developer():
        return db.devs[who["dev"]]

    async def _actor():
        security._PRESENTED_KEY_SCOPES.set(who.get("scopes"))     # as the auth dependency does (None: a JWT)
        if "agent" in who:
            return {"kind": "agent", "agent_did": who["agent"], "agent": None}
        return {"kind": "developer", "developer": db.devs[who["dev"]]}

    async def _dev_dep():
        security._PRESENTED_KEY_SCOPES.set(who.get("scopes"))
        return _developer()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[security.get_current_developer] = _dev_dep
    app.dependency_overrides[security.get_current_actor_for_read] = _actor

    async def _call(path, dev=None, agent=None, scopes=None):
        who.clear()
        who.update({"dev": dev, "scopes": scopes})
        if agent:
            who["agent"] = agent
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(path)

    return _call


@pytest.mark.parametrize("dev, ids", [
    (OWNER_A, {1}),          # the complainant's owner
    (OWNER_B, {1, 2}),       # the defendant's owner, in both
    (OWNER_S, {2}),
    (NOBODY, set()),         # the defect: a developer who owns no party listed every dispute
    (ADMIN, {1, 2}),         # control: the administrators who rule read every dispute
    (ENFORCER, {1, 2}),
])
async def test_the_list_holds_the_callers_disputes(call, dev, ids):
    r = await call("/api/v1/disputes/", dev=dev)
    assert r.status_code == 200, r.text
    assert {d["id"] for d in r.json()} == ids


async def test_the_lists_filters_still_apply_inside_the_callers_disputes(call):
    r = await call(f"/api/v1/disputes/?complainant_did={S1}", dev=OWNER_B)
    assert [d["id"] for d in r.json()] == [2]
    r = await call(f"/api/v1/disputes/?complainant_did={S1}", dev=OWNER_A)
    assert r.json() == []


async def test_an_admin_on_an_api_key_scoped_for_tools_reads_as_a_developer(call):
    r = await call("/api/v1/disputes/", dev=ADMIN, scopes=["mcp:tools"])
    assert r.status_code == 200 and r.json() == []      # the admin's agents are in no dispute here
    assert (await call("/api/v1/disputes/1", dev=ADMIN, scopes=["mcp:tools"])).status_code == 403
    assert (await call("/api/v1/disputes/1", dev=ADMIN, scopes=["mcp:admin"])).status_code == 200


@pytest.mark.parametrize("dev, dispute_id, status", [
    (NOBODY, 1, 403),        # the defect: any developer read any dispute, evidence included
    (OWNER_S, 1, 403),
    (OWNER_A, 2, 403),
    (OWNER_A, 1, 200),       # control: a party's owner
    (OWNER_B, 2, 200),
    (ADMIN, 2, 200),
    (ENFORCER, 1, 200),
    (NOBODY, 99, 404),
])
async def test_one_dispute_by_id(call, dev, dispute_id, status):
    r = await call(f"/api/v1/disputes/{dispute_id}", dev=dev)
    assert r.status_code == status, r.text
    if status == 403:
        assert "evidence" not in r.text and A1 not in r.text


@pytest.mark.parametrize("agent, dispute_id, status", [(A1, 1, 200), (A1, 2, 403), (S1, 2, 200)])
async def test_control_an_agent_credential_reads_its_own_disputes_as_before(call, agent, dispute_id, status):
    assert (await call(f"/api/v1/disputes/{dispute_id}", agent=agent)).status_code == status


@pytest.mark.parametrize("who, did, status", [
    ({"dev": NOBODY}, B1, 403),     # the defect: any developer listed any agent's disputes
    ({"dev": OWNER_A}, B1, 403),
    ({"dev": OWNER_B}, B1, 200),
    ({"dev": ADMIN}, B1, 200),
    ({"agent": B1}, B1, 200),
    ({"agent": A1}, B1, 403),       # as before
])
async def test_one_agents_disputes(call, who, did, status):
    r = await call(f"/api/v1/disputes/agent/{did}", **who)
    assert r.status_code == status, r.text
    if status == 200:
        assert {d["id"] for d in r.json()} == {1, 2}
