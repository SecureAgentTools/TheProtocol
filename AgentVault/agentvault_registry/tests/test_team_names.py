"""§MCPTEST30 (V0524, 2026-10-01) — a team name: an active team refuses it with its own words, a deleted team gives it up.

`teams` carry UNIQUE(organization_id, name) over deleted teams too (a team is soft-deleted), so the name of a team
deleted long ago stayed taken while no listed team carried it, and the caller met the index's own words ("A record with
this value already exists", 409). The tester's unique-name probe (api_tests/contracts/unique_race.py) asks it three ways.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from agentvault_registry.services import organization_service as OS


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar(self):
        return len([t for t in self._rows if t.is_active])


class _DB:
    """Holds the teams of one organization; commit enforces the unique index like Postgres, or raises it on demand
    (a concurrent create that won the race between our check and our insert)."""

    def __init__(self, teams, lose_race=False):
        self.teams = teams
        self.lose_race = lose_race
        self.added, self.rolled_back = [], False

    async def execute(self, stmt):
        text = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "count(" in text.lower():
            return _Result(self.teams)
        name = [t.name for t in self.teams if f"'{t.name}'" in text]
        return _Result([t for t in self.teams if t.name in name])

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        names = [t.name for t in self.teams] + [t.name for t in self.added]
        if self.lose_race or len(names) != len(set(names)):
            raise IntegrityError("INSERT INTO teams", {}, Exception("duplicate key value violates unique constraint"))
        self.teams.extend(self.added)
        self.added = []

    async def rollback(self):
        self.rolled_back = True
        self.added = []


def _team(name, active=True, tid=None):
    return SimpleNamespace(id=tid or f"id-{name}", organization_id="org-1", name=name, is_active=active)


@pytest.fixture(autouse=True)
def _org(monkeypatch):
    async def get_org(db, org_id):
        return SimpleNamespace(id=org_id, limits={"max_teams": 50})
    monkeypatch.setattr(OS.OrganizationService, "get_organization", staticmethod(get_org))


def test_an_active_team_refuses_its_name_in_its_own_words():
    db = _DB([_team("ops")])
    with pytest.raises(OS.TeamNameTaken) as ei:
        asyncio.run(OS.TeamService.create_team(db, "org-1", "ops"))
    assert str(ei.value) == "A team named 'ops' already exists in this organization"
    assert db.added == []


def test_a_deleted_team_gives_its_name_up():
    old = _team("ops", active=False, tid="11111111-2222-3333-4444-555555555555")
    db = _DB([old])
    team = asyncio.run(OS.TeamService.create_team(db, "org-1", "ops"))
    assert team.name == "ops" and team.is_active is not False
    assert old.name == "ops (deleted 11111111-2222-3333-4444-555555555555)"


def test_a_lost_race_is_the_same_refusal():
    db = _DB([], lose_race=True)
    with pytest.raises(OS.TeamNameTaken):
        asyncio.run(OS.TeamService.create_team(db, "org-1", "ops"))
    assert db.rolled_back


def test_a_long_deleted_name_still_fits_the_column():
    old = _team("x" * 255, active=False, tid="abcdef01-0000-0000-0000-000000000000")
    db = _DB([old])
    asyncio.run(OS.TeamService.create_team(db, "org-1", "x" * 255))
    assert len(old.name) == 255 and old.name.endswith(" (deleted abcdef01-0000-0000-0000-000000000000)")


def test_a_rename_onto_an_active_name_is_refused_and_onto_its_own_name_is_not(monkeypatch):
    mine, theirs = _team("a", tid="t-a"), _team("b", tid="t-b")
    db = _DB([mine, theirs])

    async def get_team(db_, team_id, include_members=False):
        return {t.id: t for t in db.teams}.get(team_id)
    monkeypatch.setattr(OS.TeamService, "get_team", staticmethod(get_team))
    with pytest.raises(OS.TeamNameTaken):
        asyncio.run(OS.TeamService.update_team(db, "t-a", name="b"))
    assert asyncio.run(OS.TeamService.update_team(db, "t-a", name="a", description="same name")) is mine


def test_the_routes_answer_409():
    import inspect
    from agentvault_registry.routers import organizations as R
    for fn in (R.create_team, R.update_team):
        src = inspect.getsource(fn)
        assert "except TeamNameTaken as e:" in src and "status_code=409" in src, fn.__name__
