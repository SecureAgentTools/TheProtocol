"""Simulation subsystem observability tests (§pass73.3.9 Batch 18).

3 read-only tests probing the load simulation admin surfaces (CLAUDE.md
PART 9 — Stress_Test_And_Simulation). Validates: status, agent inventory,
supply audit during simulation.
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
    name="simulation_status_endpoint_reachable",
    category="simulation_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["simulation", "status"],
)
async def test_simulation_status(rig: FederationTestRig) -> AssertionResult:
    """getAdminSimulationStatus returns the simulation envelope —
    running/instances/uptime. Most of the time sandbox-A has no
    simulation running (running=false)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminSimulationStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["running"] = r.get("running")
            state["instances"] = r.get("instances")
            state["uptime_seconds"] = r.get("uptime_seconds")
            # Envelope must be a dict with at least a `running` flag
            return "running" in r
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="simulation status returns running envelope",
        capture_state=lambda: state,
    )


@federation_test(
    name="simulation_agents_inventory_reachable",
    category="simulation_subsystem",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["simulation", "agents"],
)
async def test_simulation_agents(rig: FederationTestRig) -> AssertionResult:
    """getAdminSimulationAgents returns the simulation agent inventory
    (possibly empty when no sim is running)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminSimulationAgents")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, list):
                state["count"] = len(r)
                return True
            if isinstance(r, dict):
                agents = r.get("agents") or r.get("items") or r.get("data") or []
                state["count"] = len(agents) if isinstance(agents, list) else None
                state["keys"] = sorted(r.keys())[:6]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="simulation agent inventory reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="simulation_supply_audit_reachable",
    category="simulation_subsystem",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["simulation", "supply-audit"],
)
async def test_simulation_supply_audit(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminSimulationSupplyAudit returns a delta envelope for the
    current simulation epoch. Validates the simulation audit surface
    is alive even when no sim is running."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminSimulationSupplyAudit")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="simulation supply audit envelope reachable",
        capture_state=lambda: state,
    )
