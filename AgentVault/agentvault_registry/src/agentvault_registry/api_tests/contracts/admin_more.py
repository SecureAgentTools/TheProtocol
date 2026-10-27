"""More admin endpoints (AAA+ Phase IV-A, 2026-05-21).

Covers admin endpoints from §pass47-58 that weren't in other topic files.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Admin tutorial ──────────────────────────────────────────────────────
@Endpoint(method="POST", path="/admin/tutorial/execute", auth="developer", category="tutorial", idempotent=False)
class AdminTutorialExecute:
    """Execute a tutorial step."""
    def body(self, ctx):
        return {"step": "register", "data": {}}
    expected_status = [200, 422]


@Endpoint(method="POST", path="/admin/tutorial/generate-proof", auth="developer", category="tutorial", idempotent=True)
class AdminTutorialProof:
    """Generate sample ZKP proof."""
    def body(self, ctx):
        return {"circuit_id": "test-circuit"}
    expected_status = [200, 404, 422]


@Endpoint(method="GET", path="/admin/tutorial/health", auth="developer", category="tutorial", idempotent=True)
class TutorialHealth:
    """Tutorial sandbox health."""
    expected_status = 200


# ── Admin health-check ──────────────────────────────────────────────────
@Endpoint(method="POST", path="/admin/health-check", auth="developer", category="admin", idempotent=True, slow_timeout_sec=300.0)
class AdminHealthCheck:
    """Multi-endpoint health probe (slow)."""
    def body(self, ctx):
        return {}
    expected_status = [200, 422]


# ── Admin federation extras ─────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/federation/compliance/peers", auth="developer", category="consul_federation_compliance", idempotent=True)
class CompliancePeers:
    """CONSUL — all peers compliance state."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/federation/compliance/peers/{peer_id}", auth="developer", category="consul_federation_compliance", idempotent=True)
class CompliancePeer:
    """CONSUL — single peer compliance state."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/federation/compliance/peers/by-operator/{operator_id}", auth="developer", category="consul_federation_compliance", idempotent=True, slow_timeout_sec=60.0)
class ComplianceByOperator:
    """CONSUL — peers compliance grouped by operator."""
    expected_status = [200, 404]


# ── Admin developers extras ─────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/developers", auth="developer", category="admin_developer_management", idempotent=True)
class AdminListDevelopers:
    """List all developers (paginated)."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/developers/{developer_id}/activity", auth="developer", category="admin_developer_management", idempotent=True, slow_timeout_sec=60.0)
class DeveloperActivity:
    """Per-developer activity feed."""
    expected_status = [200, 404]


@Endpoint(method="POST", path="/admin/developers/{developer_id}/revoke-api-keys", auth="developer", category="admin_developer_management", idempotent=True, slow_timeout_sec=60.0)
class RevokeDeveloperApiKeys:
    """Bulk-revoke a developer's API keys."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


# ── Admin agents extras ─────────────────────────────────────────────────
@Endpoint(method="POST", path="/admin/agents/bulk/suspend", auth="developer", category="admin_agent_management", idempotent=False)
class BulkSuspendAgents:
    """Coordinated bulk suspension."""
    def body(self, ctx):
        return {"agent_dids": []}
    expected_status = [200, 207, 422]


@Endpoint(method="POST", path="/admin/agents/bulk/reinstate", auth="developer", category="admin_agent_management", idempotent=False)
class BulkReinstateAgents:
    """Coordinated bulk reinstatement."""
    def body(self, ctx):
        return {"agent_dids": []}
    expected_status = [200, 207, 422]


@Endpoint(method="GET", path="/admin/agents", auth="developer", category="admin_agent_management", idempotent=True, slow_timeout_sec=60.0)
class AdminListAgents:
    """List all agents (paginated, slow)."""
    expected_status = 200


# ── Cross-TEG admin ─────────────────────────────────────────────────────
@Endpoint(method="POST", path="/api/v1/cross-teg/admin/agents/{agent_did}/block", auth="developer", category="enforcement_admin", idempotent=True)
class CrossTegBlock:
    """Block agent on cross-TEG blocklist."""
    def body(self, ctx):
        return {"reason": "AAA+ contract test"}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/api/v1/cross-teg/admin/agents/{agent_did}/unblock", auth="developer", category="enforcement_admin", idempotent=True)
class CrossTegUnblock:
    """Unblock agent on cross-TEG blocklist."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
