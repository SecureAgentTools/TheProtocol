"""D6-729 (2026-10-16): the MCP OAuth access token (an API key) expires when the token response says, and revoking ends it.

The token endpoint answered expires_in 86400 for a key minted with the 365-day default, a refresh handed back the same
key with the same promise, and /oauth/revoke only deleted refresh records: a "revoked" connector's key stayed valid for
a year. Now the code exchange and every refresh set the key's expiry to now + 86400, a key revoked meanwhile ends the
grant, the mint itself asks for one day, and /oauth/revoke deactivates the grant's key (only a key this flow minted).
Each test marked BASE fails on 14520b9f.

Through FastAPI on the real router (mcp/oauth.py); only Redis (the module's in-memory fallback), the database session and
the authorize step's two loopback calls are replaced.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.mcp import oauth as O

KEY = "avreg_" + "o" * 43
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")


class _Res:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row

    def fetchall(self):
        return []


class _Db:
    """Records every statement; an UPDATE ... RETURNING answers `row` (None = no active key matched)."""

    def __init__(self, row=(42, 7)):
        self.row, self.updates, self.texts = row, [], []

    async def execute(self, stmt, params=None):
        if hasattr(stmt, "compile") and str(stmt).lstrip().upper().startswith("UPDATE DEVELOPER_API_KEYS"):
            self.updates.append(dict(stmt.compile().params))
            return _Res(self.row)
        self.texts.append(str(stmt))
        return _Res(None)

    async def commit(self):
        pass

    def renewed(self):
        return [u["expires_at"] for u in self.updates if "expires_at" in u]

    def deactivated(self):
        return [u for u in self.updates if u.get("is_active") is False]


@pytest.fixture()
def rig(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(O, "_redis", _no_redis)
    for store in (O._mem_clients, O._mem_codes, O._mem_refresh):
        store.clear()
    O._mem_clients["cid"] = {"client_id": "cid", "client_secret": "sec", "client_name": "Claude",
                             "token_endpoint_auth_method": "client_secret_post", "redirect_uris": ["https://c.example/cb"]}
    db = _Db()

    @contextlib.asynccontextmanager
    async def _ctx():
        yield db
    import agentvault_registry.database as database
    monkeypatch.setattr(database, "get_db_context", _ctx)
    app = FastAPI()
    app.include_router(O.router)
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False), db=db)


def _code():
    O._mem_codes["c1"] = {"client_id": "cid", "redirect_uri": "https://c.example/cb", "code_challenge": CHALLENGE,
                          "code_challenge_method": "S256", "scope": "mcp:tools", "api_key": KEY, "dev_token": "x"}
    return {"grant_type": "authorization_code", "code": "c1", "code_verifier": VERIFIER,
            "client_id": "cid", "client_secret": "sec"}


def _near_a_day(ts):
    want = datetime.now(timezone.utc) + timedelta(seconds=86400)
    return abs((ts - want).total_seconds()) < 120


def test_the_code_exchange_sets_the_key_to_expire_when_it_says(rig):   # BASE: the key keeps 365 days
    r = rig.client.post("/oauth/token", data=_code())
    assert r.status_code == 200 and r.json()["expires_in"] == 86400, r.text
    assert len(rig.db.renewed()) == 1 and _near_a_day(rig.db.renewed()[0])


def test_a_key_revoked_before_the_exchange_is_no_grant(rig):   # BASE: 200
    rig.db.row = None
    r = rig.client.post("/oauth/token", data=_code())
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant", r.text


def test_a_refresh_renews_the_key_for_another_day(rig):   # BASE: same key, no renewal
    refresh = rig.client.post("/oauth/token", data=_code()).json()["refresh_token"]
    r = rig.client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh,
                                             "client_id": "cid", "client_secret": "sec"})
    assert r.status_code == 200 and r.json()["expires_in"] == 86400, r.text
    assert len(rig.db.renewed()) == 2 and _near_a_day(rig.db.renewed()[1])


def test_a_refresh_after_the_key_was_revoked_ends_the_grant(rig):   # BASE: 200
    refresh = rig.client.post("/oauth/token", data=_code()).json()["refresh_token"]
    rig.db.row = None
    r = rig.client.post("/oauth/token", data={"grant_type": "refresh_token", "refresh_token": refresh,
                                             "client_id": "cid", "client_secret": "sec"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant", r.text
    assert refresh not in O._mem_refresh


def test_revoking_the_refresh_token_deactivates_the_key(rig):   # BASE: the key stays valid
    refresh = rig.client.post("/oauth/token", data=_code()).json()["refresh_token"]
    r = rig.client.post("/oauth/revoke", data={"token": refresh, "token_type_hint": "refresh_token"})
    assert r.status_code == 200
    assert refresh not in O._mem_refresh and len(rig.db.deactivated()) == 1
    assert any("paired_api_key_id" in t for t in rig.db.texts)   # its push devices are disabled too


def test_revoking_the_access_token_deactivates_the_key(rig):   # BASE: the key stays valid
    rig.client.post("/oauth/token", data=_code())
    r = rig.client.post("/oauth/revoke", data={"token": KEY, "token_type_hint": "access_token"})
    assert r.status_code == 200 and len(rig.db.deactivated()) == 1
    assert not O._mem_refresh   # the grant's refresh tokens are gone


def test_control_an_unknown_token_answers_200_and_disables_nothing(rig):
    rig.db.row = None   # no active key of this flow matches
    r = rig.client.post("/oauth/revoke", data={"token": "avreg_" + "z" * 43})
    assert r.status_code == 200 and rig.db.texts == []   # RFC 7009: always 200; no device touched


def test_revocation_only_reaches_a_key_this_flow_minted(rig):   # BASE: no statement at all
    rig.db.row = None
    rig.client.post("/oauth/revoke", data={"token": "avreg_" + "z" * 43})
    assert len(rig.db.updates) == 1
    assert rig.db.updates[0].get("description_1", "").startswith("MCP OAuth (")   # the name every OAuth key carries


def test_the_mint_asks_for_one_day(rig, monkeypatch):   # BASE: the 365-day default
    import httpx
    sent = []

    class _Resp:
        def __init__(self, code, body):
            self.status_code, self._b = code, body

        def json(self):
            return self._b

    class _Http:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, **k):
            sent.append((url, k.get("json")))
            if url.endswith("/auth/login"):
                return _Resp(200, {"access_token": "dev-jwt"})
            return _Resp(201, {"plain_api_key": KEY})
    monkeypatch.setattr(httpx, "AsyncClient", _Http)
    r = rig.client.post("/oauth/authorize", follow_redirects=False, data={
        "email": "a@example.test", "password": "pw", "client_id": "cid", "redirect_uri": "https://c.example/cb",
        "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "s", "scope": "mcp:tools"})
    assert r.status_code == 302, r.text
    mint = [j for u, j in sent if u.endswith("/auth/api-keys")]
    assert mint and mint[0]["expires_in_days"] == 1 and mint[0]["key_name"].startswith("MCP OAuth (")
