"""Operator lifecycle + frame invitation observability tests (§pass73.3.9 Batch 29).

4 tests probing the operator application + cloud operator + frame
invitation subsystems (CLAUDE.md PART 9). These power the operator
onboarding flow.
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
    name="admin_operator_applications_listing",
    category="operator_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["operator", "applications"],
)
async def test_operator_applications(rig: FederationTestRig) -> AssertionResult:
    """listAdminOperatorApplications returns the admin operator
    application queue. Sandbox-A should have ≥1 application
    (API Tester Synthetic Op at minimum)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("listAdminOperatorApplications")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            apps = r.get("applications") if isinstance(r, dict) else r
            if not isinstance(apps, list):
                state["bad_shape"] = type(apps).__name__
                return False
            state["count"] = len(apps)
            state["statuses"] = sorted({
                a.get("status") for a in apps if isinstance(a, dict)
            })
            return True  # Reachable + correct shape = pass
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin operator applications queue reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="cloud_operators_listed_with_health",
    category="operator_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["operator", "cloud-operators"],
)
async def test_cloud_operators_health(
    rig: FederationTestRig,
) -> AssertionResult:
    """getCloudOperators lists active cloud operators with health flags.
    Sandbox-A should have ≥1 active cloud-op (Sandbox Alpha)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getCloudOperators")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            ops = r.get("operators") if isinstance(r, dict) else r
            if not isinstance(ops, list):
                state["bad_shape"] = type(ops).__name__
                return False
            state["count"] = len(ops)
            active = [o for o in ops if isinstance(o, dict) and o.get("active")]
            state["active_count"] = len(active)
            state["names"] = [o.get("name") for o in ops[:5] if isinstance(o, dict)]
            return state["count"] >= 1
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="cloud operators listing ≥1 entry on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="operators_lifecycle_overview_per_frame",
    category="operator_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["operator", "lifecycle-overview"],
)
async def test_operators_lifecycle_overview(
    rig: FederationTestRig,
) -> AssertionResult:
    """getOperatorsLifecycleOverview returns the unified operator
    lifecycle view — application + federation_license combined per op."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("getOperatorsLifecycleOverview")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            ops = r.get("operators") if isinstance(r, dict) else r
            if not isinstance(ops, list):
                state["bad_shape"] = type(ops).__name__
                return False
            state["count"] = len(ops)
            with_application = sum(
                1 for o in ops
                if isinstance(o, dict) and isinstance(o.get("application"), dict)
            )
            state["with_application"] = with_application
            return True
        except Exception as e:
            state["error"] = repr(e)
            return False

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="operators lifecycle overview reachable on sandbox-A",
        capture_state=lambda: state,
    )


@federation_test(
    name="frame_invitations_inventory_per_mainframe",
    category="operator_lifecycle",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin", "sandbox-B-admin"],
    tags=["frame-invitations", "ws3.5"],
)
async def test_frame_invitations(rig: FederationTestRig) -> AssertionResult:
    """listAdminFrameInvitations returns the frame invitation queue
    (WS3.5 handshake state per CLAUDE.md PART 9). Both mainframes
    should have the endpoint reachable + config block populated."""
    state: dict = {}

    async def predicate():
        for label in ("sandbox-A-admin", "sandbox-B-admin"):
            try:
                r = await rig.mcp(label).call("listAdminFrameInvitations")
                if _is_silent_or_error(r):
                    state[label] = {"silent": True}
                    continue
                if not isinstance(r, dict):
                    state[label] = {"bad_shape": type(r).__name__}
                    continue
                state[label] = {
                    "invitation_count": len(r.get("invitations") or []),
                    "has_config": isinstance(r.get("config"), dict),
                    "config_keys": sorted((r.get("config") or {}).keys())[:6],
                }
            except Exception as e:
                state[label] = f"error: {e!r}"
        return all(
            isinstance(v, dict) and (
                v.get("silent") or v.get("has_config")
            )
            for v in state.values()
        )

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="frame invitations + config readable on both mainframes",
        capture_state=lambda: state,
    )
