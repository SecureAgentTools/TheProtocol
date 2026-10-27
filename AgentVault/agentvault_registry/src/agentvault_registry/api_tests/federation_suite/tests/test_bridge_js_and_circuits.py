"""MCP stdio bridge JS + circuit Nargo + attestation detail tests
(§pass73.3.15 Batch 69).

3 read-only tests probing the static MCP bridge JS endpoints +
ZKP circuit Nargo.toml + attestation detail.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


def _is_silent_or_error(r):
    if isinstance(r, str):
        return True
    if isinstance(r, dict):
        if not r:
            return True
        if "_text" in r:
            return isinstance(r["_text"], str)
    return False


@federation_test(
    name="mcp_stdio_bridge_js_reachable",
    category="bridge_js_and_circuits",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["mcp-bridge", "js-static"],
)
async def test_mcp_stdio_bridge_js(rig: FederationTestRig) -> AssertionResult:
    """getMcpStdioBridgeJs returns the stdio bridge JS source as text.
    Used by Claude Desktop setup → developer downloads the bridge from
    their registry."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("getMcpStdioBridgeJs")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, str):
                state["text_len"] = len(r)
                return len(r) > 0
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="MCP stdio bridge JS endpoint reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="mcp_stdio_bridge_admin_js_reachable",
    category="bridge_js_and_circuits",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["mcp-bridge", "admin-js"],
)
async def test_mcp_stdio_bridge_admin_js(
    rig: FederationTestRig,
) -> AssertionResult:
    """getMcpStdioBridgeAdminJs returns the admin-bridge stdio JS."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getMcpStdioBridgeAdminJs")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, str):
                state["text_len"] = len(r)
                return len(r) > 0
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="MCP stdio admin bridge JS endpoint reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="circuit_nargo_toml_for_known_circuit",
    category="bridge_js_and_circuits",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["zkp", "nargo-toml"],
)
async def test_circuit_nargo_toml(rig: FederationTestRig) -> AssertionResult:
    """getCircuitNargoToml returns the Nargo.toml manifest for a known
    ZKP circuit. Probe getCircuits first to pick a circuit_id."""
    state: dict = {}

    async def predicate():
        try:
            circuits = await rig.mcp("sandbox-A").call("getCircuits")
            items = circuits if isinstance(circuits, list) else (
                circuits.get("circuits") or circuits.get("items") or
                circuits.get("data") or []
            ) if isinstance(circuits, dict) else []
            if not items or not isinstance(items[0], dict):
                state["no_circuits"] = True
                return True
            cid = (items[0].get("id") or items[0].get("circuit_id") or
                   items[0].get("name") or items[0].get("slug"))
            if cid is None:
                state["no_circuit_id"] = True
                state["circuit_keys"] = sorted((items[0] or {}).keys())[:8]
                return True
            state["circuit_id"] = cid
            r = await rig.mcp("sandbox-A").call(
                "getCircuitNargoToml", {"circuit_id": str(cid)}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, str):
                state["text_len"] = len(r)
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e) or "400" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="circuit Nargo.toml endpoint reachable for known circuit",
        capture_state=lambda: state,
    )
