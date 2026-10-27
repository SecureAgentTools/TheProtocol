"""D6-727 (2026-10-16): GET /mcp/tools groups the tools by tier, and initialize names the count tools/list gives.

/mcp/tools labelled its three lists tier1_public, tier2_agent and tier3_developer while it filled them from the three
modules that define the schemas: submitDispute and createProposal (agent tools) sat under tier3_developer,
getAgentToken (no credential) and the public Guild reads under tier2_agent. And initialize's instructions counted the
dispatch table (444 on V0618) while tools/list listed 446 (enableToolset and disableToolset are answered before
dispatch). The tiers now come from the sets tools/call enforces, and the count from the listing itself.
"""
from __future__ import annotations

import asyncio
import re

from starlette.requests import Request

from agentvault_registry.mcp import server as S


def _get(path="/mcp/tools"):
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    scope = {"type": "http", "method": "GET", "path": path, "raw_path": path.encode(), "headers": [],
             "query_string": b"", "client": ("127.0.0.1", 40000), "server": ("testserver", 80), "scheme": "http",
             "root_path": "", "http_version": "1.1"}
    return Request(scope, receive)


def test_initialize_names_the_number_of_tools_the_full_listing_holds():
    listed = asyncio.run(S._handle_tools_list())["tools"]
    said = asyncio.run(S._handle_initialize({}))["instructions"]
    n = int(re.search(r"provides (\d+) tools", said).group(1))
    assert n == len(listed) == asyncio.run(S.mcp_health())["tools_available"]
    # why the dispatch table is the wrong count: the two selection tools are answered before dispatch
    assert {t["name"] for t in listed} - set(S.TOOL_DISPATCH) == {"theprotocol_enableToolset",
                                                                  "theprotocol_disableToolset"}


def test_the_tiers_are_the_ones_tools_call_enforces():
    tiers = asyncio.run(S.list_tools_http(_get()))["tiers"]
    names = [t["name"] for t in S.ALL_TOOL_SCHEMAS]
    flat = [n for group in tiers.values() for n in group]
    assert sorted(flat) == sorted(names), "every listed tool in exactly one tier"
    assert tiers["tier0_utility"] == ["theprotocol_getAgentToken"]
    assert set(tiers["tier2_agent"]) == {n for n in names if n in S.TIER2_TOOLS}
    assert set(tiers["tier3_developer"]) == {n for n in names if n in S.TIER3_TOOLS}
    assert set(tiers["listing_preferences"]) == {"theprotocol_enableToolset", "theprotocol_disableToolset"}
    # the tools the module grouping misfiled
    assert {"theprotocol_submitDispute", "theprotocol_createProposal"} <= set(tiers["tier2_agent"])
    assert "theprotocol_getCommunityAnnouncements" in tiers["tier3_developer"]
    assert "theprotocol_guildListOrders" in tiers["tier1_public"]
    assert not set(tiers["tier1_public"]) & (S.TIER2_TOOLS | S.TIER3_TOOLS)
