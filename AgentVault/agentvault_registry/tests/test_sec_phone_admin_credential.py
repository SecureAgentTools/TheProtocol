"""D6-529 (2026-10-16): the Phone Fabric admin routes ask the presented credential's authority, not the account's flag.

routers/phone_fabric.py's five admin routes (the pool, the session list, one session's trace, the per-session kill and
the global halt) checked `developer.is_admin` alone. Every other inline admin check asks security.admin_credential
since §POCKETPAIR: the account is an admin AND the credential on this request reaches admin (a scoped API key needs
'mcp:admin') AND REQUIRE_ADMIN_2FA holds. So a narrow key of an admin account, or an admin without the second factor
the registry requires, could read every session's trace and halt every phone session. Each case marked BASE fails on
7140a4a6.

Through FastAPI on the real router (GET /api/v1/admin/phone/pool, POST /api/v1/admin/phone/global-halt); only the
database is replaced (the key and developer lookups, the pool rows).
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.routers import phone_fabric

KEY = "avreg_" + "p" * 43


def _admin(two_fa=True):
    return SimpleNamespace(id=7, email="admin@example.test", name="Admin", is_admin=True, admin_support=False,
                           admin_treasury=False, admin_enforcement=False, admin_federation=False, admin_platform=False,
                           must_change_password=False, is_suspended=False, deleted_at=None, deletion_status=None,
                           two_fa_enabled=two_fa, is_verified=True, token_version=0)


class _Result:
    def __init__(self, rows=(), scalar=0, rowcount=0):
        self._rows, self._scalar, self.rowcount = list(rows), scalar, rowcount

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)

    def scalar(self):
        return self._scalar

    def fetchall(self):
        # the halt reads the sessions it ended (RETURNING), one per halted session, to emit their PhoneSessionEnded
        return [type("Row", (), {"id": f"pfs_{i}", "agent_did": f"did:theprotocol:a{i}", "actions_used": 0,
                                 "budget_spent": 0})() for i in range(self.rowcount)]


class _Session:
    """Answers the pool route's two reads and the halt's two writes; records whether a write ran."""

    def __init__(self):
        self.writes = 0

    async def execute(self, stmt, params=None):
        sql = " ".join(str(stmt).split())
        if sql.startswith("UPDATE"):
            self.writes += 1
            return _Result(rowcount=3)
        if "count(*)" in sql:
            return _Result(scalar=2)
        return _Result(rows=[{"id": 1, "backend": "mock", "handle": "mock-1", "status": "leased",
                              "leased_by": "pfs_x", "last_seen_at": None}])

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def wired(monkeypatch):
    state = {"scopes": ["*"], "dev": _admin()}

    async def _dev(*a, **k):
        return state["dev"]

    async def _row(*a, **k):
        return SimpleNamespace(id=42, scopes=state["scopes"])
    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _dev)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _dev)
    monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _row)
    session = _Session()
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(phone_fabric.router)
    app.dependency_overrides[get_db] = lambda: session
    return state, session, TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("scopes,want", [
    (["*"], 200),                  # control: a full key of an admin account
    (["read:public"], 403),        # BASE: 200 (a narrow key of an admin account read the pool)
])
def test_the_pool_asks_the_presented_key(wired, scopes, want):
    state, _session, client = wired
    state["scopes"] = scopes
    r = client.get("/api/v1/admin/phone/pool", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == want, (scopes, r.status_code, r.text)


def test_a_session_without_the_required_second_factor_is_no_admin(wired, monkeypatch):
    state, _session, client = wired
    state["dev"] = _admin(two_fa=False)
    token = security.create_access_token({"sub": "7"})
    monkeypatch.setattr(security.settings, "REQUIRE_ADMIN_2FA", False, raising=False)
    assert client.get("/api/v1/admin/phone/pool", headers={"Authorization": f"Bearer {token}"}).status_code == 200  # control
    monkeypatch.setattr(security.settings, "REQUIRE_ADMIN_2FA", True, raising=False)
    r = client.get("/api/v1/admin/phone/pool", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403, r.text   # BASE: 200


def test_the_global_halt_halts_nothing_for_a_narrow_key(wired):
    state, session, client = wired
    state["scopes"] = ["read:public"]
    r = client.post("/api/v1/admin/phone/global-halt", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 403 and session.writes == 0, (r.status_code, r.text, session.writes)   # BASE: 200, 2 writes
    state["scopes"] = ["*"]
    r = client.post("/api/v1/admin/phone/global-halt", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 200 and r.json()["halted"] == 3 and session.writes == 2   # control
