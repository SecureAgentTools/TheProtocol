"""§FEFRAME W2: CORS follows federation membership, never credentials (core/federation_cors.py).

Measured before W2 (2026-09-30): EU allowed only its own hosts (so ASIA's console could not read EU), and every
operator ran the config default ["*"] WITH credentials. Each test drives Starlette's real CORS code through the
subclass; the controls are an origin the manifest does not name, and the old credentialed wildcard.
"""
import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from agentvault_registry.core import federation_cors as fc


def _app(allow_all=False):
    app = Starlette(routes=[Route("/api/v1/x", lambda r: PlainTextResponse("ok"))])
    app.add_middleware(fc.FederationCORSMiddleware, allow_all=allow_all)
    return TestClient(app)


@pytest.fixture
def env(monkeypatch):
    for k in ("ALLOWED_ORIGINS", "CORS_ALLOW_ALL_ORIGINS", "PUBLIC_UI_URL", "PUBLIC_URL"):
        monkeypatch.delenv(k, raising=False)
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", "http://localhost:8000", raising=False)
    return monkeypatch


def test_own_explicit_and_peer_origins(env):
    env.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    env.setenv("PUBLIC_URL", "https://eu.theprotocol.cloud")
    env.setenv("ALLOWED_ORIGINS", '["https://registry.theprotocol.cloud/", "https://api.theprotocol.cloud"]')
    s = fc.compute(["https://asia.theprotocol.cloud", "https://amsterdam.op.theprotocol.cloud"])
    assert s == {"https://theprotocol.cloud", "https://eu.theprotocol.cloud", "https://registry.theprotocol.cloud",
                 "https://api.theprotocol.cloud", "https://asia.theprotocol.cloud",
                 "https://amsterdam.op.theprotocol.cloud"}
    # a trailing slash in the env (pydantic's AnyHttpUrl adds one) is reduced to the origin a browser sends
    assert "https://registry.theprotocol.cloud/" not in s


def test_a_peer_origin_reads_without_credentials_and_a_stranger_does_not(env):
    env.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    fc._set(fc.compute(["https://asia.theprotocol.cloud"]))
    c = _app()
    pre = c.options("/api/v1/x", headers={"Origin": "https://asia.theprotocol.cloud",
                                          "Access-Control-Request-Method": "POST",
                                          "Access-Control-Request-Headers": "authorization,content-type"})
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == "https://asia.theprotocol.cloud"
    assert "access-control-allow-credentials" not in pre.headers
    g = c.get("/api/v1/x", headers={"Origin": "https://asia.theprotocol.cloud"})
    assert g.headers["access-control-allow-origin"] == "https://asia.theprotocol.cloud"
    assert "access-control-allow-credentials" not in g.headers
    # the control: an origin no peer and no setting names
    bad = c.options("/api/v1/x", headers={"Origin": "https://evil.example.com",
                                          "Access-Control-Request-Method": "POST"})
    assert bad.status_code == 400
    assert "access-control-allow-origin" not in bad.headers
    g2 = c.get("/api/v1/x", headers={"Origin": "https://evil.example.com"})
    assert "access-control-allow-origin" not in g2.headers



def test_a_peer_console_can_read_the_replay_mark(env):
    """§REPATLANE-7: the mark on an answer given again under the same Idempotency-Key is exposed to an allowed origin, so
    a peer frame's console reading the answer across origins sees it; the header names the cache module's constant."""
    from agentvault_registry.services.idempotency.cache import REPLAYED_HEADER
    assert REPLAYED_HEADER in fc.EXPOSED_HEADERS
    env.setenv("PUBLIC_UI_URL", "https://theprotocol.cloud")
    fc._set(fc.compute(["https://asia.theprotocol.cloud"]))
    app = Starlette(routes=[Route("/api/v1/x", lambda r: PlainTextResponse("ok", headers={REPLAYED_HEADER: "true"}))])
    app.add_middleware(fc.FederationCORSMiddleware)
    g = TestClient(app).get("/api/v1/x", headers={"Origin": "https://asia.theprotocol.cloud"})
    assert g.headers["access-control-allow-origin"] == "https://asia.theprotocol.cloud"
    exposed = [h.strip().lower() for h in g.headers.get("access-control-expose-headers", "").split(",")]
    assert REPLAYED_HEADER.lower() in exposed
    assert g.headers[REPLAYED_HEADER] == "true"
    assert "access-control-allow-credentials" not in g.headers

def test_the_config_default_is_not_a_wildcard(env):
    """An operator with no ALLOWED_ORIGINS in its environment used to answer any origin WITH credentials."""
    assert fc.wildcard_requested() is False
    env.setenv("ALLOWED_ORIGINS", '["*"]')
    assert fc.wildcard_requested() is True
    env.delenv("ALLOWED_ORIGINS")
    env.setenv("CORS_ALLOW_ALL_ORIGINS", "true")
    assert fc.wildcard_requested() is True


def test_an_explicit_wildcard_still_carries_no_credentials(env):
    c = _app(allow_all=True)
    g = c.get("/api/v1/x", headers={"Origin": "https://anyone.example.com"})
    assert g.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in g.headers


async def test_a_failed_refresh_keeps_the_previous_set(env, monkeypatch):
    fc._set(frozenset({"https://asia.theprotocol.cloud"}))

    async def boom(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(fc.fv, "build_manifest", boom)
    out = await fc.refresh_once()
    assert "https://asia.theprotocol.cloud" in out
