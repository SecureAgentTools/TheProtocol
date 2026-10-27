"""Utility + system contracts (AAA+ Phase II-B, 2026-05-21).

System info, MCP health, sandbox proxy, registry-health.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="GET", path="/mcp/health", auth="none", category="mcp_server", idempotent=True)
class MCPHealth:
    """MCP server health."""
    expected_status = 200


@Endpoint(method="GET", path="/mcp/tools", auth="none", category="mcp_server", idempotent=True)
class MCPTools:
    """List registered MCP tools."""
    expected_status = 200


@Endpoint(method="GET", path="/docker-registry/token", auth="developer", category="docker_registry_auth", idempotent=True)
class DockerRegistryToken:
    """Get registry docker pull/push credentials."""
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Endpoint requires query params (scope, account)",
        ),
    ]


@Endpoint(method="GET", path="/utils/validate-card", auth="developer", category="utilities", idempotent=True)
class ValidateCard:
    """Validate an A2A agent card against the schema."""
    expected_status = [200, 405, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 405,
            reason="Endpoint requires POST",
        ),
    ]


@Endpoint(method="POST", path="/utils/validate-card", auth="developer", category="utilities", idempotent=True)
class ValidateCardPost:
    """Validate an A2A agent card (POST variant)."""
    def body(self, ctx):
        return {
            "card_data": {
                "name": "Test Card",
                "description": "AAA+ contract validation",
                "humanReadableId": "aaa-contract-test",
                "url": "https://example.com",
            }
        }
    expected_status = 200
