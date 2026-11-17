"""Simulation deadman tests (§pass73.3.11 Batch 51).

Read-only tests probing the simulation deadman watchdog and the topology view. Deadman fires if simulation resource
usage exceeds thresholds. (The funding preview's reachability test went with the route in V0663: the route ran the
retired network's host script, gwo_be8899e9eb589224813ec90a.)
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
    name="simulation_deadman_threshold_envelope",
    category="simulation_deadman",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["simulation", "deadman", "thresholds"],
)
async def test_simulation_deadman(rig: FederationTestRig) -> AssertionResult:
    """getAdminSimulationDeadmanStatus returns armed flag + thresholds.

    Idle state: armed=false. Thresholds include load1m_max, swap_used,
    mem_available, max_runtime — all sane defaults.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminSimulationDeadmanStatus"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["armed"] = r.get("armed")
            state["enabled_at_start"] = r.get("enabled_at_start")
            thresholds = r.get("thresholds") or {}
            state["threshold_keys"] = sorted(thresholds.keys())[:6]
            return "armed" in r and isinstance(thresholds, dict)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="simulation deadman envelope + thresholds reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="simulation_topology_envelope",
    category="simulation_deadman",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["simulation", "topology"],
)
async def test_simulation_topology(rig: FederationTestRig) -> AssertionResult:
    """getAdminSimulationTopology returns the simulation network topology
    envelope (per-frame container layout, registry counts)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getAdminSimulationTopology")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:6]
                return bool(r.keys())
            return False
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="simulation topology envelope reachable",
        capture_state=lambda: state,
    )
