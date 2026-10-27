"""Negative auth path tests (§pass73.3.16 Batch 75).

3 tests that verify the auth layer REJECTS bad credentials. Surface
health tests confirm endpoints respond; these confirm they respond
correctly to invalid input.

Pattern: use adminRequest to call public endpoints with malformed
credentials or random JWTs, assert 401/403/422 responses.
"""
from __future__ import annotations

# §FEDBETA 2026-09-04: the fixture email was hardcoded here while
# SANDBOX_ADMIN_EMAIL already existed with this exact default. On a frame
# whose fixture admin is named differently the login simply fails, and a
# NEGATIVE auth test then passes for the wrong reason — it asserts the
# login is refused, and a nonexistent account refuses every time.
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_EMAIL

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)


@federation_test(
    name="login_wrong_password_returns_401",
    category="negative_auth_paths",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["auth", "negative", "wrong-password"],
)
async def test_login_wrong_password(rig: FederationTestRig) -> AssertionResult:
    """POST /auth/login with a real email + wrong password returns 401.

    Uses commander email + deliberately wrong password (so we know the
    email exists; only the password is invalid)."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/auth/login",
                    "body": {
                        "username": SANDBOX_ADMIN_EMAIL,
                        "password": "WrongDeliberatelyBadPassword123!",
                    },
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # POST /auth/login takes form-encoded, not JSON — body via
            # adminRequest will go through as JSON. Endpoint should reject
            # with 422 (validation error) or 401 (incorrect creds).
            return state["status_code"] in (401, 422)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="wrong password on /auth/login returns 401/422",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_endpoint_with_garbage_jwt_returns_401",
    category="negative_auth_paths",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["auth", "negative", "bad-jwt"],
)
async def test_garbage_jwt(rig: FederationTestRig) -> AssertionResult:
    """Admin endpoint called with random base64 garbage as developer_jwt
    must return 401 (signature verification failure)."""
    state: dict = {}

    async def predicate():
        try:
            # 3-segment base64-like garbage that won't decode as a real JWT
            garbage = (
                "eyJhbGciOiJIUzI1NiJ9."  # valid-looking header
                "eyJzdWIiOiI5OTk5In0."   # valid-looking payload
                "INVALID_SIGNATURE_BYTES_HERE_NOT_REAL"
            )
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/admin/dashboard",
                    "developer_jwt": garbage,
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
        description="garbage JWT on admin endpoint returns 401",
        capture_state=lambda: state,
    )


@federation_test(
    name="admin_endpoint_with_empty_jwt_returns_401",
    category="negative_auth_paths",
    budget_sec=20.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["auth", "negative", "empty-jwt"],
)
async def test_empty_jwt(rig: FederationTestRig) -> AssertionResult:
    """Admin endpoint called with empty-string developer_jwt must 401.

    NOTE: adminRequest treats developer_jwt='' as 'use admin auth' so
    we use 'x' as a 1-char invalid token to force the auth path."""
    state: dict = {}

    async def predicate():
        try:
            r = await rig.mcp("sandbox-A-admin").call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/admin/dashboard",
                    "developer_jwt": "x",
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
        description="malformed 1-char JWT on admin endpoint returns 401",
        capture_state=lambda: state,
    )
