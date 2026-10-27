"""Misc admin contracts (AAA+ Phase II-B, 2026-05-21).

Catch-all for admin endpoints not covered by topic files.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/admin/cloud-operators", auth="developer", category="cloud_operators_(admin)", idempotent=True)
class CloudOperatorsList:
    """List cloud-hosted operator applications."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/cloud-operators/{application_id}/health",
    auth="developer",
    category="cloud_operators_(admin)",
    idempotent=True,
)
class CloudOperatorHealth:
    """Health of a specific cloud-hosted operator."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/enforcement/registries/quarantined", auth="developer", category="admin_enforcement", idempotent=True)
class QuarantinedRegistries:
    """List quarantined peer registries."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/enforcement/agents/{agent_did}/slash-preview",
    auth="developer",
    category="enforcement_admin",
)
class SlashPreview:
    """Preview slash amount for an agent."""
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Endpoint requires ?amount query param",
        ),
    ]


@Endpoint(method="POST", path="/admin/support/tickets/{ticket_id}/status", auth="developer", category="admin_platform", idempotent=False)
class AdminUpdateTicketStatus:
    """Admin updates a support ticket status."""
    def body(self, ctx):
        return {"status": "closed", "note": "AAA+ contract test"}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Ticket ID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/admin/support/tickets/{ticket_id}/reply", auth="developer", category="admin_platform", idempotent=False)
class AdminReplyToTicket:
    """Admin replies to a support ticket."""
    def body(self, ctx):
        return {"message": "AAA+ contract test reply"}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Ticket ID placeholder",
        ),
    ]


@Endpoint(method="GET", path="/admin/support/tickets", auth="developer", category="admin_platform", idempotent=True)
class AdminListTickets:
    """List all support tickets."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/broadcasts", auth="developer", category="admin_broadcasts", idempotent=False)
class CreateBroadcast:
    """Create a new broadcast notification."""
    def body(self, ctx):
        return {
            "title": "AAA+ contract test broadcast",
            "body": "Auto-created by API tester contracts",
            "level": "info",
            "audience": "developers",
        }
    expected_status = [200, 201]


@Endpoint(method="GET", path="/admin/broadcasts", auth="developer", category="admin_broadcasts", idempotent=True)
class ListBroadcasts:
    """List all broadcasts."""
    expected_status = 200


@Endpoint(method="POST", path="/admin/ironhand/revoke/{agent_did}", auth="developer", category="ironhand_monitoring_(admin)", idempotent=False)
class IronhandRevoke:
    """Admin revokes an agent's IRONHAND mTLS SVID."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/admin/ironhand/enroll/{agent_did}", auth="developer", category="ironhand_monitoring_(admin)", idempotent=False)
class IronhandEnroll:
    """Admin enrolls an agent in IRONHAND mTLS."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Agent already enrolled",
        ),
    ]


@Endpoint(method="POST", path="/admin/funding/{request_id}/approve", auth="developer", category="funding_admin", idempotent=False)
class ApproveFunding:
    """Admin approves a funding request."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Request ID placeholder",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Request already approved/rejected",
        ),
    ]


@Endpoint(method="POST", path="/admin/funding/{request_id}/reject", auth="developer", category="funding_admin", idempotent=False)
class RejectFunding:
    """Admin rejects a funding request."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test rejection"}
    expected_status = [200, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Request ID placeholder",
        ),
    ]


@Endpoint(method="GET", path="/admin/funding/requests", auth="developer", category="funding_admin", idempotent=True)
class ListFundingRequests:
    """List all funding requests (filterable by status)."""
    expected_status = 200
