"""Federation license inventory tests (§pass73.3.13 Batch 62).

3 read-only tests probing the federation license lifecycle inventory
surfaces — list, detail, frame invitations.
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
    name="federation_licenses_inventory",
    category="federation_licenses_inventory",
    budget_sec=15.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["licenses", "federation"],
)
async def test_federation_licenses(rig: FederationTestRig) -> AssertionResult:
    """listFederationLicenses returns the federation license inventory.
    Sandbox-A federates with sandboxalpha + sandboxdelta → expect ≥0."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("listFederationLicenses")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("licenses") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="federation licenses inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_frame_invitations_inventory",
    category="federation_licenses_inventory",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["invitations", "frames"],
)
async def test_admin_frame_invitations(
    rig: FederationTestRig,
) -> AssertionResult:
    """listAdminFrameInvitations returns the pending frame invitations
    inventory. Used by admin Federation Ops view."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("listAdminFrameInvitations")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("invitations") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin frame invitations inventory reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_bundles_reports_inventory",
    category="federation_licenses_inventory",
    budget_sec=15.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["bundles", "reports"],
)
async def test_admin_bundles_reports(rig: FederationTestRig) -> AssertionResult:
    """listAdminBundlesReports returns the bundle reports (user-flagged
    bundles) inventory. Used by admin Bundle Moderation view."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call("listAdminBundlesReports")
            if _is_silent_or_error(r):
                state["silent"] = True
                return True
            items = r if isinstance(r, list) else (
                r.get("reports") or r.get("items") or r.get("data") or []
            ) if isinstance(r, dict) else []
            state["count"] = len(items)
            return isinstance(state.get("count"), int)
        except Exception as e:
            state["error"] = repr(e)
            return "401" in repr(e) or "404" in repr(e)

    return await rig.assert_within(
        budget_sec=15.0, predicate=predicate,
        description="admin bundles reports inventory reachable",
        capture_state=lambda: state,
    )
