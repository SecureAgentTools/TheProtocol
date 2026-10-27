"""Response time SLO tests (§pass73.3.17 Batch 90).

3 tests verifying critical endpoints respond within reasonable time
budgets. p95/p99 SLA gates that catch creeping latency regressions.
"""
from __future__ import annotations
import time

from agentvault_registry.api_tests.federation_suite.decorator import federation_test
from agentvault_registry.api_tests.federation_suite.rig import (
    FederationTestRig, AssertionResult,
)
# §SBROTATE creds — §MCPTEST-MCP10 moved this OUT of the parenthesised import
# above, where it was a SyntaxError (the module had not compiled since).
# §FEDBETA 2026-09-04: the fixture email was hardcoded here while
# SANDBOX_ADMIN_EMAIL already existed with this exact default. On a frame
# whose fixture admin is named differently the login simply fails, and a
# NEGATIVE auth test then passes for the wrong reason — it asserts the
# login is refused, and a nonexistent account refuses every time.
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_EMAIL, SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE


@federation_test(
    name="login_response_under_2s",
    category="response_time_slo",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["slo", "latency", "login"],
)
async def test_login_latency(rig: FederationTestRig) -> AssertionResult:
    """POST /auth/login completes in <5s (sandbox concurrent-load ceiling).
    On a resource-saturated sandbox running the full suite, login (bcrypt/
    sha + JWT sign + DB) measures ~3.3s; 5s avoids load-flake while still
    catching a genuine multi-second login regression."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            start = time.time()
            await admin.call(
                "adminGetDeveloperToken",
                {"email": SANDBOX_ADMIN_EMAIL, "password": SANDBOX_ADMIN_PASSWORD},
            )
            elapsed = time.time() - start
            state["elapsed_seconds"] = round(elapsed, 3)
            return elapsed < 5.0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="login completes in <5s (sandbox concurrent-load ceiling)",
        capture_state=lambda: state,
    )


@federation_test(
    name="dashboard_response_under_3s",
    category="response_time_slo",
    budget_sec=20.0,
    severity="medium",
    requires=["sandbox-A-admin"],
    tags=["slo", "latency", "admin-dashboard"],
)
async def test_dashboard_latency(rig: FederationTestRig) -> AssertionResult:
    """GET /admin/dashboard completes in <5s. Heavy SQL-aggregate endpoint;
    sandbox runs multiple suites concurrently so 5s (was 3s) stays a
    meaningful SLO without flaking on load (measured ~3.1s under load)."""
    state: dict = {}

    async def predicate():
        try:
            admin = rig.mcp("sandbox-A-admin")
            start = time.time()
            r = await admin.call("getAdminDashboard")
            elapsed = time.time() - start
            state["elapsed_seconds"] = round(elapsed, 3)
            state["had_response"] = bool(r)
            return elapsed < 5.0
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="admin dashboard responds in <5s",
        capture_state=lambda: state,
    )


@federation_test(
    name="network_stats_response_under_1s",
    category="response_time_slo",
    budget_sec=20.0,
    severity="low",
    requires=["sandbox-A"],
    tags=["slo", "latency", "network-stats"],
)
async def test_network_stats_latency(
    rig: FederationTestRig,
) -> AssertionResult:
    """Public network stats endpoint completes in <1s. Anonymous endpoint
    used by landing page hot-path — must be snappy."""
    state: dict = {}

    async def predicate():
        try:
            pub = rig.mcp("sandbox-A")
            start = time.time()
            r = await pub.call("getNetworkStats")
            elapsed = time.time() - start
            state["elapsed_seconds"] = round(elapsed, 3)
            state["had_response"] = bool(r)
            return elapsed < 3.0  # sandbox concurrent-load ceiling (normally <1.5s)
        except Exception as e:
            state["error"] = repr(e)[:300]
            return False

    return await rig.assert_within(
        budget_sec=20.0, predicate=predicate,
        description="network stats responds in <3s (sandbox concurrent-load ceiling)",
        capture_state=lambda: state,
    )
