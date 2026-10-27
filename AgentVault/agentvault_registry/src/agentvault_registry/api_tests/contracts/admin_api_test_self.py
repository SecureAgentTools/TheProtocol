"""Admin API tester self-endpoints (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# These let the tester test its own admin endpoints (read-only ones safe).
@Endpoint(method="GET", path="/admin/api-test/sandbox-credentials", auth="developer", category="admin_api_test", idempotent=True)
class SandboxCredentials:
    """Get sandbox test credentials (admin-only)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/api-test/flow-values", auth="developer", category="admin_api_test", idempotent=True)
class FlowValues:
    """Get current flow values (DYNAMIC_VALUES snapshot)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/api-test/bucket-classification", auth="developer", category="admin_api_test", idempotent=True)
class BucketClassification:
    """Categories by bucket (AAA+ Phase III-C)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/api-test/archive/runs", auth="developer", category="admin_api_test", idempotent=True)
class ArchivedRuns:
    """List archived baseline runs (AAA+ Phase V)."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/api-test/reset-flow-values", auth="developer", category="admin_api_test", idempotent=True)
class ResetFlowValues:
    """Reset DYNAMIC_VALUES (safe between runs)."""
    def body(self, ctx):
        return {}
    expected_status = 200


@Endpoint(method="POST", path="/admin/api-test/reset-sandbox", auth="developer", category="admin_api_test", idempotent=False, slow_timeout_sec=120.0)
class ResetSandbox:
    """Reset the sandbox: re-seed and a fresh sentinel (slow). Since §RESETTRUNCATE (2026-09-29) nothing is truncated.

    §pass63 follow-up: PgBouncer max_client_conn was raised 800 → 1600 to
    eliminate the 500 "no more connections allowed" that fired when reset's
    36-table TRUNCATE in one transaction collided with the steady-state ~600
    idle client sessions. 500 EF kept as a defense-in-depth signal for future
    pool pressure regressions.
    """
    def body(self, ctx):
        return {}
    expected_status = [200, 403, 500, 503]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 503),
            reason="Sandbox reset requires SANDBOX_RESET_SECRET or env restriction",
        ),
        FailureMode.known_bug(
            condition=lambda r: r.status == 500 and "connections" in r.detail_lower(),
            reason="PgBouncer max_client_conn exhausted — raise the cap (§pass63 baseline 1600)",
            bug_id="PGBOUNCER-MAX-CLIENT-CONN",
        ),
    ]


@Endpoint(method="POST", path="/admin/api-test/test-category", auth="developer", category="admin_api_test", idempotent=False, slow_timeout_sec=300.0)
class TestCategoryEndpoint:
    """Self-test: hit own test-category endpoint."""
    def body(self, ctx):
        return {"category": "metrics"}  # tiny, fast category
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/api-test/eager-bootstrap", auth="developer", category="admin_api_test", idempotent=True, slow_timeout_sec=60.0)
class EagerBootstrapSelf:
    """Re-run eager bootstrap (AAA+ Phase III-A)."""
    def body(self, ctx):
        return {}
    expected_status = 200


# run-all is the legacy SmartTestRunner — keep its EF (deprecated path)
@Endpoint(method="GET", path="/admin/api-test/run-all", auth="developer", category="admin_api_test", idempotent=True, slow_timeout_sec=600.0)
class RunAllLegacy:
    """Legacy SmartTestRunner — deprecated. Returns 200 with partial results."""
    expected_status = [200, 504]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 504,
            reason="Legacy run-all may exceed BFF timeout — deprecated path",
        ),
    ]
