"""Tests for serve_well_known_card() (Option C Phase 1)."""

import asyncio
import json
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from theprotocol.agent import serve_well_known_card
from theprotocol.models import AgentCard
from theprotocol.models.agent_card import (
    AgentProvider, AgentCapabilities, SupportedInterface,
)


def _sample_card() -> AgentCard:
    return AgentCard(
        protocolVersion="1.0",
        humanReadableId="test-agent",
        agentVersion="1.0.0",
        name="Test Agent",
        description="A test agent for the well-known helper.",
        provider=AgentProvider(name="TheProtocol Test"),
        capabilities=AgentCapabilities(streaming=False),
        supportedInterfaces=[
            SupportedInterface(
                url="https://test-agent.example.com/a2a",
                protocolBinding="JSONRPC",
                protocolVersion="1.0",
            )
        ],
        securitySchemes={
            "agent_jwt": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
        },
        security=[{"agent_jwt": []}],
    )


# ──────────────────────────────────────────────────────────────────────────────
# 1. STATIC mode: 200 + valid JSON + ETag + Cache-Control
# ──────────────────────────────────────────────────────────────────────────────


def test_static_mode_returns_200_with_card_json():
    app = FastAPI()
    serve_well_known_card(app, card=_sample_card())
    client = TestClient(app)

    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/json")
    assert r.headers.get("cache-control", "").startswith("public, max-age=")
    assert r.headers.get("etag", "").startswith('"')
    assert r.headers.get("access-control-allow-origin") == "*"

    data = r.json()
    assert data["name"] == "Test Agent"
    assert data["protocolVersion"] == "1.0"
    assert isinstance(data["supportedInterfaces"], list)
    assert data["supportedInterfaces"][0]["url"].startswith("https://test-agent.example.com")


# ──────────────────────────────────────────────────────────────────────────────
# 2. Legacy alias /agent.json returns same content
# ──────────────────────────────────────────────────────────────────────────────


def test_legacy_alias_returns_same_content():
    app = FastAPI()
    serve_well_known_card(app, card=_sample_card())
    client = TestClient(app)

    canonical = client.get("/.well-known/agent-card.json")
    legacy = client.get("/.well-known/agent.json")
    assert canonical.status_code == 200
    assert legacy.status_code == 200
    assert canonical.json() == legacy.json()
    assert canonical.headers.get("etag") == legacy.headers.get("etag")


# ──────────────────────────────────────────────────────────────────────────────
# 3. Strips registry-owned fields (federation_metadata, flare)
# ──────────────────────────────────────────────────────────────────────────────


def test_strips_federation_metadata_and_flare():
    app = FastAPI()
    # Pass a plain dict with extra fields — they should NOT appear in output.
    raw = {
        "protocolVersion": "1.0",
        "humanReadableId": "stripper",
        "agentVersion": "1.0.0",
        "name": "Stripper",
        "description": "Has stuff that should be stripped",
        "provider": {"name": "test"},
        "capabilities": {"streaming": False},
        "supportedInterfaces": [
            {"url": "https://x.example.com", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "securitySchemes": {"j": {"type": "http", "scheme": "bearer"}},
        "security": [{"j": []}],
        "federation_metadata": {"origin_registry": "Registry-A", "source_registry": "spiffe://x"},
        "flare": {"tier": "founder", "encirclement": "blackhole"},
        "last_pulled_at": "2026-05-17T12:00:00Z",
    }
    serve_well_known_card(app, card=raw)
    client = TestClient(app)

    body = client.get("/.well-known/agent-card.json").json()
    assert "federation_metadata" not in body
    assert "flare" not in body
    assert "last_pulled_at" not in body
    # But agent-owned fields stay
    assert body["name"] == "Stripper"
    # Plain dict input is passed through as-is (no AnyUrl normalization).
    assert body["supportedInterfaces"][0]["url"] == "https://x.example.com"


# ──────────────────────────────────────────────────────────────────────────────
# 4. ETag matching → 304 Not Modified
# ──────────────────────────────────────────────────────────────────────────────


def test_etag_304_short_circuit():
    app = FastAPI()
    serve_well_known_card(app, card=_sample_card())
    client = TestClient(app)

    r1 = client.get("/.well-known/agent-card.json")
    etag = r1.headers["etag"]

    r2 = client.get("/.well-known/agent-card.json", headers={"If-None-Match": etag})
    assert r2.status_code == 304
    assert r2.content == b""  # 304 must not include a body
    # Headers still present for caching layers to refresh max-age
    assert r2.headers.get("etag") == etag
    assert r2.headers.get("access-control-allow-origin") == "*"


# ──────────────────────────────────────────────────────────────────────────────
# 5. CORS preflight on OPTIONS
# ──────────────────────────────────────────────────────────────────────────────


def test_cors_preflight_options():
    app = FastAPI()
    serve_well_known_card(app, card=_sample_card())
    client = TestClient(app)

    r = client.options("/.well-known/agent-card.json")
    assert r.status_code == 200
    assert r.headers.get("access-control-allow-origin") == "*"
    assert "GET" in r.headers.get("access-control-allow-methods", "")

    r2 = client.options("/.well-known/agent.json")
    assert r2.status_code == 200
    assert r2.headers.get("access-control-allow-origin") == "*"


# ──────────────────────────────────────────────────────────────────────────────
# 6. FEDERATED mode: mocked upstream 200 → card served
# ──────────────────────────────────────────────────────────────────────────────


def test_federated_mode_with_mock_registry():
    import respx
    import httpx

    fetch_url = "https://registry.example.com/api/v1/agents/did:test:1/card-export"

    upstream_card = {
        "protocolVersion": "1.0",
        "humanReadableId": "fed-agent",
        "agentVersion": "1.0.0",
        "name": "Federated Agent",
        "description": "Pulled from registry",
        "provider": {"name": "test"},
        "capabilities": {"streaming": False},
        "supportedInterfaces": [
            {"url": "https://fed.example.com", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "securitySchemes": {"j": {"type": "http", "scheme": "bearer"}},
        "security": [{"j": []}],
        # The registry's card-export already strips these, but defend anyway:
        "federation_metadata": {"hijack": "attempt"},
    }

    with respx.mock(base_url="https://registry.example.com") as mock:
        mock.get("/api/v1/agents/did:test:1/card-export").mock(
            return_value=httpx.Response(200, json=upstream_card)
        )

        app = FastAPI()
        serve_well_known_card(app, fetch_url=fetch_url, refresh_seconds=999999)

        with TestClient(app) as client:
            # TestClient context manager triggers startup events
            r = client.get("/.well-known/agent-card.json")
            assert r.status_code == 200
            body = r.json()
            assert body["name"] == "Federated Agent"
            assert "federation_metadata" not in body


# ──────────────────────────────────────────────────────────────────────────────
# 7. FEDERATED mode: upstream 5xx → 503 with Retry-After
# ──────────────────────────────────────────────────────────────────────────────


def test_federated_mode_upstream_failure_returns_503():
    import respx
    import httpx

    fetch_url = "https://registry.example.com/api/v1/agents/did:bad/card-export"

    with respx.mock(base_url="https://registry.example.com") as mock:
        mock.get("/api/v1/agents/did:bad/card-export").mock(
            return_value=httpx.Response(502, text="Bad Gateway")
        )

        app = FastAPI()
        serve_well_known_card(app, fetch_url=fetch_url, refresh_seconds=999999)

        with TestClient(app) as client:
            r = client.get("/.well-known/agent-card.json")
            assert r.status_code == 503
            assert r.headers.get("retry-after") == "30"
            body = r.json()
            assert "error" in body


# ──────────────────────────────────────────────────────────────────────────────
# 8. sign_with signs the static card; a key that cannot be used serves it unsigned
# ──────────────────────────────────────────────────────────────────────────────


def test_sign_with_a_key_that_cannot_be_used_serves_the_card_unsigned():
    app = FastAPI()
    serve_well_known_card(
        app,
        card=_sample_card(),
        sign_with={"private_pem": "fake-pem", "kid": "did:test:1#1"},
    )
    client = TestClient(app)
    r = client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    body = r.json()
    # the PEM does not load: the warning is logged and the card is served without signatures
    assert "signatures" not in body


def test_sign_with_signs_the_static_card():
    pytest.importorskip("cryptography")
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from theprotocol.auth import verify_agent_card

    priv = Ed25519PrivateKey.generate()
    pem = priv.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode()
    raw = priv.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    jwk = {"kty": "OKP", "crv": "Ed25519", "x": base64.urlsafe_b64encode(raw).rstrip(b"=").decode()}

    app = FastAPI()
    serve_well_known_card(app, card=_sample_card(), sign_with={"private_pem": pem, "kid": "did:test:1#1"})
    body = TestClient(app).get("/.well-known/agent-card.json").json()
    assert len(body["signatures"]) == 1
    assert verify_agent_card(body, jwk) == (True, None)


# ──────────────────────────────────────────────────────────────────────────────
# 9. Misuse: passing both card and fetch_url raises (mutually exclusive)
# ──────────────────────────────────────────────────────────────────────────────


def test_card_and_fetch_url_mutually_exclusive():
    app = FastAPI()
    with pytest.raises(ValueError):
        serve_well_known_card(
            app,
            card=_sample_card(),
            fetch_url="https://x.example.com/whatever",
        )

    app2 = FastAPI()
    with pytest.raises(ValueError):
        serve_well_known_card(app2)  # neither
