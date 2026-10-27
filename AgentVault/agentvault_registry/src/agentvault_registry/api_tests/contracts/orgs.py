"""Organizations + teams contracts (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/organizations", auth="developer", category="organizations", idempotent=False)
class CreateOrganization:
    """Create an organization."""
    def body(self, ctx):
        return {"name": "AAA+ Test Org", "description": "Auto-created", "type": "company"}
    expected_status = [200, 201, 409]


@Endpoint(method="GET", path="/organizations", auth="developer", category="organizations", idempotent=True)
class ListOrganizations:
    """List orgs visible to caller."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/organizations/{org_id}",
    auth="developer",
    category="organizations",
)
class GetOrganization:
    """Get an org by ID."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Org ID placeholder",
        ),
    ]


@Endpoint(
    method="POST",
    path="/organizations/{org_id}/teams",
    auth="developer",
    category="organizations",
    idempotent=False,
)
class CreateTeam:
    """Create a team in an org."""
    def body(self, ctx):
        return {"name": "AAA+ Test Team", "description": "Auto-created"}
    expected_status = [200, 201, 404]


@Endpoint(method="POST", path="/organizations/{org_id}/invite", auth="developer", category="organizations", idempotent=False)
class InviteMember:
    """Invite a developer to an org."""
    def body(self, ctx):
        return {"email": "aaa-invite@theprotocol.cloud", "role": "member"}
    expected_status = [200, 201, 404, 409]


@Endpoint(method="GET", path="/organizations/{org_id}/cicd-summary", auth="developer", category="organizations", idempotent=True)
class OrgCicdSummary:
    """Per-org CI/CD aggregation."""
    expected_status = [200, 404]
