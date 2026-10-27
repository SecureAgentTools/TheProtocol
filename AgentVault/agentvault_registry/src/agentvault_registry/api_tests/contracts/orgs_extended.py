"""Organizations + Teams extended contracts (AAA+ Phase IV-A round 2, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="GET",
    path="/organizations/{org_id}/members",
    auth="developer",
    category="organizations",
    idempotent=True,
)
class OrgMembers:
    """List org members."""
    expected_status = [200, 404]


@Endpoint(
    method="GET",
    path="/organizations/{org_id}/teams",
    auth="developer",
    category="organizations",
    idempotent=True,
)
class OrgTeams:
    """List teams in an org."""
    expected_status = [200, 404]


@Endpoint(
    method="GET",
    path="/organizations/{org_id}/teams/{team_id}",
    auth="developer",
    category="organizations",
    idempotent=True,
)
class OrgTeamDetail:
    """Get team detail."""
    expected_status = [200, 404]


@Endpoint(
    method="GET",
    path="/organizations/{org_id}/teams/{team_id}/members",
    auth="developer",
    category="organizations",
    idempotent=True,
)
class OrgTeamMembers:
    """List team members."""
    expected_status = [200, 404]


@Endpoint(
    method="POST",
    path="/organizations/{org_id}/teams/{team_id}/members",
    auth="developer",
    category="organizations",
    idempotent=False,
)
class AddTeamMember:
    """Add a member to a team."""
    def body(self, ctx):
        return {"developer_id": 1, "role": "member"}
    expected_status = [200, 201, 404, 409]


@Endpoint(
    method="DELETE",
    path="/organizations/{org_id}/teams/{team_id}/members/{member_id}",
    auth="developer",
    category="organizations",
)
class RemoveTeamMember:
    """Remove a team member."""
    expected_status = [200, 204, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Member ID placeholder doesn't resolve",
        ),
    ]


@Endpoint(
    method="POST",
    path="/organizations/{org_id}/invitations/{invitation_token}/accept",
    auth="developer",
    category="organizations",
    idempotent=False,
)
class AcceptInvitation:
    """Accept an org invitation."""
    def body(self, ctx):
        return {}
    expected_status = [200, 400, 404, 410]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 404, 410),
            reason="Invitation token placeholder is not a real token",
        ),
    ]


@Endpoint(
    method="DELETE",
    path="/organizations/{org_id}/members/{developer_id}",
    auth="developer",
    category="organizations",
)
class RemoveOrgMember:
    """Remove a member from an org."""
    expected_status = [200, 204, 403, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 404),
            reason="Cannot remove non-existent member or insufficient permissions",
        ),
    ]


@Endpoint(
    method="POST",
    path="/organizations/{org_id}/agents/{agent_did}/assign",
    auth="developer",
    category="organizations",
    idempotent=False,
)
class AssignAgentToOrg:
    """Assign an agent to an org."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(
    method="POST",
    path="/organizations/{org_id}/agents/{agent_did}/unassign",
    auth="developer",
    category="organizations",
    idempotent=True,
)
class UnassignAgentFromOrg:
    """Unassign an agent from an org."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


@Endpoint(
    method="DELETE",
    path="/organizations/{org_id}",
    auth="developer",
    category="organizations",
)
class DeleteOrganization:
    """Delete an org (admin-only)."""
    expected_status = [200, 204, 403, 404]


@Endpoint(
    method="GET",
    path="/organizations/{org_id}/agents",
    auth="developer",
    category="organizations",
    idempotent=True,
)
class OrgAgents:
    """List agents in an org."""
    expected_status = [200, 404]
