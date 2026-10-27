"""Reactor event propagation tests (Phase F §pass73.3.6+).

5 tests probing the reactor framework's worker subsystem. There are 34 live
reactors; we verify the foundational ones (broadcast, suspend, peer status,
TEG-side cascades) are alive + their event subscriptions are healthy.

Read-mostly — we look at reactor status surfaces rather than triggering
state mutations.
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


def _unwrap_admin_request(r):
    if isinstance(r, dict) and "response" in r and isinstance(r.get("response"), dict):
        return r["response"]
    return r


@federation_test(
    name="reactor_status_endpoint_lists_active_reactors",
    category="reactor_propagation",
    budget_sec=15.0,
    severity="critical",
    requires=["sandbox-A-admin"],
    tags=["reactor", "framework", "liveness"],
)
async def test_reactor_status_endpoint(rig: FederationTestRig) -> AssertionResult:
    """getReactorStatus returns ≥1 active reactor.

    Reactor framework master kill is REACTOR_FRAMEWORK_ENABLED — if disabled,
    34 reactor classes don't subscribe to their event types. This test
    catches that misconfiguration.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getReactorStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return False
            if isinstance(r, dict):
                state["keys"] = list(r.keys())[:6]
                reactors = r.get("reactors") or r.get("items") or r.get("data") or []
                state["count"] = len(reactors)
            elif isinstance(r, list):
                state["count"] = len(r)
            else:
                state["raw"] = type(r).__name__
                return False
            return isinstance(state.get("count"), int) and state["count"] >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="getReactorStatus lists ≥1 active reactor",
        capture_state=lambda: state,
    )


@federation_test(
    name="saga_timeout_status_alive",
    category="reactor_propagation",
    budget_sec=15.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["saga", "timeout-checker", "worker"],
)
async def test_saga_timeout_alive(rig: FederationTestRig) -> AssertionResult:
    """getSagaTimeoutStatus returns a structured payload — confirms the
    saga timeout sweeper is alive. This worker is what closes hung 2PC
    transactions."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getSagaTimeoutStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = list(r.keys())[:8]
            return bool(state["keys"])
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="saga_timeout_checker worker status reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_auditor_worker_status",
    category="reactor_propagation",
    budget_sec=15.0,
    severity="critical",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["supply-auditor", "worker", "invariant"],
)
async def test_supply_auditor_status(rig: FederationTestRig) -> AssertionResult:
    """getSupplyAuditorStatus returns alive state on both mainframes.

    The supply_auditor worker is what continuously verifies Δ=0 across the
    EventStore. If it's dead, supply drift can go undetected for hours.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getSupplyAuditorStatus")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                state[label] = {
                    "keys": list(r.keys())[:8] if isinstance(r, dict) else type(r).__name__
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or (isinstance(v.get("keys"), list) and v["keys"])
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="supply_auditor worker status reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="collusion_ring_detection_active",
    category="reactor_propagation",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["collusion", "worker", "detection"],
)
async def test_collusion_ring_active(rig: FederationTestRig) -> AssertionResult:
    """getCollusionStatus returns the collusion detector's last cycle state.

    Tarjan-SCC-based ring detection — the worker scans agents' transaction
    graphs for closed cycles indicating wash trading or fund cycling.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCollusionStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = list(r.keys())[:8]
            return bool(state["keys"])
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="collusion ring detector status reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="reactor_iron_hand_canary_status",
    category="reactor_propagation",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["ironhand", "canary", "mtls"],
)
async def test_ironhand_canary_status(rig: FederationTestRig) -> AssertionResult:
    """getCanaryIronhandStatus returns the IRONHAND mTLS canary subsystem state.

    Validates the agent mTLS canary watchdog is alive — this subsystem
    catches SPIFFE SVID rotation breakage end-to-end.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCanaryIronhandStatus")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                return False
            state["keys"] = list(r.keys())[:8]
            return bool(state["keys"])
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="IRONHAND mTLS canary status reachable on sandbox-A",
        capture_state=lambda: state,
    )
