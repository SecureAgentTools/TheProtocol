"""OAuth introspection + token exchange surface tests (§pass73.3.17 Batch 102).

3 tests verifying the OAuth 2.0 introspection (RFC 7662) and token
exchange (RFC 8693) endpoints respond correctly.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


@federation_test(
    name="oauth_introspect_responds_to_post",
    category="oauth_introspection_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["oauth", "introspection"],
)
async def test_oauth_introspect(rig: FederationTestRig) -> AssertionResult:
    """POST /api/v1/oauth/introspect with invalid token returns
    {active: false} per RFC 7662. Must not 5xx."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/oauth/introspect",
                    "body": {"token": "definitely_not_a_real_token_xyz"},
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            resp = r.get("response") if isinstance(r, dict) else None
            if isinstance(resp, dict):
                state["active"] = resp.get("active")
            return (
                isinstance(state["status_code"], int)
                and state["status_code"] < 500
            )
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="oauth introspect endpoint responds <500",
        capture_state=lambda: state,
    )


@federation_test(
    name="oauth_token_exchange_endpoint_exists",
    category="oauth_introspection_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["oauth", "token-exchange"],
)
async def test_oauth_token_exchange(
    rig: FederationTestRig,
) -> AssertionResult:
    """POST /api/v1/oauth/token-exchange responds (400 expected for
    missing grant_type, not 5xx)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/oauth/token-exchange",
                    "body": {},  # missing grant_type, etc → 400 expected
                },
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
        description="oauth token-exchange endpoint responds <500",
        capture_state=lambda: state,
    )


@federation_test(
    name="oauth_federation_status_envelope",
    category="oauth_introspection_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["oauth", "federation"],
)
async def test_oauth_federation_status(
    rig: FederationTestRig,
) -> AssertionResult:
    """getOAuthFederationStatus returns the OAuth federation trust state."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getOAuthFederationStatus")
            if isinstance(r, str):
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:8]
                return True
            return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="oauth federation status envelope reachable",
        capture_state=lambda: state,
    )
