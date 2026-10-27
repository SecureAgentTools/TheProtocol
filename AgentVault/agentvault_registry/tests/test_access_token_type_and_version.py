"""D6-731 (2026-10-16): every developer-token verifier asks one rule: an ACCESS token, with a current token_version.

The MCP auth bridge's developer-JWT path and get_current_developer_unified checked neither the token type nor the
token_version, so a refresh token or a logged-out token was a session there. And every verifier refused only the purpose
"password-set": the 2FA login's partial token (signed with the same key, handed out after the password and BEFORE the
code) was read as a full session, so the second factor could be skipped. One helper pair in security.py now answers for
all of them (access_token_subject, token_version_current). Each test marked BASE fails on 14520b9f.

Through FastAPI on real routes; only the database (the token_version read, the developer row) is replaced.
"""
from __future__ import annotations

import contextlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import developer as developer_crud
from agentvault_registry.database import get_db
from agentvault_registry.errors import register_error_handlers
from agentvault_registry.services import TwoFactorAuthService

DEV_ID = 7
CURRENT_TV = 3


class _Result:
    def __init__(self, value):
        self._v = value

    def scalar_one_or_none(self):
        return self._v


class _Session:
    """Answers the token_version read with the developer's current value."""

    def __init__(self):
        self.reads = 0

    async def execute(self, *a, **k):
        self.reads += 1
        return _Result(CURRENT_TV)

    async def commit(self):
        pass

    async def rollback(self):
        pass

    async def close(self):
        pass


def _dev():
    return SimpleNamespace(id=DEV_ID, email="dev@example.test", name="Dev", is_admin=False, is_verified=False,
                           is_suspended=False, deleted_at=None, deletion_status=None, two_fa_enabled=False,
                           backup_codes=None, two_fa_verified_at=None, token_version=CURRENT_TV,
                           must_change_password=False)


TOKENS = {
    "access": lambda: security.create_access_token({"sub": str(DEV_ID)}, token_version=CURRENT_TV),
    "access_without_tv": lambda: security.create_access_token({"sub": str(DEV_ID)}),
    "logged_out": lambda: security.create_access_token({"sub": str(DEV_ID)}, token_version=CURRENT_TV - 1),
    "refresh": lambda: security.create_refresh_token(DEV_ID, token_version=CURRENT_TV),
    "partial_2fa": lambda: TwoFactorAuthService.generate_partial_token(DEV_ID),
    "password_set": lambda: security.create_access_token({"sub": str(DEV_ID), "purpose": "password-set"}),
}


@pytest.fixture()
def lookups(monkeypatch):
    async def _row(*a, **k):
        return _dev()
    for name in ("get_developer_by_id_strict", "get_developer_by_id_lean"):
        monkeypatch.setattr(developer_crud, name, _row)


def _app(*routers, prefix=""):
    app = FastAPI()
    register_error_handlers(app)
    for r in routers:
        app.include_router(r, prefix=prefix)
    app.dependency_overrides[get_db] = lambda: _Session()
    return TestClient(app, raise_server_exceptions=False)


# ── the required verifier (get_current_developer → verify_access_token_required), on GET /auth/2fa/status ───────────
@pytest.mark.parametrize("kind,want", [
    ("access", 200), ("access_without_tv", 200),                      # controls
    ("logged_out", 401), ("refresh", 401), ("password_set", 401),     # refused on the base too (controls)
    ("partial_2fa", 401),                                             # BASE: 200 (the second factor skipped)
])
def test_the_required_verifier(lookups, kind, want):
    from agentvault_registry.routers import auth_2fa
    r = _app(auth_2fa.router).get("/auth/2fa/status", headers={"Authorization": f"Bearer {TOKENS[kind]()}"})
    assert r.status_code == want, (kind, r.status_code, r.text)


# ── the unified dependency, on POST /onboard/bootstrap/request-token (403 = admitted: the developer is unverified) ──
@pytest.mark.parametrize("kind,want", [
    ("access", 403), ("access_without_tv", 403),   # controls: admitted, then refused as unverified
    ("password_set", 401),                         # control
    ("logged_out", 401),                           # BASE: 403 (admitted)
    ("refresh", 401),                              # BASE: 403
    ("partial_2fa", 401),                          # BASE: 403
])
def test_the_unified_dependency(lookups, kind, want):
    from agentvault_registry.routers import onboarding
    r = _app(onboarding.router).post("/onboard/bootstrap/request-token", json={},
                                     headers={"Authorization": f"Bearer {TOKENS[kind]()}"})
    assert r.status_code == want, (kind, r.status_code, r.text)


# ── the MCP auth bridge, through POST /mcp/rpc: a developer-tier tool reports the context it was handed (a tool's own
#    require_developer_auth refuses an anonymous one; the stub reports it instead) ─────────────────────────────────────
@pytest.fixture()
def mcp(monkeypatch, lookups):
    from agentvault_registry.mcp import server as S
    tool = "theprotocol_getMyDeveloperProfile"
    assert tool in S.AUTH_REQUIRED_TOOLS

    async def _who(ctx, **kw):
        return {"auth_type": ctx.auth_type, "developer_id": ctx.developer_id}
    monkeypatch.setitem(S.TOOL_DISPATCH, tool, _who)

    @contextlib.asynccontextmanager
    async def _db():
        yield _Session()
    monkeypatch.setattr(S, "get_db_context", _db)
    client = _app(S.router, prefix="/mcp")

    def call(token):
        r = client.post("/mcp/rpc", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                          "params": {"name": tool, "arguments": {}}},
                        headers={"Authorization": f"Bearer {token}"})
        body = r.json()
        return ((body.get("result") or {}).get("structuredContent") or {}).get("auth_type")
    return call


@pytest.mark.parametrize("kind,want", [
    ("access", "developer"), ("access_without_tv", "developer"),   # controls
    ("password_set", "anonymous"),                                # control
    ("logged_out", "anonymous"),                                  # BASE: developer
    ("refresh", "anonymous"),                                     # BASE: developer
    ("partial_2fa", "anonymous"),                                 # BASE: developer
])
def test_the_mcp_bridge(mcp, kind, want):
    assert mcp(TOKENS[kind]()) == want, kind


def test_one_rule_for_every_verifier():
    import inspect
    from agentvault_registry.mcp import auth_bridge
    src = inspect.getsource(auth_bridge._authenticate_mcp_token)
    assert "access_token_subject" in src and "token_version_current" in src
    for fn in (security.verify_access_token_required, security.verify_access_token_optional_claims,
               security.get_current_developer_unified):
        assert "access_token_subject" in inspect.getsource(fn), fn.__name__
