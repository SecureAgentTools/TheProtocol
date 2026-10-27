"""Agent management contracts (AAA+ Phase II-B, 2026-05-21).

Agent CRUD + heartbeat + enable-mtls + logs.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


@Endpoint(method="POST", path="/agents/heartbeat", auth="agent", category="agents", idempotent=True)
class AgentHeartbeat:
    """Agent reports liveness + metrics."""
    def body(self, ctx):
        return {"status": "active", "metrics": {"cpu": 50, "memory": 1024}}
    expected_status = 200


@Endpoint(method="POST", path="/agent/enable-mtls", auth="agent", category="agent_mtls_(ironhand)", idempotent=False)
class EnableMtls:
    """Agent enrolls in IRONHAND mTLS — emits AgentMtlsEnrolled."""
    def body(self, ctx):
        return {}
    expected_status = 200


@Endpoint(method="GET", path="/admin/ironhand/identities", auth="developer", category="ironhand_monitoring_(admin)", idempotent=True, slow_timeout_sec=60.0)
class IronhandIdentities:
    """List all IRONHAND-enrolled agents (slow aggregation)."""
    expected_status = 200


@Endpoint(
    method="POST",
    path="/admin/agents/{did}/flags/{flag_id}/acknowledge",
    auth="developer",
    category="admin_agent_flags",
    idempotent=False,
)
class AcknowledgeAgentFlag:
    """Mark an agent flag as acknowledged."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="DID/flag_id placeholders",
        ),
    ]


@Endpoint(method="POST", path="/admin/agents/bulk/refresh-cards", auth="developer", category="admin_agent_management", idempotent=True)
class BulkRefreshCards:
    """Bulk-refresh agent card pull-sync for all native agents."""
    def body(self, ctx):
        return {"agent_dids": []}  # empty means all
    expected_status = 200
