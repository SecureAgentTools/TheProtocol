"""V0651 (p) (2026-10-31, agentvault2-14): the token bridge is retired on every registry.

Order gwo_b109ec1d4454d0db66ef6d32, on the maintainer's decision of 2026-10-31 ("retire."). SF-3's wrapped-unit bridge
was D8's first entry: off on the public network since 2026-09-05 (its router unmounted, every route a nameless 404), on
only on the sandbox. Now every /api/v1/bridge/* route answers 410 Gone with one sentence, mounted on every registry
whatever TOKEN_BRIDGE_ENABLED says, and the retired switch changes nothing: the MCP catalogs lose the five bridge tools
(getBridgeAggregate, an admin read of the history, stays), registry-config says token_bridge_enabled false, the card
offers no bridge (tests/test_registry_card_bridge_capability.py), the env catalog names the switch as retired and the
cloud provisioner no longer writes it into an operator's env. Every case fails on 48d07ecf2 (V0650).
"""
from __future__ import annotations

import ast
import pathlib

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentvault_registry.routers import token_bridge

SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry"
MAIN = SRC / "main.py"

ROUTES = (
    ("post", "/api/v1/bridge/transfer"),
    ("post", "/api/v1/bridge/mint-wrapped"),
    ("post", "/api/v1/bridge/redeem"),
    ("post", "/api/v1/bridge/unlock"),
    ("post", "/api/v1/bridge/confirm-lock"),
    ("get", "/api/v1/bridge/status/7c1f2a90-0000-4000-8000-000000000000"),
)
RETIRED_TOOLS = ("theprotocol_bridgeTransfer", "theprotocol_bridgeIssueWrapped", "theprotocol_bridgeRedeem",
                 "theprotocol_bridgeUnlock", "theprotocol_getBridgeStatus")


def _sentence():
    return getattr(token_bridge, "RETIRED_SENTENCE", None)


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(token_bridge.router)
    # a route that still reached its dependencies (V0650: a database, an agent token) answers 401/422/500 here
    return TestClient(app, raise_server_exceptions=False)


def test_the_retirement_sentence_names_the_way_on():
    s = _sentence()
    assert s and "retired" in s and "V0651" in s
    assert "POST /api/v1/teg/cross-registry-transfer" in s and "FX route" in s
    assert "bridge_transactions" in s   # the history is kept


@pytest.mark.parametrize("method,path", ROUTES)
@pytest.mark.parametrize("body", [None, {"amount": 5, "target_registry": "frame-b"}, "not json at all"])
def test_every_bridge_route_answers_410_with_the_sentence(client, method, path, body):
    kw = {}
    if method == "post" and isinstance(body, dict):
        kw["json"] = body
    elif method == "post" and body is not None:
        kw["content"] = body
        kw["headers"] = {"content-type": "application/json"}
    r = getattr(client, method)(path, **kw)
    assert r.status_code == 410, (path, r.status_code, r.text[:200])
    assert r.json()["detail"] == _sentence()


def test_no_bridge_route_reads_a_body_or_runs_a_dependency():
    # the 410 is what every caller reads: never a 401, 403 or 422 first
    paths = {getattr(r, "path", None): r for r in token_bridge.router.routes}
    assert {p for _m, p in ROUTES if "/status/" not in p} | {"/api/v1/bridge/status/{bridge_tx_id}"} == set(paths)
    for route in token_bridge.router.routes:
        assert route.dependant.body_params == [], route.path
        assert route.dependant.dependencies == [], route.path


def _tree():
    return ast.parse(MAIN.read_text(encoding="utf-8"))


def test_main_mounts_the_retired_router_whatever_the_switch_says():
    tree = _tree()
    mounts = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
              and ast.unparse(n).endswith("include_router(token_bridge.router)")]
    assert len(mounts) == 1
    gated = [n for n in ast.walk(tree) if isinstance(n, ast.If) and "include_router(token_bridge.router)" in ast.unparse(n)
             and n.body and any("include_router(token_bridge.router)" in ast.unparse(b) for b in n.body)]
    assert not gated, "the retired bridge router is mounted behind a condition"
    assert "_surface_enabled('TOKEN_BRIDGE_ENABLED')" not in ast.unparse(tree)


def test_registry_config_says_the_bridge_is_off():
    fn = next(n for n in ast.walk(_tree()) if isinstance(n, ast.AsyncFunctionDef) and n.name == "public_registry_config")
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    keys = {k.value: v for k, v in zip(ret.value.keys, ret.value.values) if isinstance(k, ast.Constant)}
    v = keys["token_bridge_enabled"]
    assert isinstance(v, ast.Constant) and v.value is False, ast.unparse(v)


def test_the_bridge_tools_are_gone_from_both_catalogs():
    from agentvault_registry.mcp import audit, server, server_admin, tool_aliases, tool_categories, tool_metadata
    listed_public = {t["name"] for t in server.ALL_TOOL_SCHEMAS if isinstance(t, dict)}
    listed_admin = {t["name"] for t in server_admin.ADMIN_TOOL_SCHEMAS if isinstance(t, dict)}
    for name in RETIRED_TOOLS:
        short = name[len("theprotocol_"):]
        assert name not in server.TOOL_DISPATCH and name not in server_admin.ADMIN_TOOL_DISPATCH, name
        assert name not in listed_public and name not in listed_admin, name
        assert name not in server.TIER2_TOOLS and name not in server.TIER3_TOOLS, name
        for tier in ("_TIER_0_TOOLS", "_TIER_1_TOOLS", "_TIER_2_TOOLS", "_TIER_3_TOOLS"):
            assert name not in getattr(audit, tier), (name, tier)
        assert short not in tool_categories.PUBLIC_TOOL_CATEGORIES and short not in tool_categories.ADMIN_TOOL_CATEGORIES
        assert name not in tool_aliases.TOOL_ALIASES and name not in tool_aliases.TOOL_ALIASES.values(), name
        assert name not in tool_metadata.TASK_TOOLS_PUBLIC, name
    # the admin read of the bridge's history stays
    assert "theprotocol_getBridgeAggregate" in server_admin.ADMIN_TOOL_DISPATCH
    assert "theprotocol_getBridgeAggregate" in listed_admin


def test_the_env_catalog_names_the_retired_switch():
    from agentvault_registry.services import env_catalog as ec
    retired = {r["env"]: r for r in getattr(ec, "RETIRED", ())}
    assert retired["TOKEN_BRIDGE_ENABLED"]["since"] == "V0651"
    assert "410 Gone" in retired["TOKEN_BRIDGE_ENABLED"]["sentence"]
    assert "TOKEN_BRIDGE_ENABLED" not in {e.primary for e in ec.CATALOG}   # never offered as a choice
    here = {r["env"]: r for r in ec.public_view({"TOKEN_BRIDGE_ENABLED": "false"}, "frame")["retired"]}
    assert here["TOKEN_BRIDGE_ENABLED"]["set_here"] is True
    not_here = {r["env"]: r for r in ec.public_view({}, "operator")["retired"]}
    assert not_here["TOKEN_BRIDGE_ENABLED"]["set_here"] is False


def test_the_provisioner_no_longer_writes_the_switch():
    from agentvault_registry.services import cloud_provisioner as cp
    assert "TOKEN_BRIDGE_ENABLED" not in cp.PARENT_POSTURE_KEYS
