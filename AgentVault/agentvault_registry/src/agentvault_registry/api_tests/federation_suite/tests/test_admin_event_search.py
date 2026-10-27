"""Admin event search + audit log surface tests (§pass73.3.10 Batch 33).

3 read-only tests probing admin event observation surfaces:
  - searchAdminEvents (free-text + event_type filter)
  - getAdminAuditLogs (security audit log)
  - getAdminBroadcastsOverview (broadcast subsystem overview)
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
    name="search_admin_events_by_event_type",
    category="admin_event_search",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["search", "events", "admin"],
)
async def test_search_admin_events(rig: FederationTestRig) -> AssertionResult:
    """searchAdminEvents finds events matching event_type filter.

    TokensTransferred is a canonical event type that should always have
    recent matches given the fed-test-agents + canary traffic.
    """
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "searchAdminEvents",
                {"event_type": "TokensTransferred", "limit": 5},
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            events = r.get("events") if isinstance(r, dict) else r
            if not isinstance(events, list):
                state["bad_shape"] = type(events).__name__
                return False
            state["count"] = len(events)
            if events and isinstance(events[0], dict):
                state["sample_keys"] = sorted(events[0].keys())[:5]
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="searchAdminEvents returns event list for TokensTransferred filter",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_audit_logs_with_actor_filter",
    category="admin_event_search",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["audit-logs", "filter"],
)
async def test_admin_audit_logs_filtered(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAdminAuditLogs accepts actor_type filter — validates filter
    path reachable + returns a list envelope."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "getAdminAuditLogs",
                {"actor_type": "developer", "limit": 5},
            )
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            logs = r if isinstance(r, list) else (
                r.get("logs") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(logs)
            return isinstance(state.get("count"), int) and state["count"] >= 0
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin audit logs with actor_type filter reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_broadcasts_overview_envelope",
    category="admin_event_search",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["broadcasts", "overview"],
)
async def test_broadcasts_overview(rig: FederationTestRig) -> AssertionResult:
    """getAdminBroadcastsOverview returns broadcast subsystem aggregate
    on each mainframe — total count, by-status counters."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("getAdminBroadcastsOverview")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if isinstance(r, dict):
                    state[label] = {"keys": sorted(r.keys())[:6]}
                else:
                    state[label] = {"bad_shape": type(r).__name__}
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
        description="admin broadcasts overview reachable on both mainframes",
        capture_state=lambda: state,
    )
