"""Agent CI/CD contracts (AAA+ Phase II-B, 2026-05-21).

Pipeline / version / deployment lifecycle. Per §pass47 A3, bodies now strict Pydantic.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(
    method="POST",
    path="/agents/{agent_did}/pipelines",
    auth="developer",
    category="agent_cicd",
    idempotent=False,
)
class CreatePipeline:
    """Create a CI/CD pipeline for an agent."""
    def body(self, ctx):
        return {
            "name": "AAA+ contract test pipeline",
            "pipeline_config": {
                "stages": [
                    {"name": "test", "steps": [{"command": "pytest tests/"}]},
                    {"name": "build", "steps": [{"command": "docker build ."}]},
                ]
            },
            "trigger_type": "push",
        }
    expected_status = [200, 201, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder — no real agent",
        ),
    ]


@Endpoint(method="POST", path="/agents/{agent_did}/versions", auth="developer", category="agent_cicd", idempotent=False)
class CreateVersion:
    """Create a new agent version."""
    def body(self, ctx):
        return {
            "version": "1.0.0",
            "description": "AAA+ contract test version",
            "changes": ["initial"],
        }
    expected_status = [200, 201, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Agent DID placeholder",
        ),
    ]


@Endpoint(method="POST", path="/agents/{agent_did}/deployments", auth="developer", category="agent_cicd", idempotent=False)
class CreateDeployment:
    """Trigger a deployment of a specific version."""
    def body(self, ctx):
        return {"version_id": "placeholder", "environment": "production"}
    expected_status = [200, 201, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 422),
            reason="Agent DID + version_id placeholders",
        ),
    ]


@Endpoint(method="GET", path="/pipeline-templates", auth="developer", category="agent_cicd", idempotent=True)
class ListPipelineTemplates:
    """Browse marketplace pipeline templates."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/pipeline-templates/{template_id}/download",
    auth="developer",
    category="agent_cicd",
)
class DownloadPipelineTemplate:
    """Download a marketplace template (a free one, the developer's own, or one bought). §pass47's
    PASS47-PIPELINE-TEMPLATE-DOWNLOAD-500 is fixed (the route reads the stored config whole and gates a paid template
    on its purchase), so a 500 is a failure (§MCPTEST30 V0644, agentvault2-66, 2026-10-26: sbx-alpha's 7 templates
    downloaded 200, an unknown id 404)."""
    expected_status = [200, 404]
