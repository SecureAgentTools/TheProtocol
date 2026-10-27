"""D6-785: A2AClient calls an A2A v1.0 card (0.7.6).

A v1.0 card names its auth in securitySchemes (the ones `security` requires) and may name its endpoint only in
supportedInterfaces. Up to 0.7.5 the client iterated card.auth_schemes, None on such a card (TypeError), and called
card.url, None when only supportedInterfaces name it. It reads both shapes now; `security: []` needs no credential.
"""

import json
from urllib.parse import parse_qsl

import httpx
import pytest

from theprotocol.client import A2AClient, KeyManager
from theprotocol.exceptions import A2AAuthenticationError
from theprotocol.models import AgentCard, Message, TextPart

AGENT_URL = "https://agent.example/a2a"
TOKEN_URL = "https://eu.registry.example/api/v1/auth/agent/token"
OAUTH = {"agent_jwt": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": TOKEN_URL, "scopes": {}}}}}


def _card(security_schemes, security, *, endpoint="interfaces"):
    d = {"protocolVersion": "1.0", "humanReadableId": "translator", "agentVersion": "1.0.0", "name": "Translator",
         "description": "Translates text.", "provider": {"name": "Example"}, "capabilities": {"streaming": False},
         "securitySchemes": security_schemes, "security": security}
    if endpoint == "interfaces":
        d["supportedInterfaces"] = [{"url": AGENT_URL, "protocolBinding": "JSONRPC", "protocolVersion": "1.0"}]
    else:
        d["url"] = AGENT_URL
    return AgentCard.model_validate(d)


def _network():
    seen = {"token_forms": [], "agent_headers": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/auth/agent/token":
            seen["token_forms"].append(dict(parse_qsl(request.content.decode())))
            return httpx.Response(200, json={"access_token": "agent-jwt", "token_type": "bearer", "expires_in": 5400})
        if request.url.path == "/a2a/":
            seen["agent_headers"].append(dict(request.headers))
            rpc_id = json.loads(request.content)["id"]
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"id": "task-1"}, "id": rpc_id})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def _message() -> Message:
    return Message(role="user", parts=[TextPart(content="Hello")])


async def test_an_oauth2_card_named_by_its_interfaces_is_called_with_its_token(monkeypatch):
    monkeypatch.setenv("THEPROTOCOL_OAUTH_TRANSLATOR_CLIENT_ID", "cid-1")
    monkeypatch.setenv("THEPROTOCOL_OAUTH_TRANSLATOR_CLIENT_SECRET", "csec-1")
    transport, seen = _network()
    async with A2AClient(http_client=httpx.AsyncClient(transport=transport)) as client:
        task_id = await client.initiate_task(_card(OAUTH, [{"agent_jwt": []}]), _message(), KeyManager(use_keyring=False))
    assert task_id == "task-1"
    assert seen["token_forms"] == [{"grant_type": "password", "username": "cid-1", "password": "csec-1"}]
    assert seen["agent_headers"][0]["authorization"] == "Bearer agent-jwt"


async def test_an_api_key_goes_in_the_header_the_card_names(monkeypatch):
    monkeypatch.setenv("THEPROTOCOL_KEY_TRANSLATOR", "k-1")
    transport, seen = _network()
    card = _card({"key": {"type": "apiKey", "in": "header", "name": "X-Agent-Key"}}, [{"key": []}], endpoint="url")
    async with A2AClient(http_client=httpx.AsyncClient(transport=transport)) as client:
        assert await client.initiate_task(card, _message(), KeyManager(use_keyring=False)) == "task-1"
    assert seen["agent_headers"][0]["x-agent-key"] == "k-1"


async def test_a_card_that_requires_nothing_is_called_without_a_credential():
    transport, seen = _network()
    async with A2AClient(http_client=httpx.AsyncClient(transport=transport)) as client:
        assert await client.initiate_task(_card(OAUTH, []), _message(), KeyManager(use_keyring=False)) == "task-1"
    assert "authorization" not in seen["agent_headers"][0] and seen["token_forms"] == []


async def test_a_card_whose_scheme_the_client_cannot_use_is_refused_by_name():
    transport, _ = _network()
    card = _card({"basic": {"type": "http", "scheme": "basic"}}, [{"basic": []}])
    async with A2AClient(http_client=httpx.AsyncClient(transport=transport)) as client:
        with pytest.raises(A2AAuthenticationError):
            await client.initiate_task(card, _message(), KeyManager(use_keyring=False))
