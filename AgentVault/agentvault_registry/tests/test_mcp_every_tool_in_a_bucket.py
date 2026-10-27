"""D6-726 (2026-10-16): every tool either MCP server lists belongs to a toolset bucket.

A tool missing from the category map falls back to "misc" with a boot warning and still works, but no bucket-filtered
listing (?toolsets= / X-MCP-Toolsets, a stored enableToolset selection) ever shows it: on V0618 eighteen public tools
(the contracts-v2 milestone tools, the Forge, the notification matrix, the support review grants, the transparent
organizations and two invitation tools) and two admin tools were reachable only through the full catalog and
searchTools. The module docstring promised a gate for this; none existed.
"""
from __future__ import annotations

from agentvault_registry.mcp import server, server_admin
from agentvault_registry.mcp import tool_categories as tc


def _unbucketed(schemas, table):
    return sorted(s["name"] for s in schemas if tc.bare_name(s["name"]) not in table)


def test_every_public_tool_is_in_a_bucket():
    assert len(server.ALL_TOOL_SCHEMAS) > 400, "a scan over nothing passes loudest"
    assert _unbucketed(server.ALL_TOOL_SCHEMAS, tc.PUBLIC_TOOL_CATEGORIES) == []
    assert {tc.get_category(s["name"]) for s in server.ALL_TOOL_SCHEMAS} <= set(tc.PUBLIC_BUCKETS)


def test_every_admin_tool_is_in_a_bucket():
    assert len(server_admin.ADMIN_TOOL_SCHEMAS) > 300
    assert _unbucketed(server_admin.ADMIN_TOOL_SCHEMAS, tc.ADMIN_TOOL_CATEGORIES) == []
    assert {tc.get_category(s["name"], is_admin=True) for s in server_admin.ADMIN_TOOL_SCHEMAS} <= set(tc.ADMIN_BUCKETS)


def test_selecting_every_bucket_lists_the_whole_catalog():
    """What a client sees when it asks for all buckets is everything the full listing holds, on both servers."""
    everything = tc.filter_schemas(server.ALL_TOOL_SCHEMAS, set(tc.PUBLIC_BUCKETS))
    assert [s["name"] for s in everything] == [s["name"] for s in server.ALL_TOOL_SCHEMAS]
    admin_all = tc.filter_schemas(server_admin.ADMIN_TOOL_SCHEMAS, set(tc.ADMIN_BUCKETS), is_admin=True)
    assert [s["name"] for s in admin_all] == [s["name"] for s in server_admin.ADMIN_TOOL_SCHEMAS]


def test_the_contract_tools_list_with_their_family():
    """The bucket a caller would look in: the milestone tools beside acceptContract, the Forge beside the CI/CD tools."""
    payments = {s["name"] for s in tc.filter_schemas(server.ALL_TOOL_SCHEMAS, {"payments-a2a", "core"})}
    assert {"theprotocol_acceptContract", "theprotocol_submitContractMilestone",
            "theprotocol_releaseContractMilestone", "theprotocol_getContractV2"} <= payments
    lifecycle = {s["name"] for s in tc.filter_schemas(server.ALL_TOOL_SCHEMAS, {"dev-lifecycle", "core"})}
    assert {"theprotocol_createVersion", "theprotocol_runForgeEval", "theprotocol_getForgeStatus"} <= lifecycle
