"""Account deletion contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode
from agentvault_registry.core.sandbox_creds import SANDBOX_ADMIN_PASSWORD, SANDBOX_TUTORIAL_PASSWORD  # §SBROTATE


@Endpoint(method="GET", path="/account/deletion-status", auth="developer", category="account_deletion", idempotent=True)
class DeletionStatus:
    """Caller's account deletion status."""
    expected_status = 200


@Endpoint(method="POST", path="/account/request-deletion", auth="developer", category="account_deletion", idempotent=False)
class RequestDeletion:
    """Request soft deletion (waiting period)."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test", "password": SANDBOX_ADMIN_PASSWORD}
    expected_status = [200, 202, 400]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 400 and "password" in r.detail_lower(),
            reason="Password mismatch on deletion request",
        ),
    ]


@Endpoint(method="POST", path="/account/cancel-deletion", auth="developer", category="account_deletion", idempotent=True)
class CancelDeletion:
    """Cancel a pending deletion."""
    def body(self, ctx):
        return {}
    expected_status = [200, 400, 409]
