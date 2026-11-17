"""V0664 (order gwo_94d297dfb0fc293483ad1632, the registry half of the Grafana kit item; session-tester seq 3344): a
frame's Grafana listens only on a unix socket, so adminGrafanaQuery dials one when GRAFANA_URL names it.

  GRAFANA_URL=unix:///run/grafana/grafana.sock   (or unix:/run/grafana/grafana.sock)
    the tool dials that socket (httpx's UDS transport) with the same path, query, method and Basic login as before;
  GRAFANA_URL=http://...  (or unset: http://grafana:3000)
    unchanged: the same client, the same URL, no transport of its own;
  a socket that is not there answers in words that name it, never a bare connection error;
  GRAFANA_URL=unix: with no path is said, and nothing is dialed;
  GRAFANA_ADMIN_PASS unset: the tool refuses as before and nothing is dialed, on either path.
Each path is measured against a real server (asyncio, on a unix socket and on a loopback port), which records the
request line and whether the login matched; no assertion prints a login.
Red on b27f2ebaf: a unix: GRAFANA_URL is dialed as an http URL and fails.
"""
from __future__ import annotations

import asyncio
import base64
import json

import pytest

from agentvault_registry.core import observability_urls as OU
from agentvault_registry.mcp import tools_admin as T
from agentvault_registry.mcp.auth_bridge import MCPAuthContext

ADMIN = MCPAuthContext(auth_type="developer", developer_id=1, is_admin=True, raw_token="x")
PASSWORD = "grafana-test-credential-not-a-secret"
LOGIN = "Basic " + base64.b64encode(f"admin:{PASSWORD}".encode()).decode()


def test_the_target_reader():
    for value, want in [
        ("", ("http://grafana:3000", None)),
        ("http://grafana.frame.internal:3001/", ("http://grafana.frame.internal:3001", None)),
        ("unix:///run/grafana/grafana.sock", ("http://grafana", "/run/grafana/grafana.sock")),
        ("unix:/run/grafana/grafana.sock", ("http://grafana", "/run/grafana/grafana.sock")),
        ("  unix:///tmp/g.sock  ", ("http://grafana", "/tmp/g.sock")),
        ("unix:", ("http://grafana", "")),
    ]:
        assert OU.grafana_target(value) == want, value


class _Server:
    """A small HTTP/1.1 server: records each request line and whether the login matched, answers JSON."""

    def __init__(self):
        self.seen = []

    async def handle(self, reader, writer):
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = await reader.read(4096)
            if not chunk:
                break
            head += chunk
        lines = head.decode(errors="replace").split("\r\n")
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:] if ":" in ln)}
        self.seen.append((lines[0], headers.get("authorization") == LOGIN))
        body = json.dumps({"database": "ok", "seen": lines[0]}).encode()
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\nConnection: close\r\n\r\n" + body)
        await writer.drain()
        writer.close()


def _run(coro):
    return asyncio.run(coro)


def test_a_unix_socket_is_dialed_with_the_same_request(monkeypatch, tmp_path):
    sock = str(tmp_path / "grafana.sock")
    monkeypatch.setenv("GRAFANA_URL", f"unix://{sock}")
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", PASSWORD)
    monkeypatch.delenv("GRAFANA_ADMIN_USER", raising=False)
    srv = _Server()

    async def go():
        server = await asyncio.start_unix_server(srv.handle, path=sock)
        async with server:
            return await T.admin_grafana_query(ADMIN, path="/api/search", params={"query": "system"})
    out = _run(go())
    assert out.get("ok") is True and out["status_code"] == 200, out
    assert out["response"]["database"] == "ok"
    assert srv.seen == [("GET /api/search?query=system HTTP/1.1", True)]


def test_the_http_path_is_unchanged(monkeypatch):
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", PASSWORD)
    monkeypatch.delenv("GRAFANA_ADMIN_USER", raising=False)
    srv = _Server()

    async def go():
        server = await asyncio.start_server(srv.handle, host="127.0.0.1", port=0)
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setenv("GRAFANA_URL", f"http://127.0.0.1:{port}")
        async with server:
            return await T.admin_grafana_query(ADMIN, path="api/health")
    out = _run(go())
    assert out.get("ok") is True, out
    assert srv.seen == [("GET /api/health HTTP/1.1", True)]


def test_a_socket_that_is_not_there_is_named(monkeypatch, tmp_path):
    sock = str(tmp_path / "absent" / "grafana.sock")
    monkeypatch.setenv("GRAFANA_URL", f"unix://{sock}")
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", PASSWORD)
    out = _run(T.admin_grafana_query(ADMIN, path="/api/health"))
    assert "error" in out and sock in out["error"] and "unix socket" in out["error"], out
    assert PASSWORD not in json.dumps(out)


def test_a_unix_url_with_no_path_is_said_and_nothing_dialed(monkeypatch):
    monkeypatch.setenv("GRAFANA_URL", "unix:")
    monkeypatch.setenv("GRAFANA_ADMIN_PASS", PASSWORD)

    def refuse(*a, **k):
        raise AssertionError("dialed")
    monkeypatch.setattr(T.httpx, "AsyncClient", refuse)
    out = _run(T.admin_grafana_query(ADMIN, path="/api/health"))
    assert "error" in out and "GRAFANA_URL" in out["error"] and "socket" in out["error"], out


@pytest.mark.parametrize("url", ["unix:///run/grafana/grafana.sock", "http://grafana.test:3000"])
def test_no_password_refuses_before_any_dial(monkeypatch, url):
    monkeypatch.setenv("GRAFANA_URL", url)
    monkeypatch.delenv("GRAFANA_ADMIN_PASS", raising=False)

    def refuse(*a, **k):
        raise AssertionError("dialed")
    monkeypatch.setattr(T.httpx, "AsyncClient", refuse)
    out = _run(T.admin_grafana_query(ADMIN, path="/api/health"))
    assert out["error"] == T.GRAFANA_NOT_CONFIGURED
