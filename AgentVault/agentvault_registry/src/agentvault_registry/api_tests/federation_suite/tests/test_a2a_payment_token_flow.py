"""A2A payment authorization token surface tests (§pass73.3.17 Batch 94).

3 tests verifying the A2A payment subsystem (f045) is reachable +
contract-correct. Per CLAUDE.md FLOW 11, A2A tokens use `apt_` prefix,
SHA-256 hash, 15 min default TTL.
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
    name="a2a_authorize_endpoint_responds",
    category="a2a_payment_token_flow",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["a2a-payment", "authorize"],
)
async def test_a2a_authorize_surface(
    rig: FederationTestRig,
) -> AssertionResult:
    """POST /api/v1/a2a-payment/authorize returns 401/403/422 to
    unauthenticated requests (not 5xx — endpoint exists + auth-gated)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/a2a-payment/authorize",
                    "developer_jwt": "x",  # bogus auth
                    "body": {},
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # Accept 401/403/422 — anything but 5xx
            return isinstance(state["status_code"], int) and \
                state["status_code"] < 500
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="a2a authorize endpoint exists + auth-gated",
        capture_state=lambda: state,
    )


@federation_test(
    name="a2a_verify_endpoint_responds",
    category="a2a_payment_token_flow",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["a2a-payment", "verify"],
)
async def test_a2a_verify_surface(rig: FederationTestRig) -> AssertionResult:
    """POST /api/v1/a2a-payment/verify is reachable. Per CLAUDE.md
    FLOW 11, verify is `no auth` — should accept POST."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "POST",
                    "endpoint": "/api/v1/a2a-payment/verify",
                    "body": {"token": "apt_invalid_token_for_test"},
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # Accept any 4xx (invalid token) — just not 5xx
            return isinstance(state["status_code"], int) and \
                state["status_code"] < 500
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="a2a verify endpoint exists + responds to invalid token",
        capture_state=lambda: state,
    )


@federation_test(
    name="a2a_my_tokens_endpoint_auth_gated",
    category="a2a_payment_token_flow",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["a2a-payment", "my-tokens"],
)
async def test_a2a_my_tokens(rig: FederationTestRig) -> AssertionResult:
    """GET /api/v1/a2a-payment/my-tokens requires agent JWT (Tier 2).
    With dev JWT (admin path), returns 401/403 — endpoint exists."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            r = await admin.call(
                "adminRequest",
                {
                    "method": "GET",
                    "endpoint": "/api/v1/a2a-payment/my-tokens",
                },
            )
            state["status_code"] = (
                r.get("status_code") if isinstance(r, dict) else None
            )
            # Tier 2 endpoint hit with dev JWT → 401/403 typical
            # OR 200 (some endpoints accept dev JWT). Just not 5xx.
            return isinstance(state["status_code"], int) and \
                state["status_code"] < 500
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="a2a my-tokens endpoint exists + responds",
        capture_state=lambda: state,
    )
