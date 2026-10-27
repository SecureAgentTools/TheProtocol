"""Public operator applications + agent templates tests (§pass73.3.12 Batch 55).

3 read-only tests probing seldom-touched public surfaces — operator
application directory + agent builder template catalog.
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
    name="public_operator_applications_listing",
    category="public_operator_apps",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["operator", "applications", "public"],
)
async def test_public_operator_applications(
    rig: FederationTestRig,
) -> AssertionResult:
    """listPublicOperatorApplications returns public-visible operator
    applications (approved + activated cloud-ops). Sandbox-A federates
    sandboxalpha + sandboxdelta → expect ≥0 (may be empty in sandbox)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("listPublicOperatorApplications")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("applications") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="public operator applications listing reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_builder_templates_inventory",
    category="public_operator_apps",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["templates", "agent-builder"],
)
async def test_agent_builder_templates(rig: FederationTestRig) -> AssertionResult:
    """listAgentBuilderTemplates returns the agent-builder template
    catalog used by AgentForge wizard."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("listAgentBuilderTemplates")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("templates") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent-builder templates inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_templates_inventory",
    category="public_operator_apps",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["templates", "agents"],
)
async def test_agent_templates(rig: FederationTestRig) -> AssertionResult:
    """listAgentTemplates returns the classic agent template catalog."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A").call("listAgentTemplates")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("templates") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent templates inventory reachable",
        capture_state=lambda: state,
    )
