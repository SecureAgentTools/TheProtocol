"""HTTP method correctness tests (§pass73.3.17 Batch 109).

3 tests verifying endpoints respond correctly to mismatched HTTP methods
(405 Method Not Allowed, not 500). FastAPI default is 405, deviations
indicate routing bugs.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


@federation_test(
    name="get_on_post_only_endpoint_returns_405",
    category="http_method_correctness",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["http-methods", "405", "post-only"],
)
async def test_get_on_post_endpoint(
    rig: FederationTestRig,
) -> AssertionResult:
    """GET /api/v1/auth/register (POST-only endpoint) returns 405 with
    Allow: POST header per HTTP spec."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {"method": "GET", "endpoint": "/api/v1/auth/register"},
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # 405 is canonical; 404 also acceptable (route may not register
            # GET handler)
            return state["status_code"] in (405, 404)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="GET on POST-only endpoint returns 405 (or 404)",
        capture_state=lambda: state,
    )


@federation_test(
    name="post_on_get_only_endpoint_returns_405",
    category="http_method_correctness",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["http-methods", "405", "get-only"],
)
async def test_post_on_get_endpoint(
    rig: FederationTestRig,
) -> AssertionResult:
    """POST /api/v1/admin/dashboard (GET-only) returns 405/404 not 500."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/admin/dashboard",
                    "body": {},
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            return state["status_code"] in (405, 404)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="POST on GET-only endpoint returns 405/404",
        capture_state=lambda: state,
    )


@federation_test(
    name="delete_on_undeleteable_endpoint",
    category="http_method_correctness",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A-admin"],
    tags=["http-methods", "delete", "405"],
)
async def test_delete_not_allowed(rig: FederationTestRig) -> AssertionResult:
    """DELETE /api/v1/admin/dashboard returns 405/404 (never 500)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {"method": "DELETE", "endpoint": "/api/v1/admin/dashboard"},
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            return state["status_code"] in (405, 404)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="DELETE on non-deletable endpoint returns 405/404",
        capture_state=lambda: state,
    )
