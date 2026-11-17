"""V0662 sidebar (order gwo_0feb166a01e2ff611e154361): the sidebar's pins follow the account, under their own key in the
developer prefs (console.nav_pins: the paths a person pinned, whole-value replace like every key). A preference, never
authority: it decides what a person sees first, never what anything may do. Red on f569f6a6e: the key is unknown (404).
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
        self.executed, self.commits = [], 0

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
        return SimpleNamespace(id=4243, email="pins@test.local", is_admin=False)

    async def fake_db():
        yield db
    app.dependency_overrides[security.get_current_developer] = fake_dev
    app.dependency_overrides[get_db] = fake_db
    with TestClient(app) as c:
        yield c, db


def test_the_pins_key_reads_unset_as_null(rig):
    c, _ = rig
    r = c.get("/developers/me/prefs/console.nav_pins")
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "console.nav_pins", "value": None, "updated_at": None}


def test_the_pins_key_takes_a_whole_value_once(rig):
    c, db = rig
    value = {"paths": ["/mission-control", "/ourchat", "/guild"]}
    r = c.put("/developers/me/prefs/console.nav_pins", json={"value": value})
    assert r.status_code == 200, r.text
    assert r.json() == {"key": "console.nav_pins", "value": value, "saved": True}
    assert len(db.executed) == 1 and db.commits == 1


def test_a_neighbouring_unknown_key_is_still_404(rig):
    # control: the allowlist grew by one key, not by a prefix
    c, db = rig
    assert c.get("/developers/me/prefs/console.nav_pins_x").status_code == 404
    assert c.put("/developers/me/prefs/console.other", json={"value": {}}).status_code == 404
    assert db.commits == 0
