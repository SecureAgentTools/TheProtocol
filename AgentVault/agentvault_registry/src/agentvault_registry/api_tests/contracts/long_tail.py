"""Long-tail contracts (AAA+ Phase IV-A, 2026-05-21).

Catch-all for endpoints not covered by topic files. Each is minimal — just
ensures the endpoint exists in the OpenAPI catalog → contract dispatches it
correctly with a sensible body + expected_status.
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Agent logs ───────────────────────────────────────────────────────────
@Endpoint(method="POST", path="/agents/{agent_did}/logs", auth="developer", category="agent_logs", idempotent=False)
class WriteAgentLog:
    """Write a log entry for an agent."""
    def body(self, ctx):
        return {"level": "INFO", "message": "AAA+ test log", "source": "contract", "metadata": {}}
    expected_status = [200, 201, 404]


@Endpoint(method="GET", path="/agents/{agent_did}/logs", auth="developer", category="agent_logs", idempotent=True)
class ReadAgentLogs:
    """Read recent logs for an agent."""
    expected_status = [200, 404]


# ── Agent builder ───────────────────────────────────────────────────────
@Endpoint(method="POST", path="/agent-builder/generate", auth="developer", category="agent_builder", idempotent=False)
class AgentBuilderGenerate:
    """Generate an agent package (a zip, routers/agent_builder.generate_agent_package: no row written, no model called).
    §SUITES1018 batch 7: the route takes `agent_builder_type` and the wrapper's backend; the contract sent `type` and
    passed on the 422. The catalog's body is the route's own shape."""
    def body(self, ctx):
        from ..request_bodies import RequestBodies
        return RequestBodies().get_body("/agent-builder/generate")
    expected_status = [200, 201]


@Endpoint(method="GET", path="/agent-builder/templates", auth="developer", category="agent_builder_templates", idempotent=True)
class AgentBuilderTemplates:
    """List agent-builder templates."""
    expected_status = 200


# ── Agent export/import ──────────────────────────────────────────────────
@Endpoint(method="POST", path="/agents/export/bulk", auth="developer", category="agent_export_import", idempotent=True)
class ExportAgentsBulk:
    """Bulk-export agents."""
    def body(self, ctx):
        return {"agent_dids": [], "include_credentials": False}
    expected_status = [200, 422]


@Endpoint(method="POST", path="/agents/import", auth="developer", category="agent_export_import", idempotent=False)
class ImportAgents:
    """Import agents from export bundle."""
    def body(self, ctx):
        return {"export_data": {}, "override_existing": False}
    expected_status = [200, 201, 400, 422]


@Endpoint(method="POST", path="/agents/import/validate", auth="developer", category="agent_export_import", idempotent=True)
class ValidateImport:
    """Validate an import bundle without applying."""
    def body(self, ctx):
        return {"export_data": {}}
    expected_status = [200, 400, 422]


@Endpoint(method="POST", path="/agents/{agent_did}/clone", auth="developer", category="agent_export_import", idempotent=False)
class CloneAgent:
    """Clone an agent."""
    def body(self, ctx):
        return {"new_name": "Cloned agent", "new_description": "Auto-cloned"}
    expected_status = [200, 201, 404]


# ── TEG transactions extras ─────────────────────────────────────────────
@Endpoint(method="POST", path="/teg/transactions/{transaction_id}/reputation-signal", auth="agent", category="teg_transactions", idempotent=False)
class TxReputationSignal:
    """Attach a reputation signal to a completed transaction."""
    def body(self, ctx):
        return {"signal_type": "positive", "signal_value": 1, "reason": "AAA+ test", "metadata": {}}
    expected_status = [200, 404]


@Endpoint(method="POST", path="/teg/batch-transfer", auth="agent", category="teg_integration", idempotent=False)
class TegBatchTransfer:
    """Batch transfer (intentionally not implemented in many builds)."""
    def body(self, ctx):
        return {"transfers": [{"to": "did:cos:p1", "amount": "1"}]}
    failures = [FailureMode.not_implemented()]
    expected_status = [200, 501]


# ── Public/showcase ─────────────────────────────────────────────────────
@Endpoint(method="GET", path="/showcase/landing-stats", auth="none", category="showcase", idempotent=True)
class ShowcaseStats:
    """Public landing-page stats."""
    expected_status = 200


@Endpoint(method="GET", path="/public/network-stats", auth="none", category="federation_public", idempotent=True)
class NetworkStats:
    """Public network stats."""
    expected_status = 200


# ── Notifications + funding ─────────────────────────────────────────────
@Endpoint(method="GET", path="/notifications/unread", auth="developer", category="status", idempotent=True)
class UnreadNotifications:
    """Caller's unread notifications."""
    expected_status = 200


@Endpoint(method="POST", path="/notifications/{broadcast_id}/read", auth="developer", category="status", idempotent=True)
class MarkNotificationRead:
    """Mark a broadcast notification as read."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404]


# ── Support ─────────────────────────────────────────────────────────────
@Endpoint(method="POST", path="/support/tickets", auth="developer", category="status", idempotent=False)
class CreateSupportTicket:
    """File a support ticket."""
    def body(self, ctx):
        return {"subject": "AAA+ contract test", "body": "Auto-created", "category": "general"}
    expected_status = [200, 201, 422]


@Endpoint(method="GET", path="/support/tickets/mine", auth="developer", category="status", idempotent=True)
class MySupportTickets:
    """List caller's support tickets."""
    expected_status = 200


# ── Achievements / Community ────────────────────────────────────────────
@Endpoint(method="GET", path="/achievements", auth="developer", category="status", idempotent=True)
class ListAchievements:
    """All achievements visible to caller."""
    expected_status = 200


@Endpoint(method="GET", path="/community/agents/discover", auth="none", category="federation_public", idempotent=True)
class CommunityDiscover:
    """Discover community-promoted agents."""
    expected_status = 200
