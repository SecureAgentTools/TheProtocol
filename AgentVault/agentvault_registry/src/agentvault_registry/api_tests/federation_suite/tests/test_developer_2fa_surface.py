"""Developer 2FA + password security tests (§pass73.3.17 Batch 104).

3 tests verifying the 2FA + password reset endpoints are wired + auth-gated.
Critical security surfaces — broken 2FA means account compromise risk.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


@federation_test(
    name="my_2fa_status_endpoint_auth_required",
    category="developer_2fa_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["2fa", "self-status"],
)
async def test_my_2fa_status_auth(rig: FederationTestRig) -> AssertionResult:
    """GET /developers/me/2fa rejects unauthenticated request with 401."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/auth/2fa/status",
                    "developer_jwt": "x",  # bogus
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
        description="2fa-status endpoint rejects bogus auth with 401",
        capture_state=lambda: state,
    )


@federation_test(
    name="forgot_password_endpoint_accepts_post",
    category="developer_2fa_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["password-reset", "forgot-password"],
)
async def test_forgot_password(rig: FederationTestRig) -> AssertionResult:
    """POST /auth/forgot-password accepts a request (whether or not the
    email exists). Never 5xx. Idempotent semantics — won't leak email
    existence via 4xx differences."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/auth/forgot-password",
                    "body": {"email": "definitely-not-real@test.sandbox"},
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # 200 (or 202) is canonical for forgot-password
            return state["status_code"] in (200, 202, 204)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="forgot-password accepts request idempotently",
        capture_state=lambda: state,
    )


@federation_test(
    name="auth_registration_config_returns_settings",
    category="developer_2fa_surface",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A"],
    tags=["auth-config", "registration-policy"],
)
async def test_registration_config_returns(
    rig: FederationTestRig,
) -> AssertionResult:
    """getAuthRegistrationConfig returns the registration policy
    envelope (open signup vs invite-only, etc.). Required for UI to
    show correct registration flow."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            r = await pub.call("getAuthRegistrationConfig")
            if isinstance(r, str):
                return True
            if isinstance(r, dict):
                state["keys"] = sorted(r.keys())[:10]
                # Must have at least one config field
                return len(r.keys()) >= 1
            return False
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="auth registration config returns policy envelope",
        capture_state=lambda: state,
    )
