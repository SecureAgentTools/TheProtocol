"""§AGORAWORDS (V0419): the AGORA renames keep every old name working, and only the new names are advertised.

MCP: a renamed tool must resolve at every door a wire name enters (public tools/call, the internal
`_handle_tools_call`, admin tools/call, the gateway's invokeTool / describeTools), or that door refuses it.
HTTP: the AGORA router is mounted twice, `/api/v1/agora` (in the schema) and `/api/v1/exchange` (hidden),
and every word-bearing path has its new name documented beside a hidden old one.
"""
from __future__ import annotations

import pytest

from agentvault_registry.mcp import server, server_admin, tools_discovery, tools_gateway
from agentvault_registry.mcp.tool_aliases import TOOL_ALIASES, resolve_alias

PUBLIC = set(server.TOOL_DISPATCH)
ADMIN = set(server_admin.ADMIN_TOOL_DISPATCH)


def _schema_names(schemas):
    return {s.get("name") for s in schemas}


def test_there_are_nineteen_agora_renames_and_thirty_eight_w3_ones_and_oauth_token_exchange_is_not_one():
    from agentvault_registry.mcp.tool_aliases import _AGORA_RENAMED, _W3_RENAMED
    assert len(_AGORA_RENAMED) == 19 and len(_W3_RENAMED) == 41 and len(TOOL_ALIASES) == 60
    assert not any("oauthTokenExchange" in k for k in TOOL_ALIASES)
    assert not set(_AGORA_RENAMED) & set(_W3_RENAMED), "an old name in two families"


def test_every_alias_target_is_a_dispatch_key_and_no_old_name_is_one():
    for old, new in TOOL_ALIASES.items():
        assert new in PUBLIC or new in ADMIN, f"{old} -> {new}: the target is in no dispatch table"
        assert old not in PUBLIC and old not in ADMIN, f"{old} is still a dispatch key (it would be advertised)"


def test_only_the_new_names_are_advertised():
    public_names = _schema_names(server.ALL_TOOL_SCHEMAS)
    admin_names = _schema_names(server_admin.ADMIN_TOOL_SCHEMAS)
    for old, new in TOOL_ALIASES.items():
        assert old not in public_names and old not in admin_names, f"{old} is advertised in tools/list"
        assert new in public_names or new in admin_names, f"{new} has no schema"


def test_resolve_alias_takes_both_wire_forms_and_passes_unknown_names_through():
    assert resolve_alias("theprotocol_buyExchangeIpo") == "theprotocol_buyAgoraLaunch"
    assert resolve_alias("buyExchangeIpo") == "buyAgoraLaunch"
    assert resolve_alias("theprotocol_getMyExchangePortfolio") == "theprotocol_getMyAgoraHoldings"
    assert resolve_alias("theprotocol_getMyBalance") == "theprotocol_getMyBalance"   # control: untouched
    assert resolve_alias("theprotocol_oauthTokenExchange") == "theprotocol_oauthTokenExchange"
    assert resolve_alias("") == ""


def test_the_renamed_tools_keep_their_tiers():
    from agentvault_registry.mcp import audit
    for new in ("theprotocol_placeAgoraOrder", "theprotocol_cancelAgoraOrder", "theprotocol_getMyAgoraOrders",
                "theprotocol_getMyAgoraHoldings", "theprotocol_buyAgoraLaunch"):
        assert new in server.TIER2_TOOLS and new in audit._TIER_2_TOOLS, new
    for new in ("theprotocol_createAgoraListing", "theprotocol_declareAgoraDistribution"):
        assert new in server.TIER3_TOOLS and new in audit._TIER_3_TOOLS, new


@pytest.mark.asyncio
async def test_an_old_public_name_executes_through_the_dispatcher(monkeypatch):
    seen = {}

    async def _fake_public_get(path, params=None, op_name=""):
        seen["path"], seen["op"] = path, op_name
        return {"listings": [{"symbol": "ALFW"}]}

    monkeypatch.setattr(tools_discovery, "_public_get", _fake_public_get)
    payload, _ = await server._handle_tools_call("theprotocol_getExchangeListings", {}, token=None)
    assert payload["isError"] is False, payload
    assert seen["path"].endswith("/listings") and seen["op"] == "getAgoraListings"


def test_invoke_tool_unwraps_an_old_name_on_both_surfaces():
    name, args = tools_gateway.unwrap_invoke({"name": "getExchangeListings", "arguments": {}}, server.TOOL_DISPATCH)
    assert name == "theprotocol_getAgoraListings" and args == {}
    name, _ = tools_gateway.unwrap_invoke({"name": "theprotocol_adminExchangeOverview"}, server_admin.ADMIN_TOOL_DISPATCH)
    assert name == "theprotocol_adminAgoraOverview"
    with pytest.raises(ValueError):   # control: an unknown name is still refused
        tools_gateway.unwrap_invoke({"name": "getNoSuchThing"}, server.TOOL_DISPATCH)


@pytest.mark.asyncio
async def test_describe_tools_finds_the_new_schema_under_an_old_name():
    out = await tools_gateway.describe_tools(server.ALL_TOOL_SCHEMAS, is_admin=False, names=["buyExchangeIpo"])
    assert [t["name"] for t in out["tools"]] == ["theprotocol_buyAgoraLaunch"]
    assert "not_found" not in out


def test_both_tools_call_doors_resolve_the_alias():
    """The public and admin JSON-RPC `tools/call` branches read the name through resolve_alias (a door that
    reads params['name'] raw would refuse every old name with -32601)."""
    import inspect
    for mod in (server, server_admin):
        src = inspect.getsource(mod)
        assert 'tool_name = resolve_alias(params.get("name", ""))' in src, mod.__name__


def test_the_agora_router_is_mounted_twice_and_only_the_new_prefix_is_documented():
    from agentvault_registry import main as m
    paths = {}
    try:  # §DEPS: FastAPI 0.14x keeps an included router as one lazily resolved app.routes entry
        from fastapi.routing import iter_route_contexts
        served = list(iter_route_contexts(m.app.routes))
    except ImportError:
        served = list(m.app.routes)
    for r in served:
        p = getattr(r, "path", None)
        if p:
            paths.setdefault(p, []).append(getattr(r, "include_in_schema", True))
    for p in ("/api/v1/agora/listings", "/api/v1/agora/listings/{listing_ref}/launch/buy",
              "/api/v1/agora/listings/{listing_ref}/distributions",
              "/api/v1/agora/organizations/{org_id}/treasury/{symbol}/distribution",
              "/api/v1/agora/organizations/{org_id}/treasury/{symbol}/buy",
              "/.well-known/agora-card.json", "/api/v1/agora/card", "/api/v1/developers/me/holdings-book"):
        assert p in paths and any(paths[p]), f"{p}: missing or not in the schema"
    for p in ("/api/v1/exchange/listings", "/api/v1/exchange/listings/{listing_ref}/ipo/buy",
              "/api/v1/exchange/listings/{listing_ref}/dividends",
              "/api/v1/exchange/organizations/{org_id}/treasury/{symbol}/dividend",
              "/api/v1/exchange/organizations/{org_id}/treasury/{symbol}/buyback",
              "/.well-known/stock-card.json", "/api/v1/exchange/stock-card", "/api/v1/developers/me/share-book"):
        assert p in paths, f"{p}: the old name must stay live"
        assert not any(paths[p]), f"{p}: the old name must be hidden from the schema"
    # the old word paths under the NEW prefix exist (same stacked function) but stay hidden
    assert not any(paths["/api/v1/agora/listings/{listing_ref}/ipo/buy"])
