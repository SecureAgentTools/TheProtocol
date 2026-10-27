"""Tests for Phase 10 #4 federation_blocklist proxy router.

Endpoints under /api/v1/federation/admin/agents/{did}/{block,unblock}
require Mode 2 federation auth and proxy to the local TEG. Tests use
TestClient + dependency overrides + a mocked TEG response.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.routers import federation_blocklist
from agentvault_registry.core import federation_auth


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(federation_blocklist.router)

    # Mock the federation identity dep (Mode 2 auth bypass for tests)
    async def fake_identity():
        return "spiffe://test.local/peer/registry-b"

    app.dependency_overrides[federation_auth.get_federation_identity] = fake_identity

    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# §CHATCOHERE-CI (2026-09-01) — ONE httpx shim, replacing three near-identical
# aiohttp fakes.
#
# The router moved from a certless aiohttp session to the SVID httpx client
# (`_proxy_to_local_teg` now uses it; `_get_session` survives only as legacy).
# These tests kept patching `_get_session`, so the mock bound NOTHING, a real
# request went out to `teg-layer:8080`, and every one of the six failed with a
# 502 that looked like a product fault. Nothing ran them, so nobody knew.
#
# ⚠ A like-for-like port is not enough: the response CONTRACT differs in every
# field the router touches — httpx answers `status_code` (not `status`), `.text`
# is a PROPERTY (not an async method) and `.json()` is SYNCHRONOUS.
# ---------------------------------------------------------------------------

def fake_httpx(status_code=200, payload=None, body_text="",
               urls=None, headers_seen=None, payloads=None, raises=None):
    """Patch target for `httpx.AsyncClient` inside the router's `async with`."""
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = body_text
        def json(self):
            return payload or {}

    class _Client:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def post(self, url, headers=None, json=None):
            if urls is not None: urls.append(url)
            if headers_seen is not None: headers_seen.append(headers or {})
            if payloads is not None: payloads.append(json or {})
            if raises is not None: raise raises
            return _Resp()
    return _Client


def test_block_proxies_to_local_teg_with_admin_key(client, monkeypatch):
    monkeypatch.setenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "secret-teg-key")

    captured_url = []
    captured_headers = []
    captured_payload = []

    with patch.object(federation_blocklist.httpx, "AsyncClient",
                      fake_httpx(200, {"status": "blocked", "blocklist_size": 5,
                                       "agent_did": "did:x:victim"},
                                 urls=captured_url, headers_seen=captured_headers,
                                 payloads=captured_payload)):
        r = client.post(
            "/api/v1/federation/admin/agents/did:x:victim/block",
            json={"reason": "remote frame request", "actor": "Frame B reactor"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "blocked"
    assert body["agent_did"] == "did:x:victim"
    assert body["federation_identity"] == "spiffe://test.local/peer/registry-b"
    # Verify proxy hit the local TEG with the admin key
    assert captured_url[0] == "http://teg-layer:8080/api/v1/cross-teg/admin/agents/did:x:victim/block"
    assert captured_headers[0]["Authorization"] == "Bearer secret-teg-key"
    # Federation identity is stamped into the audit reason
    assert "federation:spiffe://test.local/peer/registry-b" in captured_payload[0]["reason"]


def test_unblock_uses_unblock_path(client, monkeypatch):
    monkeypatch.setenv("TEG_API_BASE_URL", "http://teg-layer:8080")
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "secret-teg-key")

    captured_url = []

    with patch.object(federation_blocklist.httpx, "AsyncClient",
                      fake_httpx(200, {"status": "unblocked"}, urls=captured_url)):
        r = client.post(
            "/api/v1/federation/admin/agents/did:x:happy/unblock",
            json={"reason": "reinstated", "actor": "Frame B reactor"},
        )

    assert r.status_code == 200
    assert captured_url[0].endswith("/unblock")


def test_block_without_admin_key_still_proxies_under_mtls(client, monkeypatch):
    """§CHATCOHERE-CI (2026-09-01) — this asserted a 500 when TEG_ADMIN_API_KEY was
    unset, and the router deliberately stopped requiring it.

    The Phase-4 registry-tail change dials the local TEG over mTLS: the TEG
    authorizes on the registry's SPIFFE client cert, and the legacy Bearer key is
    attached ONLY if still configured and is ignored under mTLS. A hard 500 on a
    missing key would now BREAK a correctly-configured enforce deployment.

    So the assertion is inverted to the real contract, and — the part that matters —
    it pins that the header is simply ABSENT rather than sent empty, because
    `Authorization: Bearer ` is a different and worse thing to send than nothing.
    """
    monkeypatch.delenv("TEG_ADMIN_API_KEY", raising=False)
    seen_headers = []
    with patch.object(federation_blocklist.httpx, "AsyncClient",
                      fake_httpx(200, {"status": "blocked"}, headers_seen=seen_headers)):
        r = client.post(
            "/api/v1/federation/admin/agents/did:x:y/block",
            json={"reason": "x", "actor": "y"},
        )
    assert r.status_code == 200
    assert "Authorization" not in seen_headers[0]


def test_block_returns_502_when_local_teg_errors(client, monkeypatch):
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "k")

    with patch.object(federation_blocklist.httpx, "AsyncClient",
                      fake_httpx(503, {}, body_text="TEG unavailable")):
        r = client.post(
            "/api/v1/federation/admin/agents/did:x:y/block",
            json={"reason": "x", "actor": "y"},
        )
    assert r.status_code == 502
    assert "Local TEG returned 503" in r.json()["detail"]


def test_block_returns_502_on_network_error(client, monkeypatch):
    """A transport failure during the proxy call → 502 Bad Gateway.

    ⚠ The router catches `httpx.HTTPError` now; raising `aiohttp.ClientError`
    would sail past that except and surface as a 500, so this control has to
    speak the client library the code actually uses.
    """
    import httpx as _httpx
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "k")

    with patch.object(federation_blocklist.httpx, "AsyncClient",
                      fake_httpx(raises=_httpx.ConnectError("connection refused"))):
        r = client.post(
            "/api/v1/federation/admin/agents/did:x:y/block",
            json={"reason": "x", "actor": "y"},
        )
    assert r.status_code == 502
    assert "Local TEG unreachable" in r.json()["detail"]


def test_block_uses_default_body_when_omitted(client, monkeypatch):
    monkeypatch.setenv("TEG_ADMIN_API_KEY", "k")
    captured_payload = []

    with patch.object(federation_blocklist.httpx, "AsyncClient",
                      fake_httpx(200, {"status": "blocked", "blocklist_size": 1},
                                 payloads=captured_payload)):
        r = client.post("/api/v1/federation/admin/agents/did:x:y/block")
    assert r.status_code == 200
    # Default body fills in reason + actor
    assert "reason" in captured_payload[0]
    assert "actor" in captured_payload[0]
