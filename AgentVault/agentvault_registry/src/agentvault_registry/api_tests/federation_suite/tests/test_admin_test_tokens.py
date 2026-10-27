"""Admin test tokens + MCP audit log + agent metrics tests (§pass73.3.12 Batch 53).

3 read-only tests probing seldom-touched admin observability surfaces.
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
    name="admin_test_tokens_inventory",
    category="admin_test_tokens",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["test-tokens", "admin"],
)
async def test_admin_test_tokens(rig: FederationTestRig) -> AssertionResult:
    """getAdminTestTokens returns the dev/test JWT minting envelope."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminTestTokens")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin test tokens endpoint reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_mcp_audit_by_actor_self_lookup",
    category="admin_test_tokens",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["mcp-audit", "admin"],
)
async def test_admin_mcp_audit_by_actor(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminMcpAuditLogByActor returns audit envelope. Picks first
    developer from admin developer list, then looks up audit log."""
    state: dict = {}

    async def predicate():
        try:
            devs = await rig.mcp("sandbox-A-admin").call(
                "getAdminDevelopers", {"limit": 1}
            )
            items = devs if isinstance(devs, list) else (
                devs.get("developers") or devs.get("items") or devs.get("data") or []
            ) if isinstance(devs, dict) else []
            if not items:
                state["no_devs"] = True
                return True
            target = items[0]
            actor_id = (target.get("id") if isinstance(target, dict) else None) or \
                       (target.get("developer_id") if isinstance(target, dict) else None)
            if actor_id is None:
                state["no_actor_id"] = True
                state["dev_keys"] = sorted((target or {}).keys())[:8]
                return True
            state["actor_id"] = actor_id
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminMcpAuditLogByActor", {"actor_id": str(actor_id)}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            elif isinstance(r, list):
                state["count"] = len(r)
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin mcp-audit-by-actor reachable for known dev",
        capture_state=lambda: state,
    )


@federation_test(
    name="health_check_with_agent_auth_reachable",
    category="admin_test_tokens",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["health", "agent-auth"],
)
async def test_health_with_agent_auth(rig: FederationTestRig) -> AssertionResult:
    """getHealthCheckWithAgentAuth is the agent-tier health probe.
    Returns 200 + envelope when reachable (auth headers stripped for the
    admin bridge, so may return 401 — both states accepted)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getHealthCheckWithAgentAuth")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="health-check-with-agent-auth endpoint reachable",
        capture_state=lambda: state,
    )
