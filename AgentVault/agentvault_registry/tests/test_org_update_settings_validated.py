"""§SECFIX D6-492 (2026-10-16): PUT /organizations/{org_id} writes `settings` only as PUT /{org_id}/settings does.

Measured on the wave-1 base (7140a4a6) through these same requests: the `settings` of PUT /organizations/{org_id}
REPLACED organizations.settings wholesale with no validation. An admin stored a key another door owns
(room_assistant_present, which only the room operation may write, with its visible trail), a value outside the catalog
(a cockpit_posture the resolver does not know, echoed back as if in force), an intake agent that is not the
organization's, and `{}` wiped every setting the organization had, its liability mode included; a one-key change
dropped the others. Now both routes share one validated deep merge (_merged_settings).

The routes run through FastAPI on the real router over real (SQLite) tables; only the session and the caller's
identity are supplied.
"""
from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import organizations as orgs
from agentvault_registry.security import get_current_developer
from tests._sqlite_db import sqlite_db

OWNER, ADMIN, MEMBER = 1, 2, 3
ORG, OTHER = "org-o", "org-p"
MINE, FOREIGN = "did:theprotocol:org-o-agent-0001", "did:theprotocol:org-p-agent-0002"
START = {"liability": {"mode": "enforce", "presence_threshold_avt": 50}, "cockpit_posture": "hardened",
         "room_assistant_present": False}


def _seed():
    db = sqlite_db(models.Developer, models.Organization, models.OrganizationMember, models.Agent)
    s = db.sync
    db.devs = {}
    for i, name in ((OWNER, "owner"), (ADMIN, "admin"), (MEMBER, "member")):
        db.devs[i] = models.Developer(id=i, name=name, email=f"{name}@example.org", hashed_password="x")
        s.add(db.devs[i])
    s.add(models.Organization(id=ORG, name="Org O", slug="o", owner_id=OWNER, settings=dict(START)))
    s.add(models.Organization(id=OTHER, name="Org P", slug="p", owner_id=MEMBER, settings={}))
    s.add(models.OrganizationMember(id="m-admin", organization_id=ORG, developer_id=ADMIN, role="admin", is_active=True))
    s.add(models.OrganizationMember(id="m-member", organization_id=ORG, developer_id=MEMBER, role="member",
                                    is_active=True))
    for n, (did, org) in enumerate(((MINE, ORG), (FOREIGN, OTHER)), start=1):
        s.add(models.Agent(id=n, did=did, client_id=f"c{n}", hashed_client_secret="x", creator_developer_id=OWNER,
                           organization_id=org, status="active"))
    s.commit()
    return db


@pytest.fixture()
def put():
    db = _seed()
    app = FastAPI()
    app.include_router(orgs.router)
    caller = {"id": ADMIN}

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_developer] = lambda: db.devs[caller["id"]]

    async def call(body, path=f"/api/v1/organizations/{ORG}", as_dev=ADMIN):
        caller["id"] = as_dev
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.put(path, json=body)

    def stored():
        db.sync.expire_all()
        return db.sync.get(models.Organization, ORG).settings

    call.stored = stored
    return call


@pytest.mark.parametrize("settings, says", [
    ({"room_assistant_present": True}, "room_assistant_present"),          # another door's key
    ({"cockpit_posture": "bogus-tier"}, "cockpit_posture"),                # a value outside the catalog
    ({"feature_flags": ["x"]}, "feature_flags"),                           # a key nothing reads
    ({"intake_agent_did": FOREIGN}, "not assigned to this organization"),  # another organization's agent
])
async def test_settings_outside_what_the_settings_route_accepts_are_refused(put, settings, says):
    r = await put({"settings": settings})
    assert r.status_code == 422, r.text                  # the base answered 200 and stored it
    assert says in r.json()["detail"]
    assert put.stored() == START


async def test_an_empty_settings_object_wipes_nothing(put):
    r = await put({"settings": {}})
    assert r.status_code == 200, r.text
    assert put.stored() == START                          # the base stored {}: the liability mode was gone


async def test_a_one_key_change_keeps_the_others(put):
    r = await put({"settings": {"liability": {"presence_threshold_avt": 5}}})
    assert r.status_code == 200, r.text
    assert put.stored() == {**START, "liability": {"mode": "enforce", "presence_threshold_avt": 5}}
    assert r.json()["settings"] == put.stored()


async def test_control_the_organizations_own_agent_may_be_its_intake(put):
    r = await put({"settings": {"intake_agent_did": MINE}})
    assert r.status_code == 200, r.text
    assert put.stored()["intake_agent_did"] == MINE


async def test_control_details_without_settings_leave_the_settings_alone(put):
    r = await put({"name": "Org O renamed", "description": "d"})
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Org O renamed" and put.stored() == START


async def test_control_a_member_may_not_write_settings_on_either_route(put):
    for path in (f"/api/v1/organizations/{ORG}", f"/api/v1/organizations/{ORG}/settings"):
        body = {"settings": {"cockpit_posture": "swift"}} if path.endswith(ORG) else {"cockpit_posture": "swift"}
        assert (await put(body, path=path, as_dev=MEMBER)).status_code == 403
    assert put.stored() == START


async def test_control_the_settings_route_answers_the_same(put):
    assert (await put({"room_assistant_present": True}, path=f"/api/v1/organizations/{ORG}/settings")).status_code == 422
    r = await put({"liability": {"presence_threshold_avt": 5}}, path=f"/api/v1/organizations/{ORG}/settings")
    assert r.status_code == 200, r.text
    assert put.stored() == {**START, "liability": {"mode": "enforce", "presence_threshold_avt": 5}}
