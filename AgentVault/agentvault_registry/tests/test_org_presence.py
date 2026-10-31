"""V0650 (a) (2026-10-31, agentvault2-14): an organization's presence (GET /api/v1/organizations/{org_id}/presence).

Order gwo_6630c6afb216eba6c3270dbc. Every agent assigned to the organization, with its card name, owner, last activity,
account status and live status line, for whoever the organization's room admits, by the room's own rule (the poster's
answer, room seq 76): an active member (guests included) or an agent assigned to it. Through FastAPI on the real
organizations router over real (SQLite) tables; only the caller's identity is supplied. Cases marked BASE fail on
6c1f036b (V0649).
"""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from agentvault_registry import models
from agentvault_registry.database import get_db
from agentvault_registry.routers import organizations
from agentvault_registry.security import get_current_actor_for_read
from tests._sqlite_db import sqlite_db

OWNER, ADMIN, MEMBER, GUEST, LAPSED, OUTSIDER = 1, 2, 3, 4, 5, 6
A1, A2, A_SUS, A_REV, A_OTHER, A_NONE = (f"did:theprotocol:eu:00000000-0000-4000-8000-00000000000{i}" for i in range(1, 7))
T0 = dt.datetime(2026, 10, 31, 5, 0, 0, tzinfo=dt.timezone.utc)


def _seed():
    tables = [m for m in (models.Developer, models.Organization, models.OrganizationMember, models.Agent,
                          models.AgentCard, getattr(models, "AgentStatusLine", None)) if m is not None]
    db = sqlite_db(*tables)
    s = db.sync
    for i in (OWNER, ADMIN, MEMBER, GUEST, LAPSED, OUTSIDER):
        s.add(models.Developer(id=i, name=f"d{i}", email=f"d{i}@example.org", hashed_password="x"))
    s.add(models.Organization(id="org-s", name="Sessions", slug="sessions", owner_id=OWNER, settings={}))
    s.add(models.Organization(id="org-x", name="Other", slug="other", owner_id=OUTSIDER, settings={}))
    for n, (dev, role, active) in enumerate(((OWNER, "owner", True), (ADMIN, "admin", True), (MEMBER, "member", True),
                                             (GUEST, "guest", True), (LAPSED, "member", False))):
        s.add(models.OrganizationMember(id=f"m{n}", organization_id="org-s", developer_id=dev, role=role,
                                        is_active=active))
    for i, (did, org, status) in enumerate(((A1, "org-s", "active"), (A2, "org-s", "active"),
                                            (A_SUS, "org-s", "suspended"), (A_REV, "org-s", "revoked"),
                                            (A_OTHER, "org-x", "active"), (A_NONE, None, "active")), start=1):
        s.add(models.Agent(id=i, did=did, client_id=f"c{i}", hashed_client_secret="x", creator_developer_id=OWNER,
                           organization_id=org, status=status, created_at=T0 + dt.timedelta(minutes=i)))
    s.add(models.AgentCard(developer_id=OWNER, agent_did=A1, card_data={}, name="session-release", is_active=True))
    if hasattr(models, "AgentStatusLine"):
        s.add(models.AgentStatusLine(agent_did=A1, status_text="building V0650", set_at=T0,
                                     expires_at=T0 + dt.timedelta(hours=1)))
        s.add(models.AgentStatusLine(agent_did=A_SUS, status_text="should not show", set_at=T0,
                                     expires_at=T0 + dt.timedelta(hours=1)))
    s.commit()
    return db


@pytest.fixture()
def presence(monkeypatch):
    db = _seed()
    clock = {"now": T0 + dt.timedelta(minutes=10)}
    try:
        from agentvault_registry.services import agent_status_line as sl
        monkeypatch.setattr(sl, "_now", lambda: clock["now"])
    except ImportError:
        pass
    app = FastAPI()
    app.include_router(organizations.router)
    who = {"actor": None}

    async def _yield_db():
        yield db
    app.dependency_overrides[get_db] = _yield_db
    app.dependency_overrides[get_current_actor_for_read] = lambda: who["actor"]

    async def do(actor, org="org-s"):
        who["actor"] = actor
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            return await c.get(f"/api/v1/organizations/{org}/presence")
    do.clock = clock
    return do


def _dev(i):
    return {"kind": "developer", "developer": SimpleNamespace(id=i, name=f"d{i}", email=f"d{i}@example.org")}


def _agent(did):
    return {"kind": "agent", "agent_did": did, "agent": SimpleNamespace(did=did, name="a")}


@pytest.mark.asyncio
@pytest.mark.parametrize("actor,want", [
    (_dev(OWNER), 200), (_dev(ADMIN), 200), (_dev(MEMBER), 200), (_dev(GUEST), 200),   # the room's rule
    (_dev(LAPSED), 403), (_dev(OUTSIDER), 403),
    (_agent(A1), 200), (_agent(A_OTHER), 403), (_agent(A_NONE), 403),
])
async def test_who_reads_presence_is_who_the_room_admits(presence, actor, want):
    # BASE: 404 (no route) for every caller
    r = await presence(actor)
    assert r.status_code == want, (r.status_code, r.text[:200])


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [_dev(OWNER), _agent(A1)])
async def test_an_unknown_organization_is_404(presence, actor):
    # control: 404 on both trees (no such route there, no such org here)
    assert (await presence(actor, org="org-nope")).status_code == 404


@pytest.mark.asyncio
async def test_the_presence_lists_assigned_agents_with_their_live_lines(presence):
    # BASE: 404
    body = (await presence(_dev(MEMBER))).json()
    by = {a["did"]: a for a in body["agents"]}
    assert set(by) == {A1, A2, A_SUS}, "another org's agent, an unassigned one and a revoked one are absent"
    assert [a["did"] for a in body["agents"]] == [A1, A2, A_SUS] and body["count"] == 3
    assert by[A1]["name"] == "session-release" and by[A1]["owner_developer_id"] == OWNER
    assert by[A1]["status"]["text"] == "building V0650" and by[A1]["account_status"] == "active"
    assert by[A2]["name"] is None and by[A2]["status"] is None
    assert by[A_SUS]["status"] is None and by[A_SUS]["account_status"] == "suspended"


@pytest.mark.asyncio
async def test_a_line_past_its_expiry_reads_as_none(presence):
    # BASE: 404
    presence.clock["now"] = T0 + dt.timedelta(hours=2)
    body = (await presence(_agent(A1))).json()
    assert {a["did"]: a["status"] for a in body["agents"]}[A1] is None


def test_the_presence_route_is_either_tier():
    # BASE: no such route
    from agentvault_registry.core import auth_tiers
    route = next((r for r in organizations.router.routes
                  if getattr(r, "path", "") == "/api/v1/organizations/{org_id}/presence"), None)
    assert route is not None and auth_tiers.route_tier(route) == auth_tiers.EITHER
