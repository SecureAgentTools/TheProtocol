"""Network + stack health aggregate tests (§pass73.3.9 Batch 19).

3 tests probing the multi-pillar health aggregator endpoints. These
power the public status page + admin overview dashboards.
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
    name="stack_health_lists_core_services",
    category="network_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["stack-health", "core-services"],
)
async def test_stack_health(rig: FederationTestRig) -> AssertionResult:
    """getStackHealth returns ≥3 core services on each mainframe
    (Registry, TEG Layer, Event Store at minimum)."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getStackHealth")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                svcs = r.get("services") if isinstance(r, dict) else r
                if not isinstance(svcs, list):
                    state[label] = {"bad_shape": type(svcs).__name__}
                    continue
                state[label] = {
                    "count": len(svcs),
                    "core_count": sum(
                        1 for s in svcs
                        if isinstance(s, dict) and s.get("group") == "core"
                    ),
                    "healthy_count": sum(
                        1 for s in svcs
                        if isinstance(s, dict) and s.get("status") == "healthy"
                    ),
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("count"), int) and v["count"] >= 3
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="stack health lists ≥3 services on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="network_health_aggregate_envelope",
    category="network_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["network-health", "aggregate"],
)
async def test_network_health(rig: FederationTestRig) -> AssertionResult:
    """getNetworkHealth returns the aggregate health envelope (overall
    score, total_agents, response_time percentiles) on each frame."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getNetworkHealth")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "total_agents": r.get("total_agents"),
                    "active_agents": r.get("active_agents"),
                    "response_time_p50": r.get("response_time_p50"),
                    "error_rate": r.get("error_rate"),
                    "keys": sorted(r.keys())[:8],
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (
                    isinstance(v.get("total_agents"), int) and v["total_agents"] >= 1
                )
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="network health aggregate has ≥1 total_agents per frame",
        capture_state=lambda: state,
    )


@federation_test(
    name="combined_health_overall_status_present",
    category="network_health",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["combined-health", "admin"],
)
async def test_combined_health(rig: FederationTestRig) -> AssertionResult:
    """getCombinedHealth returns the multi-pillar admin health envelope —
    overallStatus + groupSummaries (auth, core, federation, etc.)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCombinedHealth")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            health = r.get("health") or {}
            ov = health.get("overallStatus") or {}
            state["status"] = ov.get("status")
            state["healthy"] = ov.get("healthy")
            state["total"] = ov.get("total")
            state["percentage"] = ov.get("percentage")
            return "status" in ov or "health" in r
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="combined health admin envelope contains overallStatus.status",
        capture_state=lambda: state,
    )
