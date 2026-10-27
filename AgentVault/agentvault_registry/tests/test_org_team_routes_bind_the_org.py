"""§MCPTEST30 (2026-10-01) — a team route acts only on a team of the organization whose authority it checked.

The routes take the caller's role in {org_id} and act on {team_id}. Read in the code beside the owner-scoping sweep:
PUT .../teams/{team_id} called TeamService.update_team (which commits) and only THEN compared the team's organization,
so an admin of any organization (anyone can found one) rewrote another organization's team and was answered 404;
POST and DELETE .../teams/{team_id}/members never compared it. Each now refuses BEFORE the service is called.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.routers import organizations as O

TEAM_ORG, CALLER_ORG = "org-of-the-team", "org-of-the-caller"


@pytest.fixture
def wired(monkeypatch):
    calls = []

    async def permitted(org_id, dev, db, required_role=None):
        return SimpleNamespace(id=org_id)

    async def get_team(db, team_id, include_members=False):
        return SimpleNamespace(id=team_id, organization_id=TEAM_ORG, name="their team", description="d",
                               created_at=None, updated_at=None, is_active=True, permissions=[], members=[])

    async def update_team(db, team_id, **kw):
        calls.append(("update", team_id, kw))
        return await get_team(db, team_id)

    async def add_member(db, team_id, developer_id, role="member"):
        calls.append(("add", team_id, developer_id))
        return SimpleNamespace(id="m1", role=role)

    async def remove_member(db, team_id, developer_id):
        calls.append(("remove", team_id, developer_id))
        return True
    monkeypatch.setattr(O, "get_organization_with_permission", permitted)
    monkeypatch.setattr(O.TeamService, "get_team", staticmethod(get_team))
    monkeypatch.setattr(O.TeamService, "update_team", staticmethod(update_team))
    monkeypatch.setattr(O.TeamService, "add_team_member", staticmethod(add_member))
    monkeypatch.setattr(O.TeamService, "remove_team_member", staticmethod(remove_member))
    return calls


class _Rows:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class MemberDB:
    """Answers the membership read of POST .../members: is developer `member_id` an active member of the org?"""

    def __init__(self, members=()):
        self.members, self.asked = set(members), []

    async def execute(self, stmt, params=None):
        compiled = stmt.compile()
        p = compiled.params
        dev = next((v for k, v in p.items() if k.startswith("developer_id")), None)
        self.asked.append(dev)
        return _Rows(("m",) if dev in self.members else None)


def _refused(coro):
    with pytest.raises(HTTPException) as e:
        asyncio.run(coro)
    return e.value.status_code


def test_another_orgs_team_is_refused_before_anything_is_written(wired):
    dev = SimpleNamespace(id=8)
    assert _refused(O.update_team(org_id=CALLER_ORG, team_id="t1", team_update=O.TeamUpdate(description="changed"),
                                  current_developer=dev, db=None)) == 404
    assert _refused(O.add_team_member(org_id=CALLER_ORG, team_id="t1", member_data=O.TeamMemberAdd(developer_id=8),
                                      current_developer=dev, db=None)) == 404
    assert _refused(O.remove_team_member(org_id=CALLER_ORG, team_id="t1", developer_id=7, current_developer=dev,
                                         db=None)) == 404
    assert wired == [], "the service was called for a team of another organization"


def test_control_a_team_of_the_checked_org_goes_through(wired):
    dev = SimpleNamespace(id=7)
    out = asyncio.run(O.add_team_member(org_id=TEAM_ORG, team_id="t1", member_data=O.TeamMemberAdd(developer_id=9),
                                        current_developer=dev, db=MemberDB(members={9})))
    assert out["member_id"] == "m1"
    out = asyncio.run(O.remove_team_member(org_id=TEAM_ORG, team_id="t1", developer_id=9, current_developer=dev, db=None))
    assert "removed" in out["message"]
    assert [c[0] for c in wired] == ["add", "remove"]


def test_a_developer_who_is_not_a_member_of_the_org_is_never_added(wired):
    """The roster (GET /{org}/teams) prints each member's name: adding any id let a founder read the name behind it."""
    db = MemberDB(members={9})
    with pytest.raises(HTTPException) as e:
        asyncio.run(O.add_team_member(org_id=TEAM_ORG, team_id="t1", member_data=O.TeamMemberAdd(developer_id=4242),
                                      current_developer=SimpleNamespace(id=7), db=db))
    assert e.value.status_code == 400 and "not a member of this organization" in e.value.detail
    assert db.asked == [4242] and wired == [], "the service was called for a developer outside the organization"


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
