"""Funding contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/funding/request", auth="agent", category="funding", idempotent=False)
class FundingRequest:
    """Agent submits a funding request."""
    def body(self, ctx):
        return {"amount": "1000", "reason": "AAA+ contract test request"}
    expected_status = [200, 201, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="3 pending requests per agent limit",
        ),
    ]


@Endpoint(method="GET", path="/funding/my-requests", auth="agent", category="funding", idempotent=True)
class MyFundingRequests:
    """Caller's funding request history."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/funding/pending", auth="developer", category="funding_admin", idempotent=True)
class AdminPendingFunding:
    """Admin list of pending funding requests."""
    expected_status = 200
