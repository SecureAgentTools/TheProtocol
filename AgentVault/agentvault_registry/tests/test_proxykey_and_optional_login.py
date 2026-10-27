"""§PROXYKEY 2026-09-11 — his decisions 2 and 10, each pinned both ways.

10a. The api-tester's shared proxy key has ONE reader, NO literal default, and is refused by
     SHAPE. Measured live before the change: the variable was unset on every node, so the
     source literal was the key everywhere, and on EU (execution on, public API hosts) and two
     operators it let anyone who read the source start tester runs without logging in.
10b. `get_current_developer_optional` refuses what `get_current_developer` refuses: a revoked
     token (token_version moved on), a suspended, deleted or anonymized account, and a REFRESH
     token. It is the admin gate of the api-tester router, so each of those kept admin access
     there (a refresh token for seven days).
10c. An operator no longer inherits the tester switch from its parent (it is a role, not posture).
2.   An enforcement action records the policy version `frame_policy.load()` reports: 0 for the
     factory default. The old fallback of 1 was also the first stored row's version.

RED on the pre-change tree: the source gates, the optional-login behaviour tests, the posture
test and the policy-version gate (the unit tests of the new module fail there at import).
"""
from __future__ import annotations

import ast
import pathlib
import types

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from agentvault_registry import security
from agentvault_registry.crud import crud_enforcement as ce

SRC = pathlib.Path(security.__file__).resolve().parent
STRONG = "k" * 20 + "Q9_x-" + "z" * 18          # 43 chars, the shape token_urlsafe(32) produces
SHORT = "short-key-of-thirty-characters"          # 30 chars: under the minimum


# ── 10a. the shared proxy key ───────────────────────────────────────────────────────────────────

def _getenv_defaults(path: pathlib.Path, name: str):
    """Every literal default passed to os.getenv(name, <default>) / os.environ.get(name, <default>)."""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("getenv", "get") and len(node.args) >= 2
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == name
                and isinstance(node.args[1], ast.Constant)):
            out.append(node.args[1].value)
    return out


@pytest.mark.parametrize("rel", ["routers/admin_api_test.py", "routers/mcp_tester.py"])
def test_no_router_carries_a_default_for_the_proxy_key(rel):
    defaults = _getenv_defaults(SRC / rel, "API_TEST_PROXY_INTERNAL_KEY")
    assert all(d in ("", None) for d in defaults), f"{rel} still defaults the key: {len(defaults)} site(s)"
    assert "_PROXY_INTERNAL_KEY =" not in (SRC / rel).read_text(encoding="utf-8")


def test_the_detector_can_see_a_default():
    # control: the detector finds a literal default where one exists
    tree = SRC / "routers" / "mcp_tester.py"
    assert "5400" in _getenv_defaults(tree, "MCP_TESTER_SWEEP_TIMEOUT_S")


def test_unset_means_closed(monkeypatch):
    from agentvault_registry.core import api_test_proxy_key as pk
    monkeypatch.delenv("API_TEST_PROXY_INTERNAL_KEY", raising=False)
    assert pk.configured_key() == ""
    assert pk.presented_key_ok(STRONG) is False
    assert pk.presented_key_ok("") is False
    assert pk.proxy_headers() == {}


@pytest.mark.parametrize("bad", [SHORT, "x" * 40 + "changeme", "  "])
def test_a_key_that_is_not_a_secret_is_refused_by_shape(monkeypatch, bad):
    from agentvault_registry.core import api_test_proxy_key as pk
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", bad)
    assert pk.configured_key() == ""
    assert pk.presented_key_ok(bad) is False
    assert pk.proxy_headers() == {}


def test_a_strong_key_is_accepted_only_exactly(monkeypatch):
    from agentvault_registry.core import api_test_proxy_key as pk
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", STRONG)
    assert pk.presented_key_ok(STRONG) is True
    assert pk.presented_key_ok(STRONG + "x") is False
    assert pk.presented_key_ok(STRONG[:-1]) is False
    assert pk.presented_key_ok(None) is False
    assert pk.presented_key_ok("ключ" * 11) is False          # non-ASCII must not raise
    assert pk.proxy_headers() == {"X-Internal-Key": STRONG}


def _req(path, key=None):
    return types.SimpleNamespace(url=types.SimpleNamespace(path=path),
                                 headers={"X-Internal-Key": key} if key is not None else {})


@pytest.mark.asyncio
async def test_the_router_gate_accepts_the_key_only_on_the_testers_own_routes_and_only_when_configured(monkeypatch):
    """§SUITES1018: the key unlocks the tester's own routes (a console hands its api-tester calls to its target), and
    no other admin route, not even the tester's archive or its sandbox reset."""
    from agentvault_registry.routers import admin_api_test as aat
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", STRONG)
    for path in ("/api/v1/admin/api-test/test-flow", "/api/v1/admin/api-test/test-endpoint",
                 "/api/v1/admin/api-test/reset-flow-values", "/api/v1/admin/api-test/endpoints",
                 "/api/v1/admin/api-test/flow-values", "/api/v1/admin/api-test/eager-bootstrap"):
        assert await aat.require_admin_or_proxy_key(_req(path, STRONG), None) is None, path
    for path, key in (("/api/v1/admin/api-test/test-flow", "wrong" * 9),       # wrong key
                      ("/api/v1/admin/api-test/runs/publish", STRONG),        # right key, the archive
                      ("/api/v1/admin/api-test/reset-sandbox", STRONG),       # right key, the destructive reset
                      ("/api/v1/admin/api-test/sandbox-credentials", STRONG),
                      ("/api/v1/admin/developers", STRONG)):                  # right key, any other admin route
        with pytest.raises(HTTPException) as e:
            await aat.require_admin_or_proxy_key(_req(path, key), None)
        assert e.value.status_code == 401, path
    monkeypatch.delenv("API_TEST_PROXY_INTERNAL_KEY")
    with pytest.raises(HTTPException) as e:                                    # unset: closed
        await aat.require_admin_or_proxy_key(_req("/api/v1/admin/api-test/test-flow", STRONG), None)
    assert e.value.status_code == 401


@pytest.mark.asyncio
async def test_peer_es_facts_refuses_without_the_configured_key(monkeypatch):
    from agentvault_registry.routers import mcp_tester as mt
    monkeypatch.delenv("API_TEST_PROXY_INTERNAL_KEY", raising=False)
    with pytest.raises(HTTPException) as e:
        await mt.peer_es_facts(_req("/api/v1/admin/mcp-tester/peer-es-facts", STRONG))
    assert e.value.status_code == 401
    monkeypatch.setenv("API_TEST_PROXY_INTERNAL_KEY", STRONG)
    monkeypatch.setattr(mt, "_EMIT_ES_B_URL", "")
    out = await mt.peer_es_facts(_req("/api/v1/admin/mcp-tester/peer-es-facts", STRONG))
    assert out["store"] is None and out["reachable"] is False        # past the gate: the node's own answer


# ── 10b. the optional login refuses what the required one refuses ─────────────────────────────

def _dev(**kw):
    base = dict(id=7, name="d", email="d@x", token_version=1, deleted_at=None,
                is_suspended=False, deletion_status=None)
    base.update(kw)
    return types.SimpleNamespace(**base)


def _app(monkeypatch, dev):
    async def _get(db, developer_id):
        return dev if developer_id == dev.id else None
    monkeypatch.setattr(security.developer_crud, "get_developer_by_id_lean", _get)  # V0553: the optional actor reads the developer's own row (crud get_developer_by_id_lean)

    async def _no_db():
        yield None
    app = FastAPI()
    app.dependency_overrides[security.get_db] = _no_db

    @app.get("/who")
    async def who(viewer=Depends(security.get_current_developer_optional)):
        return {"viewer": getattr(viewer, "id", None)}
    return TestClient(app)


def _who(client, token=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    return client.get("/who", headers=h).json()["viewer"]


def test_a_live_token_is_identified(monkeypatch):
    c = _app(monkeypatch, _dev())
    assert _who(c, security.create_access_token({"sub": "7"}, token_version=1)) == 7
    assert _who(c, security.create_access_token({"sub": "7"})) == 7        # no tv: grandfathered, as required
    assert _who(c) is None


def test_a_revoked_token_reads_as_anonymous(monkeypatch):
    c = _app(monkeypatch, _dev(token_version=2))                           # logged out since
    assert _who(c, security.create_access_token({"sub": "7"}, token_version=1)) is None


@pytest.mark.parametrize("state", [dict(is_suspended=True), dict(deleted_at="2026-09-11"),
                                   dict(deletion_status="anonymized")])
def test_a_suspended_deleted_or_anonymized_account_reads_as_anonymous(monkeypatch, state):
    c = _app(monkeypatch, _dev(**state))
    assert _who(c, security.create_access_token({"sub": "7"}, token_version=1)) is None


def test_a_refresh_token_is_not_an_identity(monkeypatch):
    c = _app(monkeypatch, _dev())
    assert _who(c, security.create_refresh_token(7, token_version=1)) is None


# ── 10c. the tester switch is a role, not inherited posture ───────────────────────────────────

def test_an_operator_does_not_inherit_the_tester_switch():
    from agentvault_registry.services import cloud_provisioner as cp
    assert "API_TEST_EXECUTION_ENABLED" not in cp.PARENT_POSTURE_KEYS
    assert "REPUTATION_BOND_MODE" in cp.PARENT_POSTURE_KEYS                 # control: posture still inherited


# ── 2. the recorded policy version is frame_policy's ──────────────────────────────────────────

def test_the_engine_carries_no_version_fallback_of_its_own():
    text = (SRC / "services" / "enforcement_engine.py").read_text(encoding="utf-8")
    assert "if policy_row else 1" not in text
    assert "get_active_policy(" not in text


@pytest.mark.asyncio
async def test_the_factory_default_records_version_zero_and_a_row_its_own(monkeypatch):
    from agentvault_registry.services.enforcement_engine import EnforcementEngine

    async def _none(db):
        return None
    monkeypatch.setattr(ce, "get_active_policy", _none)
    assert await EnforcementEngine()._policy_version(None) == 0

    row = types.SimpleNamespace(policy_json={}, version=3, modified_at=None, modified_by="t")

    async def _row(db):
        return row
    monkeypatch.setattr(ce, "get_active_policy", _row)
    assert await EnforcementEngine()._policy_version(None) == 3
