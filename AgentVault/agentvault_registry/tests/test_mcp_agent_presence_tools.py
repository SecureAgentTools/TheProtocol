"""V0650 (a) (2026-10-31, agentvault2-14): the two MCP tools, setMyAgentStatus and getOrganizationPresence.

Wired in every place (dispatch, tier sets in server.py and audit.py, categories), listed once each, and reaching their
routes; an agent context is required to set a line, and an empty argument never reaches the registry. BASE (V0649): the
tools do not exist.
"""
from __future__ import annotations

import asyncio

import pytest

from agentvault_registry.mcp.auth_bridge import MCPAuthContext, MCPAuthError

TOOLS = {"theprotocol_setMyAgentStatus", "theprotocol_getOrganizationPresence"}
AGT = MCPAuthContext(auth_type="agent", agent_did="did:theprotocol:a", agent_id=3, raw_token="agent-jwt")
DEV = MCPAuthContext(auth_type="developer", developer_id=7, raw_token="dev-jwt")


def _module():
    from agentvault_registry.mcp import tools_presence
    return tools_presence


def test_both_tools_are_wired_in_every_place_and_listed_once():
    from agentvault_registry.mcp import audit, server, server_admin, tool_categories as tc
    names = [t["name"] for t in server.ALL_TOOL_SCHEMAS]
    for n in TOOLS:
        assert names.count(n) == 1 and n in server.TOOL_DISPATCH and n in server.TIER2_TOOLS, n
        assert n in audit._TIER_2_TOOLS and n in server.AUTH_REQUIRED_TOOLS, n
        assert n not in server_admin.ADMIN_TOOL_DISPATCH and tc.get_category(n) == "dev-lifecycle", n
    by = {t["name"]: t for t in server.ALL_TOOL_SCHEMAS}
    assert by["theprotocol_getOrganizationPresence"]["annotations"]["readOnlyHint"] is True
    set_ann = by["theprotocol_setMyAgentStatus"]["annotations"]
    assert set_ann["idempotentHint"] is True and set_ann["destructiveHint"] is False


def test_the_tools_reach_their_routes(monkeypatch):
    m = _module()
    calls = []

    async def _req(auth, method, path, json_body=None, params=None, op_name=""):
        calls.append((method, path, json_body, op_name))
        return {"ok": True}
    monkeypatch.setattr(m, "_chat_request", _req)
    asyncio.run(m.set_my_agent_status(AGT, "building", 600))
    asyncio.run(m.get_organization_presence(AGT, "org/with space"))
    assert calls[0] == ("PUT", "/api/v1/agents/me/status", {"text": "building", "ttl_seconds": 600}, "setMyAgentStatus")
    assert calls[1][0] == "GET" and calls[1][1] == "/api/v1/organizations/org%2Fwith%20space/presence"


def test_a_developer_context_cannot_set_an_agents_line_and_blanks_never_leave(monkeypatch):
    m = _module()
    calls = []

    async def _req(*a, **k):
        calls.append(a)
        return {}
    monkeypatch.setattr(m, "_chat_request", _req)
    with pytest.raises(MCPAuthError):
        asyncio.run(m.set_my_agent_status(DEV, "x"))
    assert "error" in asyncio.run(m.set_my_agent_status(AGT, "   "))
    assert "error" in asyncio.run(m.get_organization_presence(DEV, ""))
    assert calls == []
