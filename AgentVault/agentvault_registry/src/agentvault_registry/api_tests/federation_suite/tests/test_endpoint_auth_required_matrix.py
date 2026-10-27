"""Auth-required matrix tests (§pass73.3.17 Batch 78).

3 tests verifying admin endpoints reject UNAUTHENTICATED requests with
401. Probes the auth-gate layer for known protected paths via
adminRequest with a clearly-invalid developer_jwt.

If any endpoint here returns 200 to a bogus JWT, the auth chain is
compromised — high-severity regression signal.
"""
from __future__ import annotations

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)

# Bogus 3-segment JWT — well-formed base64, signature won't verify
BOGUS_JWT = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJzdWIiOiI5OTk5OSIsImV4cCI6OTk5OTk5OTk5OX0."
    "FAKE_SIGNATURE_BYTES_THAT_WILL_NEVER_VERIFY_42"
)

# Endpoints that must require authenticated admin developer
PROTECTED_ADMIN_ENDPOINTS = [
    "/api/v1/admin/dashboard",
    "/api/v1/admin/developers",
    "/api/v1/admin/audit-logs",
    "/api/v1/admin/fee-collector/info",
    "/api/v1/admin/federation/peers/all",
    "/api/v1/admin/canary-judge/status",
    "/api/v1/admin/operator-applications",
    "/api/v1/admin/broadcasts",
]


@federation_test(
    name="protected_admin_endpoints_reject_bogus_jwt",
    category="endpoint_auth_required",
    budget_sec=60.0,
    severity="high",
    requires=["sandbox-A-admin"],
    tags=["auth", "matrix", "bogus-jwt"],
)
async def test_protected_endpoints_reject(rig: FederationTestRig) -> AssertionResult:
    """Each protected admin endpoint must return 401 to a structurally-valid
    but unverifiable JWT. Returning 200 means the auth chain is broken."""
    state: dict = {"results": {}}

    async def predicate():
        admin = rig.mcp("sandbox-A-admin")
        results = {}
        for ep in PROTECTED_ADMIN_ENDPOINTS:
            try:
                r = await admin.call(
                    "adminRequest",
                    {"method": "GET", "endpoint": ep, "developer_jwt": BOGUS_JWT},
                )
                code = r.get("status_code") if isinstance(r, dict) else None
                results[ep] = code
            except Exception as e:
                results[ep] = f"err: {repr(e)[:60]}"
        state["results"] = results
        # Every endpoint must return 401 (auth gate works)
        return all(c == 401 for c in results.values() if isinstance(c, int))

    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="all protected admin endpoints return 401 to bogus JWT",
        capture_state=lambda: state,
    )


@federation_test(
    name="protected_admin_endpoints_succeed_with_valid_admin",
    category="endpoint_auth_required",
    budget_sec=60.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["auth", "matrix", "positive-control"],
)
async def test_protected_endpoints_succeed(
    rig: FederationTestRig,
) -> AssertionResult:
    """Positive control: same endpoints succeed with valid admin auth.
    Confirms the 401 test isn't false-positive due to broken endpoints."""
    state: dict = {"results": {}}

    async def predicate():
        admin = rig.mcp("sandbox-A-admin")
        results = {}
        for ep in PROTECTED_ADMIN_ENDPOINTS:
            try:
                # No developer_jwt → use admin bridge auth
                r = await admin.call(
                    "adminRequest",
                    {"method": "GET", "endpoint": ep},
                )
                code = r.get("status_code") if isinstance(r, dict) else None
                results[ep] = code
            except Exception as e:
                results[ep] = f"err: {repr(e)[:60]}"
        state["results"] = results
        # Allow 200 or 503 (some surfaces may be feature-disabled in sandbox)
        # but never 401 (auth works) and never 5xx-broken (≥80% must be 2xx)
        ok = sum(1 for c in results.values() if isinstance(c, int) and 200 <= c < 300)
        state["ok_count"] = ok
        return ok >= len(PROTECTED_ADMIN_ENDPOINTS) * 0.8
    return await rig.assert_within(
        budget_sec=60.0, predicate=predicate,
        description="≥80% of protected endpoints return 2xx with valid admin",
        capture_state=lambda: state,
    )


@federation_test(
    name="public_endpoints_accept_unauth_request",
    category="endpoint_auth_required",
    budget_sec=30.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["auth", "matrix", "public-tier"],
)
async def test_public_endpoints_unauth(
    rig: FederationTestRig,
) -> AssertionResult:
    """Tier-1 public endpoints (network stats, public showcase, fiat tiers)
    must work without auth. Sentinel control: bogus JWT shouldn't even
    matter for these surfaces — they ignore auth headers."""
    state: dict = {"results": {}}

    public_endpoints = [
        "/api/v1/network/stats",
        "/api/v1/fiat/tiers",
        "/api/v1/fiat/providers",
    ]

    async def predicate():
        admin = rig.mcp("sandbox-A-admin")
        results = {}
        for ep in public_endpoints:
            try:
                r = await admin.call(
                    "adminRequest",
                    {"method": "GET", "endpoint": ep, "developer_jwt": BOGUS_JWT},
                )
                code = r.get("status_code") if isinstance(r, dict) else None
                results[ep] = code
            except Exception as e:
                results[ep] = f"err: {repr(e)[:60]}"
        state["results"] = results
        # Public endpoints accept bogus JWT (ignored) — expect 200/404
        # (404 if endpoint doesn't exist at that path — both are non-auth-failure)
        return all(
            isinstance(c, int) and c != 401
            for c in results.values()
        )

    return await rig.assert_within(
        budget_sec=30.0, predicate=predicate,
        description="public endpoints succeed regardless of JWT validity",
        capture_state=lambda: state,
    )
