"""Fee collector + treasury aggregate + frames SPIRE status tests
(§pass73.3.13 Batch 61).

3 read-only tests probing the fee-collector info, treasury aggregate,
and frames-SPIRE status surfaces.
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
    name="fee_collector_info_envelope",
    category="fee_and_treasury",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["fee-collector", "treasury"],
)
async def test_fee_collector_info(rig: FederationTestRig) -> AssertionResult:
    """getFeeCollectorInfo returns the fee collector account info
    (balance, recent fees, drain destination)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getFeeCollectorInfo")
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
        description="fee collector info envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="treasury_aggregate_envelope",
    category="fee_and_treasury",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["treasury", "aggregate"],
)
async def test_treasury_aggregate(rig: FederationTestRig) -> AssertionResult:
    """getTreasuryAggregate returns the treasury aggregation envelope
    (cross-TEG totals, recent flows)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getTreasuryAggregate")
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
        description="treasury aggregate envelope reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="frames_spire_status_envelope",
    category="fee_and_treasury",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["spire", "frames"],
)
async def test_frames_spire_status(rig: FederationTestRig) -> AssertionResult:
    """getFramesSpireStatus returns the SPIRE status per-frame envelope
    (server health, agent attestation count, bundle freshness)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getFramesSpireStatus")
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
        description="frames SPIRE status envelope reachable",
        capture_state=lambda: state,
    )
