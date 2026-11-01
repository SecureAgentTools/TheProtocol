"""V0652 (2026-11-01, agentvault2-14; session-lead's code-scanning triage, the sessions' room seq 624): the MCP OAuth login
page escapes what it shows, and the authorization code goes only to an address its client registered.

The page at /oauth/authorize substituted every value raw (state, scope, code_challenge and the method from the link; the
client's name from an open registration), so a crafted link could close an attribute and run a script on the page that
takes the email and the password, or plant a redirect_uri input. POST /oauth/authorize then sent the code to whatever
redirect_uri the form carried (only the GET compared it with the client's list), and the token exchange never looked at
it. Now one render escapes every value in a single pass, the POST refuses an unregistered redirect_uri before it tries the
credentials, and the exchange refuses a code whose redirect_uri is not registered or differs from the one presented.
Each case but the controls fails on 05441be31 (V0651).

Through FastAPI on the real router (mcp/oauth.py), as test_mcp_oauth_key_lifetime_and_revoke.py does: only Redis (the
module's in-memory fallback), the database session and the authorize step's two loopback calls are replaced.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.mcp import oauth as O

KEY = "avreg_" + "e" * 43
VERIFIER = "w" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
GOOD, EVIL = "https://c.example/cb", "https://evil.example/cb"
SCRIPT = '"><script>alert(1)</script>'


class _Res:
    def first(self):
        return (42, 7)

    def fetchall(self):
        return []


class _Db:
    async def execute(self, stmt, params=None):
        return _Res()

    async def commit(self):
        pass


@pytest.fixture()
def rig(monkeypatch):
    async def _no_redis():
        return None
    monkeypatch.setattr(O, "_redis", _no_redis)
    for store in (O._mem_clients, O._mem_codes, O._mem_refresh):
        store.clear()
    O._mem_clients["cid"] = {"client_id": "cid", "client_secret": "sec", "client_name": "<b>Claude</b><script>x()</script>",
                             "token_endpoint_auth_method": "client_secret_post", "redirect_uris": [GOOD]}

    @contextlib.asynccontextmanager
    async def _ctx():
        yield _Db()
    import agentvault_registry.database as database
    monkeypatch.setattr(database, "get_db_context", _ctx)
    app = FastAPI()
    app.include_router(O.router)
    return SimpleNamespace(client=TestClient(app, raise_server_exceptions=False))


def _login_stub(monkeypatch, login_status=401):
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
            sent.append(url)
            if url.endswith("/auth/login"):
                return _Resp(login_status, {"access_token": "dev-jwt"})
            return _Resp(201, {"plain_api_key": KEY})
    monkeypatch.setattr(httpx, "AsyncClient", _Http)
    return sent


def _form(**kw):
    d = {"email": "a@example.test", "password": "pw", "client_id": "cid", "redirect_uri": GOOD,
         "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": "s", "scope": "mcp:tools"}
    d.update(kw)
    return d


# ── the page escapes every value ──────────────────────────────────────────────────────────────────────────────────────

def test_the_login_page_escapes_the_link_and_the_client_name(rig):
    r = rig.client.get("/oauth/authorize", params={"client_id": "cid", "code_challenge": CHALLENGE + SCRIPT,
                                                   "state": SCRIPT, "scope": 'mcp:tools" autofocus onfocus="x()',
                                                   "redirect_uri": GOOD})
    assert r.status_code == 200, r.text
    page = r.text
    assert "<script>alert(1)</script>" not in page and "<script>x()</script>" not in page and "<b>Claude</b>" not in page
    assert '" autofocus onfocus="' not in page
    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;" in page
    assert "&lt;b&gt;Claude&lt;/b&gt;&lt;script&gt;x()&lt;/script&gt; wants to connect" in page


def test_a_value_is_never_searched_again_for_a_placeholder(rig):
    O._mem_clients["cid"]["client_name"] = "{{STATE}}"
    r = rig.client.get("/oauth/authorize", params={"client_id": "cid", "code_challenge": CHALLENGE, "state": "S-1",
                                                   "redirect_uri": GOOD})
    assert "{{STATE}} wants to connect" in r.text


def test_the_page_after_a_failed_sign_in_escapes_too(rig, monkeypatch):
    _login_stub(monkeypatch, login_status=401)
    r = rig.client.post("/oauth/authorize", data=_form(state=SCRIPT), follow_redirects=False)
    assert r.status_code == 200 and "Invalid email or password" in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text


# ── the code goes only to a registered address ───────────────────────────────────────────────────────────────────────

def test_the_post_refuses_an_unregistered_redirect_uri_before_it_tries_the_credentials(rig, monkeypatch):
    sent = _login_stub(monkeypatch, login_status=200)
    r = rig.client.post("/oauth/authorize", data=_form(redirect_uri=EVIL), follow_redirects=False)
    assert r.status_code == 400 and r.json()["error_description"] == "redirect_uri not registered", r.text
    assert sent == [] and O._mem_codes == {}


def test_control_a_registered_redirect_uri_gets_its_code(rig, monkeypatch):
    _login_stub(monkeypatch, login_status=200)
    r = rig.client.post("/oauth/authorize", data=_form(), follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"].startswith(GOOD + "?code="), r.text


def _code(redirect_uri=GOOD):
    O._mem_codes["c1"] = {"client_id": "cid", "redirect_uri": redirect_uri, "code_challenge": CHALLENGE,
                          "code_challenge_method": "S256", "scope": "mcp:tools", "api_key": KEY, "dev_token": "x"}
    return {"grant_type": "authorization_code", "code": "c1", "code_verifier": VERIFIER,
            "client_id": "cid", "client_secret": "sec"}


def test_the_exchange_refuses_a_code_issued_for_an_unregistered_address(rig):
    r = rig.client.post("/oauth/token", data=_code(redirect_uri=EVIL))
    assert r.status_code == 400 and r.json() == {"error": "invalid_grant", "error_description": "redirect_uri not registered"}


def test_the_exchange_refuses_a_presented_redirect_uri_that_differs(rig):
    r = rig.client.post("/oauth/token", data={**_code(), "redirect_uri": "https://c.example/other"})
    assert r.status_code == 400 and r.json()["error_description"] == "redirect_uri mismatch"


def test_control_the_exchange_with_the_same_or_no_redirect_uri_is_a_grant(rig):
    r = rig.client.post("/oauth/token", data={**_code(), "redirect_uri": GOOD})
    assert r.status_code == 200 and r.json()["access_token"] == KEY, r.text
    r = rig.client.post("/oauth/token", data=_code())
    assert r.status_code == 200 and r.json()["access_token"] == KEY, r.text
