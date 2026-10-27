"""D6-621 (2026-10-16): with REQUIRE_ADMIN_2FA on, no credential carries admin authority for an account without 2FA.

The rule was enforced only at the password login. An API key carrying the account's admin flags (a '*' key, an MCP OAuth
'mcp:admin' key, a CLI or bridge key), a session that outlived a 2FA disable, and the MCP bridge's own admin flag all
reached admin authority without it. The rule now lives where admin authority is used (security.admin_second_factor_ok):
require_admin_flag, admin_credential and the sites built on api_key_grants_admin, the MCP bridge, the websocket's admin
role. Non-admin use of a key is unaffected, and with the flag off nothing changes. Each case marked BASE fails on 14520b9f.

Through FastAPI on real routes (GET /admin/invite-codes, GET /auth/2fa/status, POST /mcp/rpc); only the database is
replaced (the key, developer and token_version lookups, the invite list).
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.config import settings
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers

KEY = "avreg_" + "q" * 43


def _dev(*, admin=True, support=False, two_fa=False):
    return SimpleNamespace(id=7, email="a@example.test", name="A", is_admin=admin, admin_support=support,
                           admin_treasury=False, admin_enforcement=False, admin_federation=False, admin_platform=False,
                           must_change_password=False, is_suspended=False, deleted_at=None, deletion_status=None,
                           two_fa_enabled=two_fa, is_verified=True, token_version=0, backup_codes=None,
                           two_fa_verified_at=None, organization_memberships=[])


class _Result:
    def scalar_one_or_none(self):
        return 0   # the developer's token_version


class _Session:
    async def execute(self, *a, **k):
        return _Result()

    async def commit(self):
        pass

    async def rollback(self):
        pass


@pytest.fixture()
def rig(monkeypatch):
    state = SimpleNamespace(dev=_dev(), scopes=["*"])

    async def _by_key(*a, **k):
        return state.dev

    async def _row(*a, **k):
        return SimpleNamespace(id=42, scopes=state.scopes)
    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _by_key)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _by_key)
    monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _row)
    monkeypatch.setattr(settings, "REQUIRE_ADMIN_2FA", True)

    from agentvault_registry.routers import admin_invite_codes as AIC
    from agentvault_registry.routers import auth_2fa

    async def _none(*a, **k):
        return []
    monkeypatch.setattr(AIC, "list_invite_codes", _none)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(AIC.router)
    app.include_router(auth_2fa.router)
    app.dependency_overrides[get_db] = lambda: _Session()
    state.client = TestClient(app, raise_server_exceptions=False)
    return state


def _admin_route(rig, bearer):
    return rig.client.get("/admin/invite-codes", headers={"Authorization": f"Bearer {bearer}"}).status_code


SESSION = lambda: security.create_access_token({"sub": "7"}, token_version=0)   # noqa: E731


def test_a_full_api_key_of_an_admin_without_2fa_is_refused(rig):   # BASE: 200
    assert _admin_route(rig, KEY) == 403


def test_an_mcp_oauth_admin_key_of_an_admin_without_2fa_is_refused(rig):   # BASE: 200
    rig.scopes = ["mcp:admin", "mcp:tools"]
    # D6-514: an MCP key reaches a REST admin route only through MCP's relay; there the second factor still binds it
    r = rig.client.get("/admin/invite-codes", headers={"Authorization": f"Bearer {KEY}",
                                                      security.MCP_RELAY_HEADER: security.mcp_relay_proof(KEY)})
    assert r.status_code == 403 and "two-factor" in r.text, r.text


def test_a_session_of_an_admin_without_2fa_is_refused(rig):   # BASE: 200 (e.g. 2FA disabled after the login)
    assert _admin_route(rig, SESSION()) == 403


def test_a_sub_admins_key_without_2fa_is_refused(rig):   # BASE: 200
    rig.dev = _dev(admin=False, support=True)
    assert _admin_route(rig, KEY) == 403


def test_the_refusal_names_the_second_factor(rig):
    r = rig.client.get("/admin/invite-codes", headers={"Authorization": f"Bearer {KEY}"})
    assert "two-factor" in r.json().get("detail", "") or "two-factor" in r.text


def test_control_an_admin_with_2fa_passes_on_a_key_and_a_session(rig):
    rig.dev = _dev(two_fa=True)
    assert _admin_route(rig, KEY) == 200 and _admin_route(rig, SESSION()) == 200


def test_control_with_the_flag_off_nothing_changes(rig, monkeypatch):
    monkeypatch.setattr(settings, "REQUIRE_ADMIN_2FA", False)
    assert _admin_route(rig, KEY) == 200 and _admin_route(rig, SESSION()) == 200


def test_control_non_admin_use_of_the_key_is_untouched(rig):
    r = rig.client.get("/auth/2fa/status", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 200, r.text


def test_control_a_non_admin_is_refused_for_the_flag_not_the_factor(rig):
    rig.dev = _dev(admin=False)
    r = rig.client.get("/admin/invite-codes", headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 403 and "Admin flag required" in r.text


# ── the MCP bridge's admin flag, through POST /mcp/rpc ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("two_fa,bearer,want", [
    (False, KEY, False),        # BASE: True
    (False, "session", False),  # BASE: True
    (True, KEY, True),          # control
    (True, "session", True),    # control
])
def test_the_mcp_bridge_admin_flag(rig, monkeypatch, two_fa, bearer, want):
    from agentvault_registry.mcp import server as S
    rig.dev = _dev(two_fa=two_fa)
    tool = "theprotocol_getMyDeveloperProfile"

    async def _who(ctx, **kw):
        return {"is_admin": ctx.is_admin}
    monkeypatch.setitem(S.TOOL_DISPATCH, tool, _who)

    @contextlib.asynccontextmanager
    async def _db():
        yield _Session()
    monkeypatch.setattr(S, "get_db_context", _db)
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(S.router, prefix="/mcp")
    tok = SESSION() if bearer == "session" else bearer
    r = TestClient(app, raise_server_exceptions=False).post(
        "/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": {}}},
        headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["result"]["structuredContent"]["is_admin"] is want


# ── the other readers of admin authority ─────────────────────────────────────────────────────────────────────────────
def test_the_other_admin_readers_follow_the_rule(rig):   # BASE: each one True
    from agentvault_registry.routers import fiat_onramp, frame_invitations, websocket
    dev = _dev()
    assert security.admin_credential(dev) is False
    assert fiat_onramp._is_admin_developer(dev) is False
    assert frame_invitations._may_name_internal_bundle(dev) is False
    ud = websocket._build_user_data(dev)
    assert ud["is_admin"] is False and ud["role"] == "developer"
    ok = _dev(two_fa=True)   # control
    assert security.admin_credential(ok) and fiat_onramp._is_admin_developer(ok)
    assert frame_invitations._may_name_internal_bundle(ok) and websocket._build_user_data(ok)["is_admin"] is True
