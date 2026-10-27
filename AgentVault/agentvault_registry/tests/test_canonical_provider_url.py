"""D6-814, the source (agentvault2-d6, 2026-10-23): the A2A v1.0 canonicaliser never writes a provider url "" when the card
names a URL anywhere.

Measured on production (agentvault2-56, closing D6-445): EU's saves of SYBIL's and ten showcase agents' cards stored
provider {"name": ..., "organization": ..., "url": ""}: canonicalize_card_data filled a missing provider url from the v0.3
top-level url, which a v1.0 card does not carry (its endpoint is supportedInterfaces[0].url), so it wrote "", and kept an
agent's own "" as it was. ASIA's fail-closed ingest refuses "" (the library's AgentProvider.url is an HttpUrl): 27
refusals in six minutes. Red on the code before this fix (the v1.0 and the empty-url cases).
"""
from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://t:t@localhost:5432/t")
os.environ.setdefault("API_KEY_SECRET", "test-only-secret-value-0123456789abcdef")

ENDPOINT = "https://agent.example.test/a2a"


def _v1(provider):
    return {"protocolVersion": "1.0", "humanReadableId": "probe/sundial", "agentVersion": "1.0.0", "name": "Sundial",
            "description": "probe", "provider": provider, "capabilities": {},
            "supportedInterfaces": [{"url": ENDPOINT, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}],
            "securitySchemes": {"key": {"type": "apiKey", "in": "header", "name": "X-Sundial-Key"}},
            "security": [{"key": []}]}


def _canon(cd):
    from agentvault_registry.services.a2a_v1.compat import canonicalize_card_data
    return canonicalize_card_data(cd)["provider"]


def _library_accepts(prov):
    from agentvault.models.agent_card import AgentProvider
    AgentProvider.model_validate(prov)


def test_a_v1_card_without_a_provider_url_takes_its_endpoint():
    prov = _canon(_v1({"name": "TheProtocol"}))
    assert prov["url"] == ENDPOINT and prov["organization"] == "TheProtocol"
    _library_accepts(prov)


def test_an_empty_provider_url_counts_as_none():
    prov = _canon(_v1({"name": "TheProtocol", "url": ""}))
    assert prov["url"] == ENDPOINT
    _library_accepts(prov)


def test_an_agents_own_provider_url_wins():
    prov = _canon(_v1({"name": "TheProtocol", "url": "https://theprotocol.cloud"}))
    assert prov["url"] == "https://theprotocol.cloud"


def test_a_v03_card_still_takes_its_top_level_url():
    cd = _v1({"name": "TheProtocol"})
    cd["url"] = "https://legacy.example.test/a2a"
    assert _canon(cd)["url"] == "https://legacy.example.test/a2a"


def test_a_card_that_names_no_url_keeps_the_last_resort():
    cd = _v1({"name": "TheProtocol"})
    cd["supportedInterfaces"] = [{"protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]
    assert _canon(cd)["url"] == ""
