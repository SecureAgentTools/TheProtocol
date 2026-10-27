"""D6-715 (2026-10-16): an API key whose scopes cannot be read carries no scope, never full authority.

The lookup that publishes the presented key's scopes (security._publish_presented_key) read a failed lookup, and a row
it could not find, as ['*']: a narrow key (a paired phone's 'mcp:tools', an MCP OAuth client's) whose lookup failed held
full authority for that request, the admin gates and the key-mint gate included. The crud lookup under it swallowed a
database error to None, which became the same ['*']. The key-mint gate of /auth/api-keys and the MCP bridge's admin flag
each had their own copy of the same fail-open lookup. One helper now answers for all three (security.presented_key_scopes):
an unreadable row is no scope, a database error is 503. Each case marked BASE fails on 14520b9f.

Through FastAPI on real routes (GET /admin/invite-codes, POST /auth/api-keys, POST /mcp/rpc); only the database is
replaced (the key and developer lookups, the invite list).
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers

KEY = "avreg_" + "k" * 43
DB_DOWN = OperationalError("SELECT developer_api_keys.id ...", {}, Exception("too many clients already"))


def _admin():
    return SimpleNamespace(id=7, email="admin@example.test", name="Admin", is_admin=True, admin_support=False,
                           admin_treasury=False, admin_enforcement=False, admin_federation=False, admin_platform=False,
                           must_change_password=False, is_suspended=False, deleted_at=None, deletion_status=None,
                           two_fa_enabled=True, is_verified=True, token_version=0)


class _Session:
    def __init__(self, refuse=False):
        self.refuse = refuse

    async def execute(self, *a, **k):
        if self.refuse:
            raise DB_DOWN
        raise AssertionError("no statement expected")

    async def commit(self):
        pass

    async def rollback(self):
        pass


def _row_behaviour(kind):
    """How the key's row lookup answers: a row with scopes, None (gone), or an error."""
    async def _row(*a, **k):
        if kind == "error":
            raise RuntimeError("lookup broke")
        if kind == "db_down":
            raise DB_DOWN
        if kind == "gone":
            return None
        return SimpleNamespace(id=42, scopes=kind)
    return _row


@pytest.fixture()
def patch_lookups(monkeypatch):
    async def _dev(*a, **k):
        return _admin()
    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _dev)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _dev)

    def apply(kind):
        if kind == "real":   # the real crud lookup runs, against a database that refuses
            return _Session(refuse=True)
        monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _row_behaviour(kind))
        return _Session()
    return apply


def _client(router, session, prefix=""):
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router, prefix=prefix)
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app, raise_server_exceptions=False)


# ── an admin gate (require_admin_flag), on GET /admin/invite-codes ───────────────────────────────────────────────────
@pytest.mark.parametrize("kind,want", [
    (["*"], 200), (None, 200), (["mcp:admin", "mcp:tools"], 200),   # controls: full or admin scope
    (["mcp:tools"], 403),                                          # control: narrow
    ("error", 403),                                                # BASE: 200 (read as '*')
    ("gone", 403),                                                 # BASE: 200
    ("db_down", 503),                                              # BASE: 200
    ("real", 503),                                                 # BASE: 200 (the crud swallowed the error)
])
def test_the_admin_gate(monkeypatch, patch_lookups, kind, want):
    from agentvault_registry import security
    from agentvault_registry.routers import admin_invite_codes as AIC

    async def _none(*a, **k):
        return []
    monkeypatch.setattr(AIC, "list_invite_codes", _none)
    # D6-514: a key scoped to MCP reaches a REST route only through MCP's relay, so every key here arrives that way
    # (the relay proof is inert for a key without an MCP scope); this test is about the scope LOOKUP, not the reach.
    r = _client(AIC.router, patch_lookups(kind)).get("/admin/invite-codes", headers={
        "Authorization": f"Bearer {KEY}", security.MCP_RELAY_HEADER: security.mcp_relay_proof(KEY)})
    assert r.status_code == want, (kind, r.status_code, r.text)


# ── the key-mint gate, on POST /auth/api-keys (418 = past the gate, at the mint itself) ──────────────────────────────
@pytest.mark.parametrize("kind,want", [
    (["*"], 418),                           # control: a full key mints
    (["keys:manage"], 418),                 # control: a 'keys:manage' key mints a key inside its own scopes
    (["mcp:tools"], 403),                   # control: a narrow key is refused
    ("error", 403),                         # BASE: 418 (read as '*')
    ("gone", 403),                          # BASE: 418
])
def test_the_mint_gate(monkeypatch, patch_lookups, kind, want):
    from agentvault_registry.routers import auth_secure

    async def _reached(*a, **k):
        raise HTTPException(status_code=418, detail="reached the mint")
    monkeypatch.setattr(auth_secure.developer_crud, "create_api_key", _reached)
    body = {"key_name": "x", "scopes": ["keys:manage"]} if kind == ["keys:manage"] else "my key"
    r = _client(auth_secure.router, patch_lookups(kind)).post(
        "/auth/api-keys", json=body, headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == want, (kind, r.status_code, r.text)


# ── the MCP bridge's admin flag, through POST /mcp/rpc ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("kind,want", [
    (["*"], True), (["mcp:tools"], False),   # controls
    ("error", False),                        # BASE: True (is_admin left as it was)
    ("gone", False),                         # BASE: True
    ("db_down", "unavailable"),              # BASE: True
])
def test_the_mcp_bridge_admin_flag(monkeypatch, patch_lookups, kind, want):
    from agentvault_registry.mcp import server as S
    tool = "theprotocol_getMyDeveloperProfile"

    async def _who(ctx, **kw):
        return {"auth_type": ctx.auth_type, "is_admin": ctx.is_admin}
    monkeypatch.setitem(S.TOOL_DISPATCH, tool, _who)
    session = patch_lookups(kind)

    @contextlib.asynccontextmanager
    async def _db():
        yield session
    monkeypatch.setattr(S, "get_db_context", _db)
    r = _client(S.router, session, prefix="/mcp").post(
        "/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {}}},
        headers={"Authorization": f"Bearer {KEY}"})
    body = r.json()
    if (body.get("error") or {}).get("code") == -32003:
        got = "unavailable"
    else:
        got = body["result"]["structuredContent"]["is_admin"]
    assert got == want, (kind, body)
