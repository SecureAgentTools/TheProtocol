"""§DOCSFIX D6-502 (2026-10-16): an organization's and a team's counts count what is still there.

A deleted team is marked inactive and keeps its row; a member removed from a team keeps an inactive team row. The
organization list's `team_count` counted every team row (deleted ones included), the organization read counted every
team and member row, the team list's roster (its `member_count` and `member_names`) counted inactive team rows, and the
team read counted every team row it loaded. The team limit itself already counted active teams only, so the dashboard
and the limit disagreed. Each count now reads active rows only: the two grouped queries are pinned by their statements,
the two reads through the route functions with relationships holding inactive rows.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from agentvault_registry.routers import organizations as ORG

NOW = datetime(2026, 10, 16, tzinfo=timezone.utc)


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)

    def fetchall(self):
        return list(self._rows)


class _TextSession:
    """Records each raw statement and answers it with no rows: the statements are what is pinned."""

    def __init__(self):
        self.sql = []

    async def execute(self, stmt, params=None):
        self.sql.append(" ".join(str(stmt).split()))
        return _Rows([])


def _org(**kw):
    base = dict(id="org-1", name="Halden Analytics", slug="halden-ab12", owner_id=1, description=None, website=None,
                logo_url=None, created_at=NOW, updated_at=NOW, is_active=True, settings={}, limits={})
    base.update(kw)
    return SimpleNamespace(**base)


def _team(**kw):
    base = dict(id="team-1", organization_id="org-1", name="Default Team", description=None, created_at=NOW,
                updated_at=NOW, is_active=True, permissions=[])
    base.update(kw)
    return SimpleNamespace(**base)


def test_the_organization_lists_team_count_reads_active_teams(monkeypatch):
    async def _orgs(db, developer_id):
        return [_org()]

    monkeypatch.setattr(ORG.OrganizationService, "list_developer_organizations", _orgs)
    db = _TextSession()
    _run(ORG.list_organizations(current_developer=SimpleNamespace(id=1), db=db))
    team_sql = [s for s in db.sql if "FROM teams" in s]
    assert len(team_sql) == 1, db.sql
    assert "is_active = true" in team_sql[0], team_sql[0]


def test_the_team_lists_roster_reads_active_team_rows(monkeypatch):
    async def _allowed(org_id, developer, db, required_role=None):
        return _org()

    async def _teams(db, org_id):
        return [_team()]

    monkeypatch.setattr(ORG, "get_organization_with_permission", _allowed)
    monkeypatch.setattr(ORG.TeamService, "list_organization_teams", _teams)
    db = _TextSession()
    _run(ORG.list_teams(org_id="org-1", current_developer=SimpleNamespace(id=1), db=db))
    roster = [s for s in db.sql if "FROM team_members" in s]
    assert len(roster) == 1, db.sql
    assert "tm.is_active = true" in roster[0], roster[0]


def test_the_organization_read_counts_active_members_and_teams(monkeypatch):
    members = [SimpleNamespace(is_active=True), SimpleNamespace(is_active=True), SimpleNamespace(is_active=False)]
    teams = [_team(), _team(id="team-2", is_active=False), _team(id="team-3", is_active=False)]

    async def _allowed(org_id, developer, db, required_role=None):
        return _org()

    async def _with_relations(db, org_id, include_members=False, include_teams=False):
        return SimpleNamespace(members=members, teams=teams)

    monkeypatch.setattr(ORG, "get_organization_with_permission", _allowed)
    monkeypatch.setattr(ORG.OrganizationService, "get_organization", _with_relations)
    out = _run(ORG.get_organization(org_id="org-1", current_developer=SimpleNamespace(id=1), db=None))
    assert (out.member_count, out.team_count) == (2, 1)


def test_the_team_read_counts_active_team_rows(monkeypatch):
    async def _allowed(org_id, developer, db, required_role=None):
        return _org()

    async def _get_team(db, team_id, include_members=False):
        return _team(members=[SimpleNamespace(is_active=True), SimpleNamespace(is_active=False)])

    monkeypatch.setattr(ORG, "get_organization_with_permission", _allowed)
    monkeypatch.setattr(ORG.TeamService, "get_team", _get_team)
    out = _run(ORG.get_team(org_id="org-1", team_id="team-1", current_developer=SimpleNamespace(id=1), db=None))
    assert out.member_count == 1
