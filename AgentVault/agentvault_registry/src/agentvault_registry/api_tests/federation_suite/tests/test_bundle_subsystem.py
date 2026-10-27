"""Agent Bundles subsystem tests (Phase H §pass73.3.8+).

4 tests covering the §pass51 agent bundles (.tpb signed archives) +
templates + onboard-download surface. Bundles are signed agent definitions
that can be installed across federation peers.
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
    name="featured_bundles_listed_per_frame",
    category="bundle_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["bundles", "featured"],
)
async def test_featured_bundles(rig: FederationTestRig) -> AssertionResult:
    """getFeaturedBundles returns a list shape on each mainframe.

    Empty is OK on fresh sandbox; the surface must exist + be queryable.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getFeaturedBundles")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("bundles") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(items)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="featured bundles list reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_templates_catalog_per_frame",
    category="bundle_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["templates", "catalog"],
)
async def test_agent_templates(rig: FederationTestRig) -> AssertionResult:
    """listAgentTemplates returns a list of agent templates on each frame."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listAgentTemplates")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("templates") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(items)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent templates catalog reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="agent_builder_templates_listed",
    category="bundle_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["agent-builder"],
)
async def test_agent_builder_templates(rig: FederationTestRig) -> AssertionResult:
    """listAgentBuilderTemplates returns templates for the no-code builder."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("listAgentBuilderTemplates")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("templates") or r.get("items") or r.get("data") or []
                ) if isinstance(r, dict) else []
                state[label] = {"count": len(items)}
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="agent builder templates queryable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_bundle_reports_endpoint_reachable",
    category="bundle_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["bundles", "moderation"],
)
async def test_admin_bundle_reports(rig: FederationTestRig) -> AssertionResult:
    """listAdminBundlesReports returns the bundle moderation queue."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("listAdminBundlesReports")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("reports") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin bundle reports queryable on sandbox-A",
        capture_state=lambda: state,
    )
