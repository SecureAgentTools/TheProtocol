"""§MCPTEST30 (V0541): a relay route reports a relay only when the address answers as one, and the tester's
getRelayStatus contract takes the refusal the sentinel's card earns on each target.

Round 11 was the first run whose getRelayStatus reached the route (V0538 gave the tool its developer credential). A
frame's sentinel declares http://localhost:8100/agents/<name> on its card: the SSRF guard's 422, correct. An operator's
declares its own public page, https://<operator>/agents/<name>; the route POSTed the relay call there, the host answered
with its 404 body, and `data.get("result", {})` read the missing result as an empty one: 200 `{}`, a relay with nothing
to say (cloud-op alpha run 5d85e2dfd5404824). The route now answers 502 and names the status that came back.
"""
from __future__ import annotations

import json
import socket
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from agentvault_registry.api_tests.categories.flow_mcp_lifecycle.test_flow_mcp_lifecycle import _evaluate_contract
from agentvault_registry.api_tests.contracts.mcp_contracts import McpContract, McpFixtureBag, get_contract
from agentvault_registry.routers import agent_cicd
from agentvault_registry.services import service_purchase

OWNER = SimpleNamespace(id=7)
DID = "did:theprotocol:sandbox-a.theprotocol.cloud:00000000-0000-4000-8000-000000000002"


@pytest.fixture
def answer(monkeypatch):
    """The address's answer to the relay call: (HTTP status, JSON body); `None` for an address that does not answer."""
    import httpx

    state = {"answer": (200, {"result": {"content": [{"text": '{"running": true}'}]}}), "posted": []}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, json=None):
            state["posted"].append(url)
            if state["answer"] is None:
                raise ConnectionError("connect to 10.1.2.3:8000 refused")
            code, body = state["answer"]
            return SimpleNamespace(status_code=code, json=lambda: body)

    async def permission(db, agent_did, developer_id):
        return None

    async def relay_url(agent_did, db):
        return "https://sbxalphaop.op.example.test/agents/cloudop-sentinel-1790903738-bc1dfc"

    monkeypatch.setattr(agent_cicd.agent_cicd_service, "_get_agent_with_permission", permission)
    monkeypatch.setattr(agent_cicd, "_get_relay_url", relay_url)
    monkeypatch.setattr(service_purchase.socket, "getaddrinfo",
                        lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: _Client())
    return state


async def test_a_relay_result_is_returned(answer):
    assert await agent_cicd.relay_status(agent_did=DID, developer=OWNER, db=None) == {"running": True}
    assert await agent_cicd.relay_action(agent_did=DID, body={"tool": "relay_stop"}, developer=OWNER, db=None) == {"running": True}


@pytest.mark.parametrize("code, body", [
    (404, {"detail": "Not Found"}),             # round 11: an operator's own page answering the relay path
    (200, {"detail": "Not Found"}),             # a 200 that is no JSON-RPC result
    (200, {"result": {"content": []}}),         # a result with nothing in it
])
async def test_an_address_that_does_not_answer_as_a_relay_is_a_502(answer, code, body):
    answer["answer"] = (code, body)
    for call in (agent_cicd.relay_status(agent_did=DID, developer=OWNER, db=None),
                 agent_cicd.relay_action(agent_did=DID, body={"tool": "relay_restart"}, developer=OWNER, db=None)):
        with pytest.raises(HTTPException) as ei:
            await call
        assert ei.value.status_code == 502
        assert ei.value.detail == f"The agent's address answered, but not as a relay (HTTP {code})"


async def test_a_silent_address_is_still_the_502_without_its_exception_text(answer):
    answer["answer"] = None
    with pytest.raises(HTTPException) as ei:
        await agent_cicd.relay_status(agent_did=DID, developer=OWNER, db=None)
    assert ei.value.status_code == 502 and "10.1.2.3" not in str(ei.value.detail)


_TOOL = {"name": "theprotocol_getRelayStatus", "inputSchema": {"type": "object", "properties": {}}}
_BAG = McpFixtureBag(sentinel_did="did:theprotocol:test", sentinel_jwt="x")


def _rpc(text):
    return {"jsonrpc": "2.0", "id": 1, "result": {"isError": True, "content": [{"type": "text", "text": text}]}}


def _judge(code, text, contract=None):
    return _evaluate_contract(_TOOL, contract or get_contract("theprotocol_getRelayStatus"), False, code, _rpc(text), _BAG,
                              has_explicit_contract=True)


def test_the_contract_takes_each_refusal_the_sentinel_earns():
    assert _judge("422", "Error: HTTP 422: Agent endpoint must be https (card declares http)")[0] is True   # a frame
    assert _judge("502", "Error: HTTP 502: The agent's address answered, but not as a relay (HTTP 404)")[0] is True
    assert _judge("404", "Error: HTTP 404: No relay configured for this agent")[0] is True


def test_the_error_class_still_requires_a_named_refusal():
    """The controls: another refusal, a success, and a bare "error" contract are each refused."""
    ok, why = _judge("500", "Error: HTTP 500: Internal server error")
    assert ok is False and "expected error message contains one of" in why
    ok, why = _evaluate_contract(_TOOL, get_contract("theprotocol_getRelayStatus"), True, "200",
                                 {"jsonrpc": "2.0", "id": 1, "result": {"content": [{"type": "text", "text": json.dumps({})}]}},
                                 _BAG, has_explicit_contract=True)
    assert ok is False and "expected error but got 200" in why
    ok, why = _judge("422", "Error: HTTP 422: anything", McpContract(tier="3", arguments={}, expect_status="error"))
    assert ok is False and "banned pattern" in why
