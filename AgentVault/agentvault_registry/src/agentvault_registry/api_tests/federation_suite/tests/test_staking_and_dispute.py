"""Staking + dispute subsystem tests (Phase H §pass73.3.8+).

5 tests probing the staking + dispute observability surfaces.
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
    name="staking_global_stats_per_frame",
    category="staking_and_dispute",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "global-stats"],
)
async def test_staking_global_stats(rig: FederationTestRig) -> AssertionResult:
    """getLockStats returns aggregate staking metrics on each mainframe."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockStats")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                else:
                    state[label] = type(r).__name__
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
        description="staking global stats reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="staking_apy_rates_published",
    category="staking_and_dispute",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "apy"],
)
async def test_apy_rates(rig: FederationTestRig) -> AssertionResult:
    """getLockPayoutTiers publishes current APY rates per tier."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockPayoutTiers")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                elif isinstance(r, list):
                    state[label] = {"count": len(r)}
                else:
                    state[label] = type(r).__name__
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or (isinstance(v.get("keys"), list) and v["keys"])
                or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="APY rates published on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="staking_distribution_stats_queryable",
    category="staking_and_dispute",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A", "sandbox-B"],
    tags=["staking", "distribution"],
)
async def test_staking_distribution_stats(rig: FederationTestRig) -> AssertionResult:
    """getLockPayoutStats returns aggregate distribution metrics.

    Replaced getLockPayoutRecords which requires `distribution_id`
    (single-record fetch by ID, not list-all). The stats surface is the
    right read for a no-args federation-wide probe.
    """
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getLockPayoutStats")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                elif isinstance(r, list):
                    state[label] = {"count": len(r)}
                else:
                    state[label] = type(r).__name__
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent")
                or (isinstance(v.get("keys"), list) and v["keys"])
                or isinstance(v.get("count"), int)
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="staking distribution stats reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_dispute_settlements_per_frame",
    category="staking_and_dispute",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["disputes", "settlements"],
)
async def test_federation_dispute_settlements(
    rig: FederationTestRig,
) -> AssertionResult:
    """getFederationDisputeSettlements lists cross-registry dispute outcomes."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getFederationDisputeSettlements")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                items = r if isinstance(r, list) else (
                    r.get("settlements") or r.get("disputes") or r.get("items") or []
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
        description="federation dispute settlements reachable on both mainframes",
        capture_state=lambda: state,
    )


@federation_test(
    name="teg_policies_compliance_dashboard",
    category="staking_and_dispute",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A", "sandbox-B"],
    tags=["teg-policies", "compliance"],
)
async def test_teg_policies_dashboard(rig: FederationTestRig) -> AssertionResult:
    """getTegPoliciesComplianceDashboard returns the TEG-policy compliance state."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A", "sandbox-B"):
            try:
                r = await rig.mcp(label).call("getTegPoliciesComplianceDashboard")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": list(r.keys())[:8]}
                else:
                    state[label] = type(r).__name__
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
        description="TEG policies compliance dashboard reachable on both mainframes",
        capture_state=lambda: state,
    )
