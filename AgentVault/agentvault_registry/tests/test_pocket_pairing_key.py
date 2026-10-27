"""§POCKETPAIR (2026-10-15): a paired phone's key is narrow, removing the phone revokes it, and no key mints past itself.

POCKET FRAME's "Pair this phone" minted a '*' key (full developer authority, and admin authority for an admin) that
lived 365 days, and nothing tied it to the phone: removing the phone left the key live. Mapping it found two holes any
narrow key falls through: POST /developers/me/apikeys minted a never-expiring '*' key for ANY key (an MCP OAuth key
included), and /auth/api-keys let a 'keys:manage' key mint a '*' key. And several admin checks read the account's
is_admin and never the presented key's scope. Each test below fails on V0617.
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry import schemas, security
from agentvault_registry.routers import auth_secure, developers, device_push
from agentvault_registry.services import device_key_link as link

SRC = pathlib.Path(security.__file__).resolve().parent


def _with(scopes=None, key_id=None):
    """Publish a presented key for the duration of a with-block (None, None = a JWT)."""
    class _Ctx:
        def __enter__(self):
            self.t1 = security._PRESENTED_KEY_SCOPES.set(scopes)
            self.t2 = security._PRESENTED_KEY_ID.set(key_id)

        def __exit__(self, *a):
            security._PRESENTED_KEY_SCOPES.reset(self.t1)
            security._PRESENTED_KEY_ID.reset(self.t2)
    return _Ctx()


class _Res:
    def __init__(self, rows):
        self._rows = list(rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _DB:
    """Records every statement; answers each execute with the next scripted row list."""

    def __init__(self, *script):
        self.script, self.calls, self.commits, self.rollbacks = list(script), [], 0, 0

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), dict(params or {})))
        return _Res(self.script.pop(0) if self.script else [])

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1


# ── the predicates ───────────────────────────────────────────────────────────────────────────────────────────────────
def test_key_may_mint_never_past_the_presenting_key():
    with _with(None):
        assert security.key_may_mint(None) and security.key_may_mint(["*"])          # a session mints anything
    with _with(["*"]):
        assert security.key_may_mint(None)
    with _with(["mcp:tools"]):
        assert not security.key_may_mint(None) and not security.key_may_mint(["mcp:tools"])   # no keys:manage
    with _with(["keys:manage"]):
        assert not security.key_may_mint(None), "keys:manage minted a '*' key"
        assert not security.key_may_mint(["mcp:admin"])
        assert security.key_may_mint(["keys:manage"])
    with _with(["keys:manage", "mcp:tools"]):
        assert security.key_may_mint(["mcp:tools"]) and not security.key_may_mint(["mcp:tools", "mcp:admin"])


def test_admin_credential_follows_the_presented_key():
    admin, member = SimpleNamespace(is_admin=True), SimpleNamespace(is_admin=False)
    with _with(None):
        assert security.admin_credential(admin) and not security.admin_credential(member)
    with _with(["*"]):
        assert security.admin_credential(admin)
    with _with(["mcp:tools"]):
        assert not security.admin_credential(admin), "a phone's key carried the account's admin power"
    with _with(["mcp:admin"]):
        assert security.admin_credential(admin) and not security.admin_credential(member)


def test_the_link_reads_only_a_positive_integer_and_a_client_never_writes_it():
    assert link.paired_key_id({link.PREFS_KEY: 42}) == 42
    assert link.paired_key_id(json.dumps({link.PREFS_KEY: "17"})) == 17
    for bad in (None, {}, {link.PREFS_KEY: True}, {link.PREFS_KEY: -3}, {link.PREFS_KEY: "x"}, "not json", [42]):
        assert link.paired_key_id(bad) is None, bad
    assert link.client_prefs({link.PREFS_KEY: 9, "min_transfer_avt": 5}) == {"min_transfer_avt": 5}
    assert link.client_prefs(None) == {}


# ── the device routes ────────────────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def _quiet_notify(monkeypatch):
    import agentvault_registry.background_tasks.push_notify as pn

    async def _nothing(*a, **k):
        return None
    monkeypatch.setattr(pn, "notify", _nothing)


async def test_a_phone_registering_with_its_key_records_that_key(_quiet_notify):
    db = _DB([SimpleNamespace(id=11, created_at=None, last_seen_at=None)])
    body = schemas.DevicePushRegisterIn(platform="android", rail="ntfy", target="pf-topic-1", label="Pixel 9",
                                        prefs={"min_transfer_avt": 5, link.PREFS_KEY: 999})
    with _with(["mcp:tools"], 42):
        out = await device_push.register_device(body=body, current=SimpleNamespace(id=5), db=db)
    sql, params = db.calls[0]
    assert json.loads(params["prefs"]) == {"min_transfer_avt": 5, link.PREFS_KEY: 42}, "the client's 999 must not stand"
    assert params["kid"] == 42 and "paired_api_key_id" in sql and out["paired_key"] is True


async def test_a_session_registration_records_no_key_and_strips_a_claimed_one(_quiet_notify):
    db = _DB([SimpleNamespace(id=12, created_at=None, last_seen_at=None)])
    body = schemas.DevicePushRegisterIn(platform="web", rail="ntfy", target="pf-topic-2", label="Desk",
                                        prefs={link.PREFS_KEY: 7})
    with _with(None, None):
        out = await device_push.register_device(body=body, current=SimpleNamespace(id=5), db=db)
    _, params = db.calls[0]
    assert json.loads(params["prefs"]) == {} and params["kid"] is None and out["paired_key"] is False


async def test_removing_a_paired_phone_revokes_its_key_in_the_same_transaction():
    db = _DB([SimpleNamespace(id=11, prefs=json.dumps({link.PREFS_KEY: 42}))], [SimpleNamespace(id=42)])
    out = await device_push.unregister_device(device_id=11, current=SimpleNamespace(id=5), db=db)
    assert out["paired_key_revoked"] is True and db.commits == 1
    sql, params = db.calls[1]
    assert "UPDATE developer_api_keys SET is_active = FALSE" in sql and params == {"k": 42, "dev": 5}


async def test_removing_a_device_without_a_key_revokes_nothing_and_a_missing_device_is_404():
    db = _DB([SimpleNamespace(id=12, prefs="{}")])
    out = await device_push.unregister_device(device_id=12, current=SimpleNamespace(id=5), db=db)
    assert out["paired_key_revoked"] is False and len(db.calls) == 1
    db = _DB([])
    with pytest.raises(HTTPException) as e:
        await device_push.unregister_device(device_id=99, current=SimpleNamespace(id=5), db=db)
    assert e.value.status_code == 404 and db.commits == 0


async def test_revoking_a_key_disables_the_devices_it_registered():
    db = _DB([SimpleNamespace(id=11), SimpleNamespace(id=13)])
    n = await link.disable_devices_for_key(db, 5, 42)
    sql, params = db.calls[0]
    assert n == 2 and "SET enabled = FALSE" in sql and params == {"dev": 5, "kid": "42"}


# ── the mint rails ───────────────────────────────────────────────────────────────────────────────────────────────────
async def test_the_legacy_mint_rail_refuses_a_scoped_key():
    with _with(["mcp:tools"], 42):
        with pytest.raises(HTTPException) as e:
            await developers.create_new_api_key(description="x", db=_DB(), current_developer=SimpleNamespace(id=5))
    assert e.value.status_code == 403


async def test_auth_api_keys_refuses_a_key_broader_than_the_one_asking(monkeypatch):
    async def _row(db, plain_key):
        return SimpleNamespace(id=42, scopes=["keys:manage"])
    monkeypatch.setattr(auth_secure.developer_crud, "get_api_key_row_by_plain_key", _row)
    for payload in ("phone key", schemas.ApiKeyCreateRequest(key_name="x", scopes=["*"]),
                    schemas.ApiKeyCreateRequest(key_name="x", scopes=["mcp:admin"])):
        with pytest.raises(HTTPException) as e:
            await auth_secure.create_api_key(payload=payload, authorization="Bearer avreg_presented",
                                             current_developer=SimpleNamespace(id=5), db=_DB())
        assert e.value.status_code == 403 and "does not hold" in str(e.value.detail), payload


# ── the admin sites ──────────────────────────────────────────────────────────────────────────────────────────────────
ADMIN_SITES = {   # every inline admin check the mapping found, and how many each file must route through admin_credential
    "routers/mcp_tester.py": 2, "routers/console_suite.py": 1, "routers/oauth_federation.py": 3,
    "routers/agent_authz_api.py": 3, "routers/agent_delegation_api.py": 4, "routers/liability.py": 5,
    "routers/bundles.py": 5,
    "routers/phone_fabric.py": 1,   # D6-529: the mapping missed it (its helper read getattr(dev, "is_admin"))
}
OLD_CHECK = re.compile(r"not\s+[A-Za-z_]+\.is_admin\b|getattr\([A-Za-z_]+,\s*[\"']is_admin[\"']")


def test_the_inline_admin_checks_ask_the_presented_key():
    for rel, n in ADMIN_SITES.items():
        text = (SRC / rel).read_text()
        calls = sum(1 for node in ast.walk(ast.parse(text)) if isinstance(node, ast.Call)
                    and getattr(node.func, "attr", getattr(node.func, "id", "")) == "admin_credential")
        assert calls >= n, f"{rel}: admin_credential called {calls}x, want >= {n}"
        code = "\n".join(ln.split("#", 1)[0] for ln in text.splitlines())
        assert not OLD_CHECK.search(code), f"{rel}: an inline is_admin check is back: {OLD_CHECK.search(code).group(0)}"
    fiat = (SRC / "routers/fiat_onramp.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(fiat)) if isinstance(n, ast.FunctionDef) and n.name == "_is_admin_developer")
    # D6-821: the check is security.admin_flag_credential(dev), which asks api_key_grants_admin (and the second factor,
    # and the forced password change); either form asks the presented key
    body = ast.unparse(fn)
    assert "api_key_grants_admin" in body or "admin_flag_credential" in body, \
        "fiat_onramp's admin check ignores the presented key"


def test_every_key_path_publishes_the_scopes():
    text = (SRC / "security.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(text)) if isinstance(n, ast.AsyncFunctionDef) and n.name == "get_current_developer_unified")
    assert ast.unparse(fn).count("_publish_presented_key") == 2, "a key path of the unified dependency publishes nothing"
