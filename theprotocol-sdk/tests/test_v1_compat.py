"""Q-C W3 (2026-05-12) — v1_compat.py extensions for A2A v1.0 alignment.

Covers:
- Part `kind` discriminator (A2A v1.0 §4.7)
- v0.3 authSchemes ↔ v1.0 securitySchemes translation (§4.5)
- AgentCard v0.3 ↔ v1.0 dual-shape converters
"""
from __future__ import annotations

import pytest

from theprotocol.models.a2a_protocol import TextPart, FilePart, DataPart
from theprotocol.models.v1_compat import (
    part_from_v1,
    part_to_v1,
    security_schemes_from_v03_auth_schemes,
    security_schemes_to_v03_auth_schemes,
    agent_card_from_v03,
    agent_card_to_v03,
)


# ─── Part kind discriminator ─────────────────────────────────────────────────


class TestPartKindDiscriminator:
    def test_text_kind_read(self):
        p = part_from_v1({"kind": "text", "text": "hello"})
        assert isinstance(p, TextPart)
        assert p.content == "hello"

    def test_file_kind_read_nested(self):
        p = part_from_v1({
            "kind": "file",
            "file": {"url": "https://x.test/a.png", "mediaType": "image/png", "name": "a.png"},
        })
        assert isinstance(p, FilePart)
        assert str(p.url) == "https://x.test/a.png"
        assert p.media_type == "image/png"
        assert p.filename == "a.png"

    def test_data_kind_read(self):
        p = part_from_v1({"kind": "data", "data": {"foo": "bar"}})
        assert isinstance(p, DataPart)
        assert p.content == {"foo": "bar"}

    def test_text_kind_emit(self):
        out = part_to_v1(TextPart(content="hi"), kind_discriminator=True)
        assert out == {"kind": "text", "text": "hi"}

    def test_file_kind_emit(self):
        out = part_to_v1(
            FilePart(url="https://y.test/b.pdf", mediaType="application/pdf", filename="b.pdf"),
            kind_discriminator=True,
        )
        assert out == {
            "kind": "file",
            "file": {"url": "https://y.test/b.pdf", "mediaType": "application/pdf", "name": "b.pdf"},
        }

    def test_data_kind_emit(self):
        out = part_to_v1(
            DataPart(content={"a": 1}, mediaType="application/json"),
            kind_discriminator=True,
        )
        assert out == {"kind": "data", "data": {"a": 1}}

    def test_legacy_default_no_regression(self):
        out = part_to_v1(TextPart(content="legacy"))
        assert out == {"text": "legacy"}
        assert "kind" not in out

    def test_legacy_field_presence_still_works(self):
        p = part_from_v1({"text": "still works"})
        assert isinstance(p, TextPart)
        assert p.content == "still works"


# ─── SecurityScheme translation ───────────────────────────────────────────────


class TestSecuritySchemes:
    def test_oauth2_v03_to_v1(self):
        derived = security_schemes_from_v03_auth_schemes(
            [{"scheme": "oauth2", "tokenUrl": "https://x.test/token"}]
        )
        assert "oauth2_agent_jwt" in derived["securitySchemes"]
        scheme = derived["securitySchemes"]["oauth2_agent_jwt"]
        assert scheme["type"] == "oauth2"
        assert scheme["flows"]["clientCredentials"]["tokenUrl"] == "https://x.test/token"
        assert derived["security"] == [{"oauth2_agent_jwt": []}]

    def test_apikey_v03_to_v1(self):
        derived = security_schemes_from_v03_auth_schemes(
            [{"scheme": "apiKey", "name": "X-Custom-Header"}]
        )
        assert derived["securitySchemes"]["api_key"]["type"] == "apiKey"
        assert derived["securitySchemes"]["api_key"]["name"] == "X-Custom-Header"

    def test_bearer_v03_to_v1(self):
        derived = security_schemes_from_v03_auth_schemes([{"scheme": "bearer"}])
        assert derived["securitySchemes"]["bearer"]["type"] == "http"
        assert derived["securitySchemes"]["bearer"]["scheme"] == "bearer"

    def test_mtls_v03_to_v1_native(self):
        """v0.3 mtls maps to A2A v1.0 native MutualTlsSecurityScheme (§4.5.6)."""
        derived = security_schemes_from_v03_auth_schemes([{"scheme": "mtls"}])
        assert derived["securitySchemes"]["mtls"]["type"] == "mutualTLS"

    def test_none_scheme_drops(self):
        derived = security_schemes_from_v03_auth_schemes([{"scheme": "none"}])
        assert derived["securitySchemes"] == {}
        assert derived["security"] == []

    def test_v1_to_v03_oauth2_reverse(self):
        v1_schemes = {
            "agent_jwt": {
                "type": "oauth2",
                "flows": {"clientCredentials": {"tokenUrl": "https://r.test/token", "scopes": {}}},
            }
        }
        v03 = security_schemes_to_v03_auth_schemes(v1_schemes, [{"agent_jwt": []}])
        assert v03[0]["scheme"] == "oauth2"
        assert v03[0]["tokenUrl"] == "https://r.test/token"

    def test_v1_to_v03_mtls_reverse(self):
        v1_schemes = {"mtls": {"type": "mutualTLS"}}
        v03 = security_schemes_to_v03_auth_schemes(v1_schemes, [{"mtls": []}])
        assert v03[0]["scheme"] == "mtls"

    def test_empty_v1_emits_none(self):
        v03 = security_schemes_to_v03_auth_schemes({}, [])
        assert v03 == [{
            "scheme": "none", "scopes": None, "tokenUrl": None,
            "description": None, "service_identifier": None,
        }]


# ─── AgentCard converters ─────────────────────────────────────────────────────


class TestAgentCardConverters:
    def test_v03_canonicalizes_to_dual_shape(self):
        v03 = {
            "protocolVersion": "0.3.0",
            "name": "Test",
            "url": "https://t.test/",
            "authSchemes": [{"scheme": "oauth2", "tokenUrl": "https://t.test/token"}],
        }
        v1 = agent_card_from_v03(v03)
        assert v1["protocolVersion"] == "1.0"
        assert v1["schemaVersion"] == "0.3.0"
        assert v1["supportedInterfaces"][0]["url"] == "https://t.test/"
        assert "oauth2_agent_jwt" in v1["securitySchemes"]
        # v0.3 fields preserved (6-month transition)
        assert "authSchemes" in v1
        assert "url" in v1

    def test_idempotent_on_v1_card(self):
        v1 = {
            "protocolVersion": "1.0",
            "name": "V1",
            "supportedInterfaces": [{"url": "https://u.test/", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "securitySchemes": {"agent_jwt": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "https://u.test/token", "scopes": {}}}}},
            "security": [{"agent_jwt": []}],
        }
        v1_again = agent_card_from_v03(v1)
        assert v1_again["protocolVersion"] == "1.0"
        # didn't blow away pre-existing v1.0 fields
        assert v1_again["securitySchemes"] == v1["securitySchemes"]

    def test_strict_v03_emit_strips_v1_fields(self):
        v1 = {
            "protocolVersion": "1.0",
            "name": "V1",
            "supportedInterfaces": [{"url": "https://u.test/", "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "securitySchemes": {"agent_jwt": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "https://u.test/token", "scopes": {}}}}},
            "security": [{"agent_jwt": []}],
            "extensions": [{"uri": "https://example.test/ext/v1"}],
        }
        v03 = agent_card_to_v03(v1)
        assert v03["protocolVersion"] == "0.3.0"
        assert "supportedInterfaces" not in v03
        assert "securitySchemes" not in v03
        assert "security" not in v03
        assert "extensions" not in v03
        # v0.3 fields reconstituted
        assert v03["url"] == "https://u.test/"
        assert v03["authSchemes"][0]["scheme"] == "oauth2"
        assert v03["authSchemes"][0]["tokenUrl"] == "https://u.test/token"
