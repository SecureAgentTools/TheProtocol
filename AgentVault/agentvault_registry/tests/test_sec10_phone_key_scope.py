"""SEC-10 (2026-10-17): a paired phone's key holds a scope of its own; 'mcp:tools' no longer registers a push device.

D6-514 let a key scoped to MCP reach one REST route directly, the paired phone's push registration (POST
/api/v1/devices/register), because a phone's key held 'mcp:tools'. Any MCP credential holds it too, so an MCP OAuth
connector's key could register a push device on the account directly and receive the account's notifications. Now the
phone's own scope 'pocket:device' names that route, and the console pairs a phone with ['mcp:tools', 'pocket:device'];
'mcp:tools' reaches nothing directly, and 'pocket:device' alone reaches only that route and is not an MCP credential. A
phone paired before (its key ['mcp:tools'] alone, under the console's name "POCKET FRAME: <label>") keeps its push
registration until it is paired again or its key expires.

Through FastAPI on real routes (POST /api/v1/devices/register, GET /api/v1/auth/api-keys, POST /mcp/rpc relaying to GET
/api/v1/auth/api-keys in process); only the database (the key and developer lookups, the key list) is replaced. Each
case marked BASE answers otherwise on 453cc8b8 (its security.py and mcp/auth_bridge.py mounted).
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers

KEY = "avreg_" + "p" * 43
PHONE = ["mcp:tools", "pocket:device"]


def _dev():
    return SimpleNamespace(id=7, email="d@example.test", name="D", is_admin=False, admin_support=False,
                           admin_treasury=False, admin_enforcement=False, admin_federation=False, admin_platform=False,
                           must_change_password=False, is_suspended=False, deleted_at=None, deletion_status=None,
                           two_fa_enabled=False, is_verified=True, token_version=0, hashed_password="x")


class _Session:
    async def execute(self, *a, **k):    # the key list: none
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def rig(monkeypatch):
    state = SimpleNamespace(scopes=PHONE, name="POCKET FRAME: Pixel 9")

    async def _by_key(*a, **k):
        return _dev()

    async def _row(*a, **k):
        return SimpleNamespace(id=42, scopes=state.scopes, description=state.name)
    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _by_key)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _by_key)
    monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _row)

    from agentvault_registry.mcp import server as S
    from agentvault_registry.routers import auth_secure, device_push
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_secure.router, prefix="/api/v1")
    app.include_router(device_push.router)
    app.include_router(S.router, prefix="/mcp")
    app.dependency_overrides[get_db] = lambda: _Session()
    state.app, state.client = app, TestClient(app, raise_server_exceptions=False)
    return state


def _register(rig):
    # an invalid rail: 422 from the route's own check = the key reached the route; 403 = refused at the credential
    return rig.client.post("/api/v1/devices/register", json={"platform": "android", "rail": "pigeon", "target": "x"},
                           headers={"Authorization": f"Bearer {KEY}"})


def _reached(r):
    return r.status_code == 422 and "rail must be one of" in r.text


@pytest.mark.parametrize("scopes,name,reaches", [
    (PHONE, "POCKET FRAME: Pixel 9", True),                     # control: a phone paired now
    (["pocket:device"], "my phone", True),                      # control: the phone's scope alone
    (["mcp:tools"], "POCKET FRAME: Pixel 7", True),             # a phone paired before SEC-10 keeps it
    (["*"], "full", True),                                      # control
    (["mcp:tools"], "MCP OAuth (Claude)", False),               # BASE: reached (an MCP connector's key)
    (["mcp:admin", "mcp:tools"], "MCP OAuth (Claude)", False),  # BASE: reached
    (["mcp:tools"], "my script", False),                        # BASE: reached
    (["mcp:tools", "keys:manage"], "POCKET FRAME: x", False),   # BASE: reached; not the console's pairing scopes
])
def test_who_registers_a_push_device_directly(rig, scopes, name, reaches):
    rig.scopes, rig.name = scopes, name
    r = _register(rig)
    assert _reached(r) is reaches, (scopes, name, r.status_code, r.text)
    if not reaches:
        assert r.status_code == 403 and "scoped to MCP" in r.text


def test_the_phones_scope_reaches_nothing_else_directly(rig):
    rig.scopes, rig.name = ["pocket:device"], "my phone"
    r = rig.client.get("/api/v1/auth/api-keys", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 403, (r.status_code, r.text)            # BASE: 200 (no MCP scope: it kept full reach)
    assert "paired phone" in r.text and "devices/register" in r.text
    rig.scopes = PHONE
    r = rig.client.get("/api/v1/auth/api-keys", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 403 and "scoped to MCP" in r.text       # control: the phone's key, presented directly


def _routed_through(monkeypatch, app):
    original = httpx.AsyncClient

    class _Routed(original):
        def __init__(self, *a, **kw):
            kw["transport"] = httpx.ASGITransport(app=app)
            super().__init__(*a, **kw)
    monkeypatch.setattr(httpx, "AsyncClient", _Routed)


def _mcp_keys(rig, monkeypatch):
    from agentvault_registry.mcp import server as S

    @contextlib.asynccontextmanager
    async def _db():
        yield _Session()
    monkeypatch.setattr(S, "get_db_context", _db)
    _routed_through(monkeypatch, rig.app)
    return rig.client.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                             "params": {"name": "theprotocol_getMyApiKeys", "arguments": {}}},
                           headers={"Authorization": f"Bearer {KEY}"}).json()


def test_a_paired_phones_key_still_drives_the_mcp_tools(rig, monkeypatch):
    body = _mcp_keys(rig, monkeypatch)
    out = (body.get("result") or {}).get("structuredContent") or body
    assert out.get("api_keys") == [] and not out.get("error"), body              # control, both trees


def test_the_phones_scope_alone_is_not_an_mcp_credential(rig, monkeypatch):
    rig.scopes, rig.name = ["pocket:device"], "my phone"
    body = _mcp_keys(rig, monkeypatch)
    result = body.get("result") or {}
    assert body.get("error") or result.get("isError"), body                      # BASE: the tool ran as the developer
    assert (result.get("structuredContent") or {}).get("api_keys") is None, body


def test_the_effective_scopes_rule():
    assert security.effective_key_scopes(["mcp:tools"], "POCKET FRAME: Pixel 7") == PHONE
    assert security.effective_key_scopes(["mcp:tools"], "MCP OAuth (Claude)") == ["mcp:tools"]
    assert security.effective_key_scopes(["mcp:tools"], None) == ["mcp:tools"]
    assert security.effective_key_scopes(PHONE, "POCKET FRAME: Pixel 9") == PHONE
    assert security.key_reaches_mcp(["*"]) and security.key_reaches_mcp(["keys:manage"])
    assert security.key_reaches_mcp(PHONE) and security.key_reaches_mcp([])
    assert not security.key_reaches_mcp(["pocket:device"])
