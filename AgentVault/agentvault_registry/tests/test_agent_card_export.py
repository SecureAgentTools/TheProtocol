"""Tests for the Option C Phase 2 agent card-export endpoint.

Exercises the stripping + canonicalisation logic in isolation (no DB).
Live end-to-end verification happens against sandbox-A via curl during
Phase 2 deploy (see SESSION_LOG_2026-05-17_OPTION_C_PHASE_2.md).
"""
from agentvault_registry.routers import agent_discovery
from agentvault_registry.services.a2a_v1.compat import canonicalize_card_data


def _registry_card_with_enrichment():
    """A realistic stored card_data with both agent-owned and registry-owned fields."""
    return {
        # agent-owned
        "protocolVersion": "1.0",
        "humanReadableId": "test-agent",
        "agentVersion": "1.0.0",
        "name": "Test Agent",
        "description": "agent-canonical metadata",
        "provider": {"name": "TheProtocol"},
        "capabilities": {"streaming": False},
        "supportedInterfaces": [
            {"url": "https://agent.example.com/a2a", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "securitySchemes": {"agent_jwt": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}},
        "security": [{"agent_jwt": []}],
        # registry-owned enrichment that MUST be stripped
        "federation_metadata": {
            "origin_registry": "Registry-A",
            "source_registry": "spiffe://agentvault.com/registry-a",
            "last_synced_at": "2026-05-17T12:00:00Z",
        },
        "flare": {
            "tier": "sentinel",
            "encirclement_variant": "blackhole",
            "granted_at": "2026-05-01T00:00:00Z",
        },
        "last_pulled_at": "2026-05-17T18:00:00Z",
        "last_pulled_etag": '"deadbeef"',
    }


def test_registry_owned_fields_constant_includes_expected_keys():
    """The stripping constant must cover every registry-canonical key."""
    expected = {"federation_metadata", "flare", "last_pulled_at", "last_pulled_etag"}
    assert agent_discovery._REGISTRY_OWNED_FIELDS == expected


def test_stripping_removes_registry_owned_fields():
    """The endpoint's strip logic (mirror) must drop federation_metadata + flare + last_pulled_*."""
    stored = _registry_card_with_enrichment()
    canonical = canonicalize_card_data(stored)
    stripped = {k: v for k, v in canonical.items() if k not in agent_discovery._REGISTRY_OWNED_FIELDS}

    assert "federation_metadata" not in stripped
    assert "flare" not in stripped
    assert "last_pulled_at" not in stripped
    assert "last_pulled_etag" not in stripped


def test_stripping_preserves_agent_owned_fields():
    """All agent-owned fields survive the strip."""
    stored = _registry_card_with_enrichment()
    canonical = canonicalize_card_data(stored)
    stripped = {k: v for k, v in canonical.items() if k not in agent_discovery._REGISTRY_OWNED_FIELDS}

    assert stripped["name"] == "Test Agent"
    assert stripped["protocolVersion"] == "1.0"
    assert stripped["supportedInterfaces"][0]["url"] == "https://agent.example.com/a2a"
    assert "securitySchemes" in stripped
    assert "security" in stripped
    assert "capabilities" in stripped
    assert "provider" in stripped


def test_canonicalize_v03_only_card_derives_v1():
    """A v0.3-only card_data passes through canonicalize and emerges with v1 fields."""
    v03 = {
        "schemaVersion": "0.3.0",
        "humanReadableId": "legacy",
        "agentVersion": "0.9.0",
        "name": "Legacy",
        "description": "v0.3 agent",
        "url": "https://legacy.example.com",
        "preferredTransport": "JSONRPC",
        "provider": {"name": "test"},
        "capabilities": {"a2aVersion": "0.3.0"},
        "authSchemes": [{"scheme": "bearer"}],
    }
    canonical = canonicalize_card_data(v03)
    # canonicalize should derive v1 fields
    assert "supportedInterfaces" in canonical
    assert "securitySchemes" in canonical
    assert "security" in canonical


def test_stripping_is_no_op_when_no_registry_fields():
    """A card with no registry-owned enrichment passes through unchanged after strip."""
    pure_agent = {
        "protocolVersion": "1.0",
        "name": "pure",
        "agentVersion": "1.0.0",
        "humanReadableId": "pure",
        "description": "no enrichment",
        "provider": {"name": "test"},
        "capabilities": {"streaming": False},
        "supportedInterfaces": [
            {"url": "https://x.example.com", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}
        ],
        "securitySchemes": {"j": {"type": "http", "scheme": "bearer"}},
        "security": [{"j": []}],
    }
    canonical = canonicalize_card_data(pure_agent)
    stripped = {k: v for k, v in canonical.items() if k not in agent_discovery._REGISTRY_OWNED_FIELDS}
    assert stripped == canonical
