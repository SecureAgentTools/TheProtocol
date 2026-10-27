"""D6-514 (2026-10-16): a key scoped to MCP reaches the REST API only through MCP (and a paired phone's push route).

A paired phone's key carries the scope 'mcp:tools' (§POCKETPAIR), as an MCP OAuth client's does: the scope that names the
public MCP tools. It narrowed only the admin gates and key minting; presented to any other REST route directly it carried
the account's whole developer authority (list and revoke keys, reset an agent's credentials, every developer route).
Now a key holding an MCP scope ('mcp:tools' or 'mcp:admin', and not '*') reaches a REST route when the registry's own
MCP server relays the call (the X-MCP-Relay proof, an HMAC of the key under API_KEY_SECRET that the tools' httpx
client adds: mcp/auth_bridge.mcp_http_client), or when its scope names the route for direct use (POST
/api/v1/devices/register, the paired phone's push registration). Everything else answers 403. Keys without an MCP
scope keep their reach. Each case marked BASE fails on 7140a4a6.

Corrected for SEC-10 (2026-10-17): the push registration's direct allowance belongs to the phone's own scope
'pocket:device' (a phone is paired with ['mcp:tools', 'pocket:device']), no longer to 'mcp:tools', which every MCP
OAuth connector's key holds too (tests/test_sec10_phone_key_scope.py).

Through FastAPI on real routes (GET /api/v1/auth/api-keys, POST /api/v1/devices/register, POST
/api/v1/onboard/agents/{did}/reset-credentials over X-Api-Key, and POST /mcp/rpc relaying to GET /api/v1/auth/api-keys
in-process); only the database (the key and developer lookups, the key list) is replaced.
"""
from __future__ import annotations

import ast
import contextlib
import pathlib
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers

KEY = "avreg_" + "m" * 43
OTHER_KEY = "avreg_" + "n" * 43
SRC = pathlib.Path(security.__file__).resolve().parent


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
    state = SimpleNamespace(scopes=["mcp:tools"])

    async def _by_key(*a, **k):
        return _dev()

    async def _row(*a, **k):
        return SimpleNamespace(id=42, scopes=state.scopes)
    monkeypatch.setattr(developer_crud, "get_developer_by_plain_api_key", _by_key)
    monkeypatch.setattr(developer_crud, "get_developer_by_id_strict", _by_key)
    monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _row)

    from agentvault_registry.mcp import server as S
    from agentvault_registry.routers import auth_secure, device_push, onboarding
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(auth_secure.router, prefix="/api/v1")
    app.include_router(device_push.router)
    app.include_router(onboarding.router, prefix="/api/v1")
    app.include_router(S.router, prefix="/mcp")
    app.dependency_overrides[get_db] = lambda: _Session()
    state.app, state.client = app, TestClient(app, raise_server_exceptions=False)
    return state


def _keys(rig, key=KEY, **headers):
    return rig.client.get("/api/v1/auth/api-keys", headers={"Authorization": f"Bearer {key}", **headers})


@pytest.mark.parametrize("scopes,want", [
    (["*"], 200),                          # control: a full key
    (["read:public"], 200),                # control: a key without an MCP scope keeps its reach
    (["keys:manage"], 200),                # control
    (["mcp:tools"], 403),                  # BASE: 200 (a paired phone's key listed the account's keys)
    (["mcp:admin", "mcp:tools"], 403),     # BASE: 200 (an MCP OAuth admin key, presented directly)
    (["mcp:tools", "read:public"], 403),   # BASE: 200
])
def test_a_direct_call_reaches_what_the_scope_allows(rig, scopes, want):
    rig.scopes = scopes
    r = _keys(rig)
    assert r.status_code == want, (scopes, r.status_code, r.text)
    if want == 403:
        assert "scoped to MCP" in r.text


def test_the_relay_proof_is_the_mcp_servers_and_names_one_key(rig):
    assert _keys(rig, **{security.MCP_RELAY_HEADER: security.mcp_relay_proof(KEY)}).status_code == 200    # control
    assert _keys(rig, **{security.MCP_RELAY_HEADER: security.mcp_relay_proof(OTHER_KEY)}).status_code == 403
    assert _keys(rig, **{security.MCP_RELAY_HEADER: "0" * 64}).status_code == 403


def test_a_paired_phone_still_registers_its_push_device(rig):
    # 422 from the route's own rail check = past the credential (the handler ran); 403 = refused at the credential
    rig.scopes = ["mcp:tools", "pocket:device"]   # SEC-10: the phone's own scope carries the push registration
    r = rig.client.post("/api/v1/devices/register", json={"platform": "android", "rail": "pigeon", "target": "x"},
                        headers={"Authorization": f"Bearer {KEY}"})
    assert r.status_code == 422 and "rail must be one of" in r.text, r.text      # control, both trees


def test_the_x_api_key_path_holds_the_same_rule(rig):
    # an invalid body: 422 when the key reaches the route, 403 when it is refused before
    def reset(scopes):
        rig.scopes = scopes
        return rig.client.post("/api/v1/onboard/agents/did:theprotocol:test:x/reset-credentials", json={},
                               headers={"X-Api-Key": KEY}).status_code
    assert reset(["*"]) == 422                 # control
    assert reset(["mcp:tools"]) == 403         # BASE: 422 (a phone's key reached the credential reset)


def test_an_unreadable_scope_reaches_nothing(rig, monkeypatch):
    async def _gone(*a, **k):
        return None
    monkeypatch.setattr(developer_crud, "get_api_key_row_by_plain_key", _gone)
    assert _keys(rig).status_code == 403       # BASE: 200 (D6-715 left it the non-admin routes)


def _routed_through(monkeypatch, app):
    """A tool's call to this registry lands on the test app, in process (the registry's loopback, in miniature)."""
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
    body = rig.client.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                             "params": {"name": "theprotocol_getMyApiKeys", "arguments": {}}},
                           headers={"Authorization": f"Bearer {KEY}"}).json()
    return (body.get("result") or {}).get("structuredContent") or body


def test_the_public_tools_still_work_for_an_mcp_key(rig, monkeypatch):
    _routed_through(monkeypatch, rig.app)
    out = _mcp_keys(rig, monkeypatch)
    assert out.get("api_keys") == [] and not out.get("error"), out          # control, both trees


def test_without_the_relay_proof_the_tools_would_be_refused(rig, monkeypatch):
    from agentvault_registry.mcp import auth_bridge

    async def _no_proof(request):
        return None
    monkeypatch.setattr(auth_bridge, "_add_mcp_relay_proof", _no_proof)
    _routed_through(monkeypatch, rig.app)
    out = _mcp_keys(rig, monkeypatch)
    text = " ".join(c.get("text", "") for c in ((out.get("result") or {}).get("content") or []))
    assert (out.get("result") or {}).get("isError") and "403" in text, out   # the hook is what carries an MCP key


async def test_the_hook_adds_the_proof_only_for_a_key_on_this_registry():
    from agentvault_registry.mcp.auth_bridge import mcp_http_client
    seen = []

    def _record(request):
        seen.append(request.headers.get(security.MCP_RELAY_HEADER))
        return httpx.Response(200, json={})
    async with mcp_http_client(transport=httpx.MockTransport(_record)) as c:
        await c.get("http://localhost:8000/api/v1/x", headers={"Authorization": f"Bearer {KEY}"})
        await c.get("http://localhost:8000/api/v1/x", headers={"Authorization": "Bearer eyJ.a.b"})
        await c.get("https://elsewhere.example/api/v1/x", headers={"Authorization": f"Bearer {KEY}"})
        await c.get("http://localhost:8000/api/v1/x")
    assert seen == [security.mcp_relay_proof(KEY), None, None, None]


def test_every_tool_module_builds_its_clients_with_the_hook():
    for rel in ("mcp/tools_agent.py", "mcp/tools_developer.py", "mcp/tools_discovery.py", "mcp/tools_commons.py",
                "mcp/tools_guild.py"):
        tree = ast.parse((SRC / rel).read_text())
        raw = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "AsyncClient" and getattr(n.func.value, "id", "") == "httpx"]
        assert not raw, f"{rel}: httpx.AsyncClient at lines {raw}: a call to this registry would carry no relay proof"
