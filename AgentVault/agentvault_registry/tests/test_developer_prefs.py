"""§DASHARRANGE (2026-09-02) — the developer prefs rail, which the cockpit desk and now the
dashboard persist through.

The allowlist admits `cockpit.dashboard`; an unknown key is 404 on GET and PUT; a body
without `value` is 422; a value over the 16 KB cap is 413 and touches no row; a PUT on an
allowed key reaches the DB exactly once and commits. TestClient + dependency overrides; the
session is a recording fake (CI runs these tests in the image with `--network none`).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.database import get_db
from agentvault_registry.routers import developers


class _Result:
    def scalar_one_or_none(self):
        return None


class FakeDB:
    def __init__(self):
        self.executed = []
        self.commits = 0

    async def execute(self, stmt, *a, **kw):
        self.executed.append(stmt)
        return _Result()

    async def commit(self):
        self.commits += 1


@pytest.fixture
def rig():
    app = FastAPI()
    app.include_router(developers.router)
    db = FakeDB()

    async def fake_dev():
        return SimpleNamespace(id=4242, email="prefs@test.local", is_admin=False)

    async def fake_db():
        yield db

    app.dependency_overrides[security.get_current_developer] = fake_dev
    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as c:
        yield c, db


def test_dashboard_key_is_allowed():
    assert "cockpit.dashboard" in developers._PREF_KEYS
    assert "cockpit.layouts" in developers._PREF_KEYS


def test_get_unset_pref_is_null_not_an_error(rig):
    c, _ = rig
    r = c.get("/developers/me/prefs/cockpit.dashboard")
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "cockpit.dashboard", "value": None, "updated_at": None}


def test_unknown_key_is_404_on_both_verbs(rig):
    c, db = rig
    assert c.get("/developers/me/prefs/cockpit.nope").status_code == 404
    assert c.put("/developers/me/prefs/cockpit.nope", json={"value": {}}).status_code == 404
    assert db.commits == 0


def test_put_dashboard_layout_reaches_the_db_once_and_commits(rig):
    c, db = rig
    value = {"panes": ["quickactions", "agents", "earnings", "decisions", "market"], "sizes": {"agents": 3}}
    r = c.put("/developers/me/prefs/cockpit.dashboard", json={"value": value})
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "cockpit.dashboard", "value": value, "saved": True}
    assert len(db.executed) == 1
    assert db.commits == 1


def test_put_without_value_is_422(rig):
    c, db = rig
    r = c.put("/developers/me/prefs/cockpit.dashboard", json={"panes": []})
    assert r.status_code == 422
    assert db.commits == 0


def test_put_over_the_cap_is_413_and_touches_no_row(rig):
    c, db = rig
    r = c.put("/developers/me/prefs/cockpit.dashboard", json={"value": {"blob": "x" * (developers._PREF_MAX_BYTES + 1)}})
    assert r.status_code == 413
    assert db.executed == [] and db.commits == 0
