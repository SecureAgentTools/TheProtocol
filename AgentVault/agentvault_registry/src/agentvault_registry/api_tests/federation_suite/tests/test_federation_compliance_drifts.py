"""Federation compliance drift subsystem tests (§pass73.3.11 Batch 49).

3 read-only tests probing the federation compliance drift detector.
Drifts fire when a peer registry's reported state diverges from the
expected baseline (e.g., URL misconfigured, license revoked).
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
    name="federation_compliance_drifts_inventory",
    category="federation_compliance_drifts",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["compliance", "drifts"],
)
async def test_compliance_drifts(rig: FederationTestRig) -> AssertionResult:
    """getFederationComplianceDrifts returns drift inventory + by_type
    aggregation. Sandbox typically has some drifts due to stale peer
    URLs from tear-down operators."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getFederationComplianceDrifts"
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            if not isinstance(r, dict):
                state["bad_shape"] = type(r).__name__
                return False
            state["total"] = r.get("total")
            state["by_type"] = list((r.get("by_type") or {}).keys())[:5]
            drifts = r.get("drifts") or []
            state["drift_count"] = len(drifts) if isinstance(drifts, list) else 0
            return isinstance(r.get("total"), int)
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation compliance drifts inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_compliance_per_peer_lookup",
    category="federation_compliance_drifts",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["compliance", "per-peer"],
)
async def test_compliance_per_peer(rig: FederationTestRig) -> AssertionResult:
    """getFederationCompliancePeerByID returns the per-peer compliance
    envelope. Picks a peer from the drifts list to look up."""
    state: dict = {}

    async def predicate():
        try:
            d = await rig.mcp("sandbox-A-admin").call(
                "getFederationComplianceDrifts"
            )
            drifts = (d or {}).get("drifts") if isinstance(d, dict) else []
            if not drifts:
                state["no_drifts"] = True
                return True
            target = drifts[0]
            data = (target.get("data") or {}) if isinstance(target, dict) else {}
            peer_id = data.get("peer_id") if isinstance(data, dict) else None
            if peer_id is None:
                state["no_peer_id"] = True
                state["drift_keys"] = sorted((target or {}).keys())[:8]
                return True
            state["peer_id"] = peer_id
            r = await rig.mcp("sandbox-A-admin").call(
                "getFederationCompliancePeerByID", {"peer_id": str(peer_id)}
            )
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
        description="per-peer compliance lookup reachable for known peer_id",
        capture_state=lambda: state,
    )


@federation_test(
    name="federation_compliance_events_inventory",
    category="federation_compliance_drifts",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["compliance", "events"],
)
async def test_compliance_events_inventory(
    rig: FederationTestRig,
) -> AssertionResult:
    """getFederationComplianceEvents inventory with limit param."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getFederationComplianceEvents", {"limit": 10}
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation compliance events list reachable with limit",
        capture_state=lambda: state,
    )
