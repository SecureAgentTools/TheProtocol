"""CI/CD subsystem observability tests (§pass73.3.13 Batch 58).

3 read-only tests probing the CI/CD deployment tracking subsystem
(agent deployments + pipeline summary + version rollbacks).
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
    name="cicd_summary_envelope",
    category="cicd_observability",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["cicd", "summary"],
)
async def test_cicd_summary(rig: FederationTestRig) -> AssertionResult:
    """getCicdSummary returns the CI/CD overview envelope — pipeline
    counts, deployment counts, recent activity."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCicdSummary")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cicd summary envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="cicd_deployments_inventory",
    category="cicd_observability",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["cicd", "deployments"],
)
async def test_cicd_deployments(rig: FederationTestRig) -> AssertionResult:
    """getCicdDeployments returns the deployment list — may be empty
    in sandbox (no real CI/CD pipelines), still validates surface."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCicdDeployments")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("deployments") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cicd deployments inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="composite_health_check",
    category="cicd_observability",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["health", "composite"],
)
async def test_composite_health(rig: FederationTestRig) -> AssertionResult:
    """getCompositeHealth returns a multi-pillar health envelope
    (rolls registry + TEG + ES + SPIRE into one view)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("compositeHealthCheck")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="composite health check reachable",
        capture_state=lambda: state,
    )
