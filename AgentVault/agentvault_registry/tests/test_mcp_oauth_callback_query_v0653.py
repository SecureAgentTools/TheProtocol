"""V0653 (am), the plan's item 8 (session-lead, the sessions' room seq 858): the authorization code joins a registered
redirect_uri's own query.

mcp/oauth.py built the callback as f"{redirect_uri}?{urlencode(params)}", so a client whose registered redirect_uri
already carries a query (https://c.example/cb?tenant=a) was sent https://c.example/cb?tenant=a?code=...: its own
parameter read "a?code=..." and the code reached it under no name. RFC 6749 3.1.2: the client's query component is kept
when parameters are added. Now the code and the state join that query, and one of ours replaces one of the same name.
The cases marked BASE fail on ddee98169.

Through FastAPI on the real router, with the harness of test_mcp_oauth_escape_and_redirect_v0652.py: only Redis (the
module's in-memory fallback), the database session and the authorize step's two loopback calls are replaced.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
from types import SimpleNamespace
from urllib.parse import parse_qsl, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.mcp import oauth as O

KEY = "avreg_" + "q" * 43
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
WITH_QUERY = "https://c.example/cb?tenant=a&lang=de"
NAMES_STATE = "https://c.example/cb?state=registered&tenant=a"
PLAIN = "https://c.example/cb"


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
def client(monkeypatch):
    import httpx

    async def _no_redis():
        return None
    monkeypatch.setattr(O, "_redis", _no_redis)
    for store in (O._mem_clients, O._mem_codes, O._mem_refresh):
        store.clear()
    O._mem_clients["cid"] = {"client_id": "cid", "client_secret": "sec", "client_name": "Claude",
                             "token_endpoint_auth_method": "client_secret_post",
                             "redirect_uris": [WITH_QUERY, NAMES_STATE, PLAIN]}

    @contextlib.asynccontextmanager
    async def _ctx():
        yield _Db()
    import agentvault_registry.database as database
    monkeypatch.setattr(database, "get_db_context", _ctx)

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
            if url.endswith("/auth/login"):
                return _Resp(200, {"access_token": "dev-jwt"})
            return _Resp(201, {"plain_api_key": KEY})
    monkeypatch.setattr(httpx, "AsyncClient", _Http)
    app = FastAPI()
    app.include_router(O.router)
    return TestClient(app, raise_server_exceptions=False)


def _authorize(client, redirect_uri, state="s-1"):
    r = client.post("/oauth/authorize", follow_redirects=False,
                    data={"email": "a@example.test", "password": "pw", "client_id": "cid", "redirect_uri": redirect_uri,
                          "code_challenge": CHALLENGE, "code_challenge_method": "S256", "state": state,
                          "scope": "mcp:tools"})
    assert r.status_code == 302, (r.status_code, r.text[:200])
    return r.headers["location"]


def test_the_code_joins_a_registered_query(client):
    # BASE: https://c.example/cb?tenant=a&lang=de?code=...&state=s-1 (two '?', the client's lang read "de?code=...")
    loc = _authorize(client, WITH_QUERY)
    assert loc.count("?") == 1, loc
    u = urlparse(loc)
    q = dict(parse_qsl(u.query))
    assert (u.scheme, u.netloc, u.path) == ("https", "c.example", "/cb")
    assert q["tenant"] == "a" and q["lang"] == "de" and q["state"] == "s-1" and q.get("code"), q
    assert q["code"] in O._mem_codes


def test_a_registered_state_is_replaced_by_the_request_s(client):
    # BASE: the address carried two '?' and its own state=registered; the client read neither as the request's
    loc = _authorize(client, NAMES_STATE)
    pairs = parse_qsl(urlparse(loc).query)
    assert loc.count("?") == 1, loc
    assert [v for k, v in pairs if k == "state"] == ["s-1"] and dict(pairs)["tenant"] == "a", pairs


def test_control_an_address_with_no_query_gets_code_and_state_as_before(client):
    loc = _authorize(client, PLAIN)
    assert loc.startswith(PLAIN + "?code=") and loc.endswith("&state=s-1"), loc
