"""V0650 (n): the dev machine's V0649 outside re-check (order gwo_108bf148564e182c77539381), three of its four findings.

(a) the downloads manifest gave CLAUDE.md the template's size while the download is rendered per request, so a client
    that checked the one against the other refused an honest file;
(c) create_agent's registry_url and the served manual's registry URL were two addresses for one registry (EU's
    credentials said https://theprotocol.cloud, its manual https://eu.theprotocol.cloud);
(d) the external enable-mtls answer carried docker_label, a label for a container on the registry's own host.
The fourth, (b), is the two stdio bridges' initialize, in the stack (tests/bridges/bridge_initialize.test.mjs there).
"""
import hashlib
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.routers import agent_mtls, downloads

TEMPLATE = (
    "# Operator manual\n\n<!-- LIVE_FACTS -->\n\n"
    "Sign in: `curl -X POST {REGISTRY_URL}/api/v1/auth/login`\n"
    "Your agents: `curl {REGISTRY_URL}/api/v1/developers/me/agents`\n"
)
BRIDGE = b"#!/usr/bin/env node\n// a bridge\nconsole.log('hello');\n"
ADMIN_BRIDGE = b"#!/usr/bin/env node\n// the admin bridge\n"


@pytest.fixture
def served(tmp_path, monkeypatch):
    (tmp_path / "operator-CLAUDE.md").write_text(TEMPLATE, encoding="utf-8")
    (tmp_path / "mcp-stdio-bridge.js").write_bytes(BRIDGE)
    (tmp_path / "mcp-stdio-bridge-admin.js").write_bytes(ADMIN_BRIDGE)
    monkeypatch.setattr(downloads, "_DOWNLOADS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(downloads.router)
    return TestClient(app), tmp_path


def _configure(monkeypatch, *, base, ui=None, public=None):
    from agentvault_registry.config import settings
    monkeypatch.setattr(settings, "BASE_URL", base, raising=False)
    for name, value in (("PUBLIC_UI_URL", ui), ("PUBLIC_URL", public)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _entry(client, name):
    files = client.get("/api/v1/downloads/manifest").json()["files"]
    return next(f for f in files if f["filename"] == name)


# ── (a) the manifest gives only numbers a download can match ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["mcp-stdio-bridge.js", "mcp-stdio-bridge-admin.js"])
def test_a_file_served_as_stored_matches_its_manifest_size_and_digest(served, name):
    client, _ = served
    body = client.get(f"/api/v1/downloads/{name}").content
    e = _entry(client, name)
    assert e["available"] is True and e["rendered_per_request"] is False
    assert e["size_bytes"] == len(body)
    assert e["sha256"] == hashlib.sha256(body).hexdigest()


def test_the_rendered_manual_gives_no_size_or_digest_a_download_cannot_match(served, monkeypatch):
    client, folder = served
    _configure(monkeypatch, base="https://eu.theprotocol.cloud", ui="https://theprotocol.cloud")
    body = client.get("/api/v1/downloads/CLAUDE.md").content
    stored = (folder / "operator-CLAUDE.md").read_bytes()
    assert body != stored and len(body) != len(stored)   # rendered per request: no download equals the stored file
    e = _entry(client, "CLAUDE.md")
    assert e["rendered_per_request"] is True
    assert e["size_bytes"] is None and e["sha256"] is None
    # the template's own numbers, under keys of their own: true of the build input, never offered as the download's
    assert e["template_size_bytes"] == len(stored)
    assert e["template_sha256"] == hashlib.sha256(stored).hexdigest()


def test_a_missing_file_gives_no_numbers(served):
    client, folder = served
    (folder / "mcp-stdio-bridge-admin.js").unlink()
    e = _entry(client, "mcp-stdio-bridge-admin.js")
    assert e["available"] is False and e["size_bytes"] is None and e["sha256"] is None


# ── (c) one registry URL: the manual names the address the credentials name ──────────────────────────────────────────

def test_the_manual_names_the_address_create_agent_returns(served, monkeypatch):
    from agentvault_registry.core.public_url import credential_home_url
    client, _ = served
    _configure(monkeypatch, base="https://eu.theprotocol.cloud", ui="https://theprotocol.cloud",
               public="https://eu.theprotocol.cloud")
    home = credential_home_url()   # what create_agent, a reset, a rotation, a spawn and a restore return as registry_url
    assert home == "https://theprotocol.cloud"
    text = client.get("/api/v1/downloads/CLAUDE.md").text
    assert f"{home}/api/v1/auth/login" in text and f"{home}/api/v1/developers/me/agents" in text
    assert "https://eu.theprotocol.cloud" not in text   # the API base names the same registry, but not the credentials' address


def test_where_no_address_is_configured_the_manual_keeps_the_requests_host(served, monkeypatch):
    client, _ = served
    _configure(monkeypatch, base="http://localhost:8000")   # the image default: loopback, rejected
    text = client.get("/api/v1/downloads/CLAUDE.md",
                      headers={"x-forwarded-host": "op.example.org", "x-forwarded-proto": "https"}).text
    assert "https://op.example.org/api/v1/auth/login" in text and "localhost" not in text


# ── (d) the external enable-mtls answer carries no docker_label ──────────────────────────────────────────────────────

def _enrolled():
    return {"status": "enrolled", "spiffe_id": "spiffe://example.org/agent/x", "enrolled_at": "2026-10-31T00:00:00+00:00",
            "docker_label": "com.theprotocol.agent-did:x"}


PREMINT = {"spiffe_id": "spiffe://example.org/agent/x", "svid_pem": "-", "key_pem": "-", "bundle_pem": "-",
           "ttl_seconds": 600, "ttl_capped_by_ca": False, "expires_at": "2026-10-31T00:10:00+00:00"}


@pytest.mark.parametrize("inline", [True, False])
def test_an_external_answer_carries_no_docker_label(monkeypatch, inline):
    monkeypatch.setattr(agent_mtls, "_inline_svid_enabled", lambda: inline)
    r = agent_mtls._attach_delivery(_enrolled(), None, "did:theprotocol:x", "x", premint=PREMINT,
                                    deployment="external", signal="public_network_source")
    assert r["deployment"] == "external" and r["delivery"] == ("inline" if inline else "unavailable")
    assert "docker_label" not in r


def test_the_on_host_answer_keeps_its_label_beside_the_instructions_that_use_it():
    r = agent_mtls._attach_delivery(_enrolled(), None, "did:theprotocol:x", "x",
                                    deployment="onbox", signal="internal_network_source")
    assert r["delivery"] == "workload_api" and r["docker_label"] == "com.theprotocol.agent-did:x"
    # the instructions name the label (V0649 wrote "label: value"; (j) writes "label=value"): the label, not its punctuation
    assert re.search(r"com\.theprotocol\.agent-did\s*[:=]\s*x\b", r["instructions"]), r["instructions"]
