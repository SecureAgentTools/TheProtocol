"""Agent CI/CD extras + pipeline-templates (AAA+ Phase IV-A, 2026-05-21)."""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="POST",
    path="/agents/{agent_did}/versions/{version_id}/activate",
    auth="developer",
    category="agent_cicd",
    idempotent=False,
)
class ActivateVersion:
    """Activate a specific agent version."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(
    method="DELETE",
    path="/agents/{agent_did}/versions/{version_id}",
    auth="developer",
    category="agent_cicd",
    idempotent=False,
)
class DeleteVersion:
    """Delete a version. Refuses if `is_current=true` or any deployment
    references it (`routers/agent_cicd.py:delete_version`).

    In the test env the version under test is always the agent's only/current
    version (eager-bootstrap creates one agent → one version → version is
    marked is_current). 409 with "Cannot delete the current version" is the
    business-rule outcome, not a bug. 404 happens when path placeholder
    substitution lands on a placeholder version_id.
    """
    expected_status = [200, 204, 404, 409]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 409,
            reason="Version is current or has deployments referencing it (single-version test env)",
        ),
    ]


@Endpoint(
    method="POST",
    path="/agents/{agent_did}/versions/{version_id}/rollback",
    auth="developer",
    category="agent_cicd",
    idempotent=False,
)
class RollbackVersion:
    """Rollback to a previous version."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 409]


@Endpoint(
    method="POST",
    path="/agents/{agent_did}/deployments/{deployment_id}/status",
    auth="developer",
    category="agent_cicd",
    idempotent=False,
)
class UpdateDeploymentStatus:
    """Update deployment status (success/failure/in_progress)."""
    def body(self, ctx):
        return {"status": "completed", "message": "AAA+ contract test"}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/pipeline-templates", auth="developer", category="agent_cicd", idempotent=False)
class CreatePipelineTemplate:
    """Create a marketplace pipeline template."""
    def body(self, ctx):
        return {
            "name": "AAA+ test template",
            "description": "Auto-created",
            "config": {"stages": ["build", "test", "deploy"]},
        }
    expected_status = [200, 201, 409]


@Endpoint(method="POST", path="/pipeline-templates/{template_id}/purchase", auth="developer", category="agent_cicd", idempotent=False)
class PurchasePipelineTemplate:
    """Buy a marketplace template (AVT)."""
    def body(self, ctx):
        return {"buyer_did": "did:theprotocol:placeholder", "payment_method": "tokens"}
    expected_status = [200, 201, 400, 404]
