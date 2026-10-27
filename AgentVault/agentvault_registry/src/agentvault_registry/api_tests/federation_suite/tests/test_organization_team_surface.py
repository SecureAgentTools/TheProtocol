"""Organization + team surface tests (§pass73.3.17 Batch 103).

3 tests verifying the org/team subsystem endpoints are reachable.
Organizations are the multi-tenancy primitive — broken org endpoints
mean teams can't onboard.
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
    name="my_organizations_endpoint_reachable",
    category="organization_team_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["organizations", "self"],
)
async def test_my_organizations(rig: FederationTestRig) -> AssertionResult:
    """getMyOrganizations endpoint reachable via admin bridge. May be
    empty for commander (typically not in test orgs) — surface check."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/organizations/me"},
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            return (
                isinstance(state["status_code"], int)
                and state["status_code"] < 500
            )
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="my-organizations endpoint reachable",
        capture_state=lambda: state,
    )


@federation_test(
    name="organization_creation_requires_auth",
    category="organization_team_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["organizations", "create", "auth-required"],
)
async def test_org_create_auth_required(
    rig: FederationTestRig,
) -> AssertionResult:
    """POST /organizations without auth must return 401. Org creation
    is dev-only — unauthenticated must fail."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/organizations",
                    "developer_jwt": "x",  # bogus auth
                    "body": {"name": "test-unauth-org"},
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            return state["status_code"] == 401
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="POST /organizations rejects unauthenticated request (401)",
        capture_state=lambda: state,
    )


@federation_test(
    name="public_org_by_slug_404_for_unknown",
    category="organization_team_surface",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["organizations", "by-slug", "404"],
)
async def test_org_by_slug_404(rig: FederationTestRig) -> AssertionResult:
    """GET /organizations/by-slug/{slug} returns 404 for non-existent
    slug — endpoint exists + handles not-found cleanly."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/organizations/by-slug/no-such-org-xyz123",
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            return state["status_code"] == 404
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="organizations/by-slug returns 404 for unknown slug",
        capture_state=lambda: state,
    )
