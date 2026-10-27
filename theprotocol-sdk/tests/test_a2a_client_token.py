"""A2AClient's OAuth2 token request (0.7.6) — hermetic via MockTransport.

A card may name a registry's agent token route as its token URL (the registry's own agent cards do). That route reads
FastAPI's OAuth2 password form: client_id as `username`, client_secret as `password`, `grant_type` absent or
`password`. Measured on the registry's FastAPI (0.141.1): the client-credentials form, and that form with username and
password added, are both answered 422 (`grant_type` must match `^password$`); `username` + `password`, with or without
`grant_type=password`, are answered 200. Up to 0.7.5 the client sent the client-credentials form to every token URL.
"""

import json
from urllib.parse import parse_qsl

import httpx

from theprotocol.client import A2AClient, KeyManager
from theprotocol.models import AgentCard, Message, TextPart

AGENT_URL = "https://agent.example/a2a"


def _card(token_url: str) -> AgentCard:
    return AgentCard.model_validate({
        "protocolVersion": "1.0",
        "humanReadableId": "translator",
        "agentVersion": "1.0.0",
        "name": "Translator",
        "description": "Translates text.",
        "url": AGENT_URL,
        "authSchemes": [{"scheme": "oauth2", "tokenUrl": token_url}],
        "provider": {"name": "Example"},
        "capabilities": {"streaming": False},
    })


def _keys(monkeypatch) -> KeyManager:
    monkeypatch.setenv("THEPROTOCOL_OAUTH_TRANSLATOR_CLIENT_ID", "cid-1")
    monkeypatch.setenv("THEPROTOCOL_OAUTH_TRANSLATOR_CLIENT_SECRET", "csec-1")
    return KeyManager(use_keyring=False)


def _network(token_path: str, token_rule):
    """A token server at `token_path` answering by `token_rule(form)`, and the agent's JSON-RPC endpoint."""
    seen = {"token_forms": [], "agent_auth": []}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == token_path:
            form = dict(parse_qsl(request.content.decode()))
            seen["token_forms"].append(form)
            return token_rule(form)
        if request.url.path == "/a2a/":
            seen["agent_auth"].append(request.headers.get("authorization"))
            rpc_id = json.loads(request.content)["id"]
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": {"id": "task-1"}, "id": rpc_id})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def _registry_rule(form):
    """The registry's /api/v1/auth/agent/token as measured: FastAPI's OAuth2PasswordRequestForm, then the credentials."""
    if form.get("grant_type") not in (None, "password") or "username" not in form or "password" not in form:
        return httpx.Response(422, json={"detail": [{"type": "validation_error"}]})
    if (form["username"], form["password"]) != ("cid-1", "csec-1"):
        return httpx.Response(401, json={"detail": "Invalid client credentials"})
    return httpx.Response(200, json={"access_token": "agent-jwt", "token_type": "bearer", "expires_in": 5400})


def _client_credentials_rule(form):
    """A standard OAuth2 client-credentials token endpoint (RFC 6749 section 4.4)."""
    if form.get("grant_type") != "client_credentials":
        return httpx.Response(400, json={"error": "unsupported_grant_type"})
    if (form.get("client_id"), form.get("client_secret")) != ("cid-1", "csec-1"):
        return httpx.Response(401, json={"error": "invalid_client"})
    return httpx.Response(200, json={"access_token": "cc-token", "token_type": "bearer", "expires_in": 3600})


def _message() -> Message:
    return Message(role="user", parts=[TextPart(content="Hello")])


async def test_a_registry_token_url_gets_the_registry_form(monkeypatch):
    transport, seen = _network("/api/v1/auth/agent/token", _registry_rule)
    async with A2AClient(http_client=httpx.AsyncClient(transport=transport)) as client:
        card = _card("https://eu.registry.example/api/v1/auth/agent/token")
        task_id = await client.initiate_task(card, _message(), _keys(monkeypatch))
    assert task_id == "task-1"
    assert seen["token_forms"] == [{"grant_type": "password", "username": "cid-1", "password": "csec-1"}]
    assert seen["agent_auth"] == ["Bearer agent-jwt"]


async def test_any_other_token_url_still_gets_the_client_credentials_form(monkeypatch):
    transport, seen = _network("/oauth/token", _client_credentials_rule)
    async with A2AClient(http_client=httpx.AsyncClient(transport=transport)) as client:
        task_id = await client.initiate_task(card := _card("https://auth.example/oauth/token"), _message(),
                                             km := _keys(monkeypatch))
        await client.initiate_task(card, _message(), km)   # the cached token is reused
    assert task_id == "task-1"
    assert seen["token_forms"] == [{"grant_type": "client_credentials", "client_id": "cid-1", "client_secret": "csec-1"}]
    assert seen["agent_auth"] == ["Bearer cc-token", "Bearer cc-token"]
