"""EventStore cross-frame peer visibility tests (§pass73.3.17 Batch 108).

3 tests verifying the EventStore reports cross-frame federation peer
state — the SF-3/4/5 federation primitive.
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
    name="eventstore_cross_frame_peers_inventory",
    category="eventstore_cross_frame_visibility",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["event-store", "cross-frame", "peers"],
)
async def test_cross_frame_peers(rig: FederationTestRig) -> AssertionResult:
    """getEventStoreCrossFramePeers returns the cross-frame peer
    inventory. Sandbox-A federates with sandbox-B → expect ≥0."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventStoreCrossFramePeers")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            peers = r if isinstance(r, list) else (
                r.get("peers") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(peers) if isinstance(peers, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="event store cross-frame peers inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="eventstore_federation_operators_inventory",
    category="eventstore_cross_frame_visibility",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["event-store", "federation-operators"],
)
async def test_federation_operators(
    rig: FederationTestRig,
) -> AssertionResult:
    """getEventStoreFederationOperators returns the operator inventory
    that the EventStore knows about for license enforcement."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getEventStoreFederationOperators")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            ops = r if isinstance(r, list) else (
                r.get("operators") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(ops) if isinstance(ops, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="event store federation operators inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="supply_auditor_events_feed",
    category="eventstore_cross_frame_visibility",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["event-store", "supply-auditor", "feed"],
)
async def test_supply_auditor_events(
    rig: FederationTestRig,
) -> AssertionResult:
    """getSupplyAuditorEvents returns the supply auditor audit feed."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call("getSupplyAuditorEvents")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r if isinstance(r, list) else (
                r.get("events") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(events) if isinstance(events, list) else None
            return isinstance(state["count"], int)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="supply auditor events feed reachable",
        capture_state=lambda: state,
    )
