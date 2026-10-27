"""D8: a retired bridge reads as switched off, not as five broken contracts (the nightly pair nt261008, 2026-10-08).

The fresh frame's template sets TOKEN_BRIDGE_ENABLED=false (his decision D8: the legacy money surfaces retire behind
flags), so the bridge router is not mounted and every bridge route answers FastAPI's plain 404 "Not Found". The first
nightly pair on the current image read that as three failed bridge contracts (they wait for the router's own refusal
sentences). registry-config now reports token_bridge_enabled, and the tester holds the bridge tools to the 404 where the
target says the bridge is off, exactly as it holds the staking tools to their refusal (test_mcp_switches.py).
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import pathlib

from agentvault_registry.api_tests.contracts import mcp_switches as M
from agentvault_registry.mcp import tools_admin, tools_agent

BRIDGE_TOOLS = ("bridgeTransfer", "bridgeIssueWrapped", "bridgeRedeem", "bridgeUnlock", "getBridgeStatus")
NOT_MOUNTED = "Error: HTTP 404: Not Found"


def _switched(tool, config):
    async def go():
        M.use_target(config)
        return M.switched_off(tool)
    return asyncio.run(go())


def test_the_bridge_tools_follow_the_reported_switch():
    for n in BRIDGE_TOOLS:
        tool = f"theprotocol_{n}"
        assert _switched(tool, {"token_bridge_enabled": False}) is M.BRIDGE_OFF, n
        assert _switched(tool, {"token_bridge_enabled": True}) is None, n
        # a target older than this key reports nothing: nothing is switched, never guessed
        assert _switched(tool, {"staking_enabled": True}) is None, n
    assert "token_bridge_enabled" in M.KEYS


def test_a_retired_bridge_is_judged_by_its_404():
    assert M.judge("theprotocol_bridgeUnlock", M.BRIDGE_OFF, 404, NOT_MOUNTED) == (True, None)
    healthy, why = M.judge("theprotocol_bridgeUnlock", M.BRIDGE_OFF, 200, '{"ok": true}')
    assert not healthy and why.startswith("BUG-FIND")
    # controls: a mounted router's own 404 is not the switch, and neither is another refusal
    healthy, _why = M.judge("theprotocol_getBridgeStatus", M.BRIDGE_OFF, 404, "Error: HTTP 404: Bridge transaction not found")
    assert not healthy
    healthy, _why = M.judge("theprotocol_getBridgeStatus", M.BRIDGE_OFF, 403, "Error: HTTP 403: forbidden")
    assert not healthy


def test_every_switched_tool_is_a_bridge_route():
    src = inspect.getsource(tools_admin) + inspect.getsource(tools_agent)
    for path in ("/api/v1/bridge/mint-wrapped", "/api/v1/bridge/redeem", "/api/v1/bridge/unlock",
                 "/api/v1/bridge/status/", "/api/v1/bridge/transfer"):
        assert path in src, path


MAIN = pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "main.py"


def _route_fn(name):
    # the route is a closure inside create_app(): the AST is the honest reader (test_freshframe_registry_config.py)
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    return next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == name)


def test_the_bridge_router_is_mounted_only_behind_its_switch():
    assert M.BRIDGE_OFF.where == (
        "unmounted: main.create_app mounts routers/token_bridge.py only where TOKEN_BRIDGE_ENABLED is on")
    tree = ast.parse(MAIN.read_text(encoding="utf-8"))
    gates = [n for n in ast.walk(tree) if isinstance(n, ast.If)
             and "include_router(token_bridge.router)" in ast.unparse(n)
             and ast.unparse(n.test) == "_surface_enabled('TOKEN_BRIDGE_ENABLED')"]
    assert len(gates) == 1
    mounts = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and ast.unparse(n).endswith("include_router(token_bridge.router)")]
    assert len(mounts) == 1, "the bridge router is mounted somewhere its switch does not reach"


def test_registry_config_reports_the_d8_switches():
    fn = _route_fn("public_registry_config")
    ret = next(n for n in ast.walk(fn) if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict))
    keys = {k.value: ast.unparse(v) for k, v in zip(ret.value.keys, ret.value.values) if isinstance(k, ast.Constant)}
    assert keys.get("token_bridge_enabled") == "_legacy_surface_on('TOKEN_BRIDGE_ENABLED')"
    assert keys.get("legacy_contracts_enabled") == "_legacy_surface_on('LEGACY_CONTRACTS_ENABLED')"
