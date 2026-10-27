"""§SECFIX D6-499 (2026-10-16): an organization's guest does not run the CI/CD of the organization's agents.

Measured on the wave-1 base (7140a4a6) through these same requests: agent_cicd_service._get_agent_with_permission let
in any ACTIVE member of the agent's organization, so a guest (who may only read the organization) listed and created
pipelines, and with them every other pipeline, version, deployment and relay operation the rule guards. It now asks
the organization's own role check (OrganizationService.check_member_permission with `member`, the bar the
organization's CI/CD summary already sets): the agent's creator, the organization's owner, or a member, admin or
owner of it. A guest, a lapsed member and an outsider are refused with 403.

The routes run through FastAPI on the real router over real (SQLite) tables; only the session, the caller's identity
and the audit emitter are supplied.
"""
from __future__ import annotations

import datetime as dt

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import text

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_cicd
from agentvault_registry.security import get_current_developer
from agentvault_registry.services import agent_cicd_service as cicd_module
from tests._sqlite_db import sqlite_db

CREATOR, OWNER, ADMIN, MEMBER, GUEST, OUTSIDER, LAPSED = 1, 2, 3, 4, 5, 6, 7
AGENT = "did:theprotocol:org-o-builder-0001"


def _seed():
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.Agent)
    raw = db.sync.get_bind().raw_connection()           # one connection (StaticPool): the function serves the session
    raw.driver_connection.create_function(
        "NOW", 0, lambda: dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f"))
    raw.close()
    s = db.sync
    s.execute(text("CREATE TABLE agent_pipelines (id TEXT PRIMARY KEY, agent_did TEXT, pipeline_name TEXT, "
                   "pipeline_config TEXT, trigger_type TEXT, webhook_url TEXT, webhook_secret TEXT, is_active BOOLEAN, "
                   "environment_vars TEXT, notification_config TEXT, created_by INTEGER, created_at TEXT, "
                   "updated_at TEXT)"))
    db.devs = {}
    for i in (CREATOR, OWNER, ADMIN, MEMBER, GUEST, OUTSIDER, LAPSED):
        db.devs[i] = models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x")
        s.add(db.devs[i])
    s.add(models.Organization(id="org-o", name="Org O", slug="o", owner_id=OWNER, settings={}))
    for n, (dev, role, active) in enumerate(((OWNER, "owner", True), (ADMIN, "admin", True), (MEMBER, "member", True),
                                             (GUEST, "guest", True), (LAPSED, "member", False))):
        s.add(models.OrganizationMember(id=f"m{n}", organization_id="org-o", developer_id=dev, role=role,
                                        is_active=active))
    s.add(models.Agent(id=1, did=AGENT, client_id="c1", hashed_client_secret="x", creator_developer_id=CREATOR,
                       organization_id="org-o", status="active"))
    s.commit()
    return db


@pytest.fixture()
def call(monkeypatch):
    db = _seed()
    app = FastAPI()
    app.include_router(agent_cicd.router, prefix="/api/v1")
    caller = {"id": None}

    async def _db():
        yield db

    async def _no_event(*_a, **_k):
        return None

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_developer] = lambda: db.devs[caller["id"]]
    monkeypatch.setattr(cicd_module, "_emit_cicd_event", _no_event)

    async def do(method, as_dev, body=None):
        caller["id"] = as_dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.request(method, f"/api/v1/agents/{AGENT}/pipelines", json=body)

    def pipelines():
        return db.sync.execute(text("SELECT COUNT(*) FROM agent_pipelines")).scalar()

    do.pipelines = pipelines
    return do


@pytest.mark.parametrize("dev, status", [
    (CREATOR, 200), (OWNER, 200), (ADMIN, 200), (MEMBER, 200),     # controls: the agent's creator and the org's people
    (GUEST, 403),                                                  # the defect: the base answered 200
    (OUTSIDER, 403), (LAPSED, 403),                                # controls: refused before and after
])
async def test_who_may_read_an_organization_agents_pipelines(call, dev, status):
    r = await call("GET", dev)
    assert r.status_code == status, r.text


async def test_a_guest_cannot_create_a_pipeline_and_nothing_is_written(call):
    r = await call("POST", GUEST, {"pipeline_name": "deploy", "pipeline_config": {"steps": []}})
    assert r.status_code == 403, r.text                           # the base created it
    assert call.pipelines() == 0


async def test_control_a_member_creates_one(call):
    r = await call("POST", MEMBER, {"pipeline_name": "deploy", "pipeline_config": {"steps": []}})
    assert r.status_code == 200, r.text
    assert call.pipelines() == 1
