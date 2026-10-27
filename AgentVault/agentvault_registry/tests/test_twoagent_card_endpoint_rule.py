"""§TWOAGENT #12 / #22 (2026-09-23) — one endpoint rule for both places a card declares its endpoint, said on one line.

Measured in Stage 0 (V0425, both sessions): an http endpoint in the v0.3 `url` was refused "Agent URL must use HTTPS
unless it is localhost", while the SAME URL in `supportedInterfaces[].url` (where an A2A v1.0 card declares it) passed:
`SupportedInterface.url` was a bare `AnyUrl`. Live on EU and ASIA today: 3 active cards declare a non-localhost http
interface. The refusal was pydantic's multi-line repr (the rejected input, an external docs URL), it never said that
a sandbox registry accepts http, and the card VALIDATE route answered "An internal error occurred" for every
schema-invalid card.

Now `_check_endpoint_scheme` guards both fields, the refusal names where http is accepted, and the registry answers
`loc: message; …` at create, update and validate.

RED on V0430 (library AND registry mounted from 2be91334): the interface URL is accepted, the sentence helper does not
exist, the validate route says "An internal error occurred". The controls (https and localhost pass; the sandbox
accepts http; the existing `url` rule still refuses) pass on both trees.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError


def _card(**over):
    card = {
        "protocolVersion": "1.0", "humanReadableId": "twoagent-test/assay", "agentVersion": "1.0.0",
        "name": "Assay Desk", "description": "Assays samples for a fee.",
        "provider": {"name": "Straits"}, "capabilities": {"a2aVersion": "1.0", "streaming": False},
        "supportedInterfaces": [{"url": "https://assay.example/a2a", "protocolBinding": "JSONRPC"}],
        "securitySchemes": {}, "security": [],
    }
    card.update(over)
    return card


def _iface(url):
    return [{"url": url, "protocolBinding": "JSONRPC"}]


@pytest.fixture(autouse=True)
def _not_a_sandbox(monkeypatch):
    monkeypatch.delenv("SANDBOX_MODE", raising=False)
    monkeypatch.delenv("CC_TARGET_ENVIRONMENT", raising=False)


def test_an_interface_url_obeys_the_same_rule_as_url():
    from agentvault.models.agent_card import AgentCard
    with pytest.raises(ValidationError) as e:
        AgentCard.model_validate(_card(supportedInterfaces=_iface("http://agent.example/a2a")))
    assert "Interface URL must use HTTPS unless it is localhost" in str(e.value)
    assert "sandbox" in str(e.value)


def test_control_https_and_localhost_interfaces_pass_and_url_still_refuses():
    from agentvault.models.agent_card import AgentCard
    AgentCard.model_validate(_card())
    AgentCard.model_validate(_card(supportedInterfaces=_iface("http://localhost:8000/a2a")))
    with pytest.raises(ValidationError):
        AgentCard.model_validate(_card(url="http://agent.example/a2a"))


def test_control_a_sandbox_registry_accepts_http(monkeypatch):
    from agentvault.models.agent_card import AgentCard
    monkeypatch.setenv("SANDBOX_MODE", "true")
    AgentCard.model_validate(_card(supportedInterfaces=_iface("http://twoagent-b-assay:9100/a2a")))


def test_the_refusal_is_one_line_that_names_the_field():
    from agentvault.models.agent_card import AgentCard
    from agentvault_registry.crud.agent_card import card_validation_sentence
    with pytest.raises(ValidationError) as e:
        AgentCard.model_validate(_card(supportedInterfaces=_iface("http://agent.example/a2a"), name=None))
    s = card_validation_sentence(e.value)
    assert "supportedInterfaces.0.url: Interface URL must use HTTPS" in s and "name: " in s
    assert "\n" not in s and "errors.pydantic.dev" not in s and "input_value" not in s


async def test_create_refuses_with_the_sentence():
    from agentvault_registry import schemas
    from agentvault_registry.crud.agent_card import create_agent_card
    with pytest.raises(ValueError) as e:
        await create_agent_card(None, 1, schemas.AgentCardCreate(
            card_data=_card(supportedInterfaces=_iface("http://agent.example/a2a"))))
    assert "supportedInterfaces.0.url" in str(e.value) and "errors.pydantic.dev" not in str(e.value)


async def test_the_validate_route_says_what_is_wrong():
    from agentvault_registry import schemas
    from agentvault_registry.routers.utils import validate_agent_card
    out = await validate_agent_card(schemas.AgentCardValidationRequest(card_data=_card(provider={})))
    assert out.is_valid is False
    assert out.detail != "An internal error occurred" and "provider.name" in (out.detail or "")
