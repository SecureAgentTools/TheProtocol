"""§MCPTEST30 (V0547) — three MCP wrappers turned a peer-only route's 401 into an empty list.

listFederationAgentCards, listFederationRegistryCards and getFederationPolicyCompliance call routes that authenticate
only a federation PEER (core/federation_auth.get_federation_identity: mTLS, the internal secret or a federation
licence), which no MCP caller holds. Each wrapper answered the refusal with {"agent_cards": [], "total": 0} (and the
like) for every caller, and its contract read that as a pass on every run (round 14: 200, healthy). They now answer
the refusal as it came; their contracts pin it as documented 4xx, and the survey's PEER_ROUTE class names them.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS
from agentvault_registry.mcp import tools_discovery as TD

REFUSAL = {"status_code": 401,
           "upstream_error": "listFederationAgentCards returned HTTP 401: Federation authentication required",
           "body": '{"detail":"Federation authentication required (mTLS certificate, internal secret, or federation license)"}',
           "path": "/api/v1/federation/agent-cards"}
CASES = [(TD.list_federation_agent_cards, "agent_cards"), (TD.list_federation_registry_cards, "registry_cards"),
         (TD.get_federation_policy_compliance, "peers")]


@pytest.mark.parametrize("fn,key", CASES)
def test_the_refusal_reaches_the_caller_never_an_empty_list(monkeypatch, fn, key):
    async def refused(path, params=None, op_name=""):
        return dict(REFUSAL)
    monkeypatch.setattr(TD, "_public_get", refused)
    out = asyncio.run(fn())
    assert key not in out, f"{fn.__name__} invented an empty {key} list for a refusal: {out}"
    assert out["status_code"] == 401 and "Federation authentication required" in out["body"]


@pytest.mark.parametrize("fn,key", CASES)
def test_the_control_an_answer_the_peer_feed_gives_is_kept(monkeypatch, fn, key):
    async def served(path, params=None, op_name=""):
        return [{"id": 1}, {"id": 2}]
    monkeypatch.setattr(TD, "_public_get", served)
    out = asyncio.run(fn())
    assert out[key] == [{"id": 1}, {"id": 2}] and out["total"] == 2


@pytest.mark.parametrize("tool", ["theprotocol_listFederationAgentCards", "theprotocol_listFederationRegistryCards",
                                  "theprotocol_getFederationPolicyCompliance"])
def test_their_contracts_pin_the_refusal_not_an_empty_success(tool):
    c = MCP_CONTRACTS[tool]
    assert c.expect_status == "error_4xx" and c.expect_error_message_contains == "Federation authentication required"
    assert not c.expect_keys


def test_no_description_promises_a_public_read():
    from agentvault_registry.mcp.tools_discovery import DISCOVERY_TOOL_SCHEMAS as SCHEMAS
    by = {sc["name"]: sc["description"] for sc in SCHEMAS}
    for tool in ("theprotocol_listFederationAgentCards", "theprotocol_listFederationRegistryCards",
                 "theprotocol_getFederationPolicyCompliance"):
        assert "Public." not in by[tool] and "federation peers only" in by[tool], by[tool]


@pytest.fixture(autouse=True)
def _leave_a_current_event_loop():
    yield
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
