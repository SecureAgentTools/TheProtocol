"""§SECBATCH wave 3 (2026-10-16): adminGrafanaQuery signs in to Grafana only with the password configured for this
registry (GRAFANA_ADMIN_PASS); with none configured it refuses, "Grafana credentials not configured", and sends nothing.

Measured on the base (1032dca8): the tool's password came from getattr(settings, "GRAFANA_ADMIN_PASS", <a literal in
the source>). Settings declares no such field, so the literal was used whatever the environment said: every call sent a
Basic login built from a value in the source, and a configured password was never read.

Why no test caught it: the tool's tests (test_mcp_admin_wrapper_errors, test_mcp_admin_envelope_wire) check its error
helper and its source text; none called it and looked at what it sends.

The tool runs through FastAPI on the real admin MCP router (POST /mcp/admin/rpc, tools/call); only the caller (an
admin), the audit writer and Grafana (an httpx transport that records the method and path it is asked, never a header)
are supplied. The assertions compare paths and booleans only, so a failure prints nothing a login is made of.
"""
from __future__ import annotations

import base64
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.mcp import server_admin as SA
from agentvault_registry.mcp import tools_admin as TA

TEST_PASSWORD = "grafana-test-credential-not-a-secret"
# the tool as the admin dispatch names it
TOOL = next(n for n in SA.ADMIN_TOOL_DISPATCH if n.endswith("_adminGrafanaQuery"))
CALLER = SimpleNamespace(is_anonymous=False, is_developer=True, is_agent=False, auth_type="developer", developer_id=42,
                         agent_did=None, is_admin=True, raw_token="t", agent_id=None)


@pytest.fixture()
def grafana(monkeypatch):
    sent, login_ok = [], []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append((request.method, request.url.path))
        expected = "Basic " + base64.b64encode(f"admin:{TEST_PASSWORD}".encode()).decode()
        login_ok.append(request.headers.get("authorization") == expected)
        return httpx.Response(200, json=[{"uid": "d1", "title": "Frame"}])

    real_client = httpx.AsyncClient

    def client_factory(*args, **kwargs):
        kwargs.pop("verify", None)
        return real_client(*args, transport=httpx.MockTransport(answer), **kwargs)

    async def _admin(*a, **k):
        return CALLER

    async def _audit(**kw):
        return None

    # the tool reads its address and user from the environment when it runs (§DOCSFIX D6-251)
    monkeypatch.setenv("GRAFANA_URL", "http://grafana.test:3000")
    monkeypatch.delenv("GRAFANA_ADMIN_USER", raising=False)
    monkeypatch.setattr(TA.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(SA, "authenticate_mcp_token", _admin)
    monkeypatch.setattr(SA, "emit_mcp_audit", _audit)
    monkeypatch.delenv("GRAFANA_ADMIN_PASS", raising=False)

    app = FastAPI()
    app.include_router(SA.router, prefix="/mcp/admin")
    client = TestClient(app, raise_server_exceptions=False)

    def call(path="/api/search"):
        r = client.post("/mcp/admin/rpc", headers={"Authorization": "Bearer admin-test-token"},
                        json={"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                              "params": {"name": TOOL, "arguments": {"path": path}}})
        assert r.status_code == 200, r.status_code
        result = r.json().get("result") or {}
        text = " ".join(c.get("text", "") for c in result.get("content") or [])
        return result, text

    return call, sent, login_ok


def test_with_no_password_configured_the_tool_refuses_and_sends_nothing(grafana):
    call, sent, _ = grafana
    result, text = call()
    assert "Grafana credentials not configured" in text, "the tool did not refuse"
    assert result.get("isError") is True
    assert sent == [], "a request went to Grafana with no password configured"


def test_a_blank_password_is_no_password(grafana, monkeypatch):
    call, sent, _ = grafana
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", "   ")
    _, text = call()
    assert "Grafana credentials not configured" in text and sent == []


def test_with_the_password_configured_the_tool_signs_in_with_it(grafana, monkeypatch):
    call, sent, login_ok = grafana
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", TEST_PASSWORD)
    result, text = call("/api/search")
    assert sent == [("GET", "/api/search")]
    assert login_ok == [True], "the request did not carry the configured login"
    assert not result.get("isError") and "200" in text and "Frame" in text
