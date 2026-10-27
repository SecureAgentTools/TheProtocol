"""CB-499 (2026-10-16): the federation crawls verify the peer's certificate and follow no redirect.

The map behind GET /api/v1/agents/locations/trusted-registries was crawled with httpx verify=False and
follow_redirects=True, and so were main.py's topology crawl (whose discoveries are written back as ACTIVE peer rows)
and the peer fallback of cross-registry receiver resolution; receiver resolution then derived a teg_id and registry_id
from a crawled name. A listing answered by anyone on the path, or redirected anywhere, became part of the map. Now one
client (agent_locations._crawl_client) verifies TLS with the registry's own trust (the SPIRE bundle and the public
roots, es_ssl_helper.get_httpx_verify) and follows no redirect, and one request helper keeps the DNS bypass verifying
the certificate for the peer's name.

Through FastAPI on the real trusted-registries route: the peer table is a double, the HTTP client is httpx's own with a
mock transport (a peer that answers its listing with a redirect to another host), and the registry's verify setting is
a recognisable SSL context. The two sibling crawls are pinned on their call sites (AST, not text).
RED on 7140a4a6: all three tests (the redirect was followed and the stranger served, verify=False everywhere).
"""
import ast
import pathlib
import ssl
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry import es_ssl_helper
from agentvault_registry.background_tasks import leader
from agentvault_registry.database import get_db
from agentvault_registry.routers import agent_locations

PEER = SimpleNamespace(name="frame-x", base_url="https://frame-x.example.invalid:8443", status="ACTIVE",
                       peer_type="frame", cached_registry_card=None)
STRANGER = "stranger-registry"


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return SimpleNamespace(all=lambda: list(self._rows))

    def all(self):
        return list(self._rows)


class _Db:
    async def execute(self, stmt, *a, **k):
        cols = [c["name"] for c in stmt.column_descriptions]
        if cols == ["PeerRegistry"]:
            return _Result([PEER])
        if "cached_registry_card" in cols:
            return _Result([])
        # the ACTIVE-name filter: as if a crawl had already written the stranger back as a peer row
        return _Result([("frame-x",), (STRANGER,)])


def _handler(request: httpx.Request) -> httpx.Response:
    if request.url.host == "frame-x.example.invalid" and request.url.path == "/api/v1/federation/peers/":
        return httpx.Response(302, headers={"Location": "https://elsewhere.example.invalid/api/v1/federation/peers/"})
    if request.url.host == "elsewhere.example.invalid" and request.url.path == "/api/v1/federation/peers/":
        return httpx.Response(200, json={"items": [{"name": STRANGER, "base_url": "https://elsewhere.example.invalid"}]})
    return httpx.Response(404)


@pytest.fixture()
def crawl(monkeypatch):
    made = []
    ctx = ssl.create_default_context()
    real = httpx.AsyncClient

    class _Recording(real):
        def __init__(self, *a, **kw):
            made.append({"verify": kw.get("verify", True), "follow_redirects": kw.get("follow_redirects", False)})
            kw.pop("verify", None)
            kw["transport"] = httpx.MockTransport(_handler)
            super().__init__(*a, **kw)

    async def _no_redis():
        return None

    monkeypatch.setattr(httpx, "AsyncClient", _Recording)
    monkeypatch.setattr(es_ssl_helper, "get_httpx_verify", lambda: ctx)
    monkeypatch.setattr(leader, "get_redis", _no_redis)
    monkeypatch.setattr(agent_locations, "_get_host_public_ip", lambda: "")
    monkeypatch.setattr(agent_locations, "_trusted_cache", {})
    return made, ctx


def _trusted():
    app = FastAPI()
    app.include_router(agent_locations.router, prefix="/api/v1/agents/locations")
    app.dependency_overrides[get_db] = lambda: _Db()
    return TestClient(app, raise_server_exceptions=False).get("/api/v1/agents/locations/trusted-registries")


def test_a_redirected_listing_does_not_enter_the_map(crawl):
    r = _trusted()
    assert r.status_code == 200, (r.status_code, r.text[:300])
    names = [x["name"] for x in r.json()["registries"]]
    assert "frame-x" in names, names                        # control: the direct peer is served
    assert STRANGER not in names, names


def test_every_crawl_client_verifies_with_the_registrys_trust_and_follows_no_redirect(crawl):
    made, ctx = crawl
    _trusted()
    assert made, "the crawl built no client"
    assert all(m["verify"] is ctx for m in made), made
    assert not any(m["follow_redirects"] for m in made), made


SRC = pathlib.Path(agent_locations.__file__).resolve().parents[1]


def _calls_in(path, func_name):
    tree = ast.parse((SRC / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
            return [n for n in ast.walk(node) if isinstance(n, ast.Call)]
    raise AssertionError(f"{func_name} not found in {path}")


@pytest.mark.parametrize("path, func_name", [
    ("main.py", "_run_topology_bfs"),                                  # writes ACTIVE peer rows back
    ("routers/teg_integration.py", "_resolve_receiver_registry"),       # routes a transfer by a crawled name
])
def test_the_sibling_crawls_use_the_verified_client(path, func_name):
    calls = _calls_in(path, func_name)
    for call in calls:
        for kw in call.keywords:
            if kw.arg == "verify":
                assert not (isinstance(kw.value, ast.Constant) and kw.value.value is False), f"verify=False in {func_name}"
            if kw.arg == "follow_redirects":
                assert not (isinstance(kw.value, ast.Constant) and kw.value.value is True), f"redirects in {func_name}"
    names = {getattr(c.func, "id", getattr(c.func, "attr", None)) for c in calls}
    assert "_crawl_client" in names and "_crawl_get" in names, sorted(n for n in names if n)
