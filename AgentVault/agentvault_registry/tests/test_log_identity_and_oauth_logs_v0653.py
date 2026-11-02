"""V0653 (am), items 7 and 8 (the hardening list in the sessions' room): log lines name a person without their address,
and the MCP OAuth flow names the API key it mints by its id, never by its characters.

The helper (core/log_identity.py) on its own, and the real OAuth router (mcp/oauth.py) through FastAPI with its logs
captured, as test_mcp_oauth_escape_and_redirect_v0652.py drives it (only Redis, the database session and the two
loopback calls are replaced). BASE (a5ef48ddd, V0652): the success line carries the key's first 15 characters and the
whole e-mail address; the helper does not exist.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.mcp import oauth as O

KEY = "avreg_" + "k" * 43
EMAIL = "maintainer.private@example.test"
VERIFIER = "v" * 64
CHALLENGE = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
GOOD = "https://c.example/cb"


def test_email_for_log_names_without_the_address():
    from agentvault_registry.core.log_identity import email_for_log
    shown = email_for_log(EMAIL)
    assert shown.startswith("m…@example.test #") and "maintainer.private" not in shown
    assert email_for_log(EMAIL.upper()) == shown                     # one person, one name across a flow
    assert email_for_log("other@example.test") != shown
    assert email_for_log(None) == "email:none" and email_for_log("") == "email:none"
    assert email_for_log("no-at-sign").startswith("email:#")


def test_api_key_for_log_names_the_id_only():
    from agentvault_registry.core.log_identity import api_key_for_log
    assert api_key_for_log({"id": 42, "key_prefix": "avreg_"}) == "key id 42"
    assert api_key_for_log(None) == "key id unknown" and api_key_for_log({}) == "key id unknown"


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
    async def _no_redis():
        return None
    monkeypatch.setattr(O, "_redis", _no_redis)
    for store in (O._mem_clients, O._mem_codes, O._mem_refresh):
        store.clear()
    O._mem_clients["cid"] = {"client_id": "cid", "client_secret": "sec", "client_name": "Claude",
                             "token_endpoint_auth_method": "client_secret_post", "redirect_uris": [GOOD]}

    @contextlib.asynccontextmanager
    async def _ctx():
        yield _Db()
    import agentvault_registry.database as database
    monkeypatch.setattr(database, "get_db_context", _ctx)
    import httpx

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
            return _Resp(201, {"plain_api_key": KEY, "api_key_info": {"id": 4242, "key_prefix": "avreg_"}})
    monkeypatch.setattr(httpx, "AsyncClient", _Http)
    app = FastAPI()
    app.include_router(O.router)
    return TestClient(app, raise_server_exceptions=False)


def test_the_oauth_flow_logs_the_key_by_id_and_the_person_without_their_address(client, caplog):
    caplog.set_level(logging.INFO, logger=O.logger.name)
    r = client.post("/oauth/authorize", data={"email": EMAIL, "password": "pw", "client_id": "cid", "redirect_uri": GOOD,
                                              "code_challenge": CHALLENGE, "code_challenge_method": "S256",
                                              "state": "s", "scope": "mcp:tools"}, follow_redirects=False)
    assert r.status_code == 302, r.text
    text = "\n".join(rec.getMessage() for rec in caplog.records)
    assert "[MCP OAuth] Generated API key (key id 4242)" in text
    assert KEY[:10] not in text and "maintainer.private" not in text
    assert "m…@example.test #" in text
