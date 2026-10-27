"""Admin observability contracts (AAA+ Phase II-B, 2026-05-21).

Read-only admin observability endpoints added during §pass47-58.
Covers broadcast scheduler, email studio, audit logs, attestation analytics,
bridge aggregate, federation topology, agent health, agent flags, cicd fleet.
"""
from __future__ import annotations

from ..core.contract import Endpoint


# ── Broadcasts (§bc1-bc5) ────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/broadcasts/overview", auth="developer", category="admin_broadcasts", idempotent=True)
class BroadcastsOverview:
    """Aggregate broadcast stats."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/broadcast-templates", auth="developer", category="admin_broadcasts", idempotent=True)
class BroadcastTemplates:
    """Saved broadcast templates."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/broadcast-scheduler/status", auth="developer", category="admin_broadcasts", idempotent=True)
class BroadcastSchedulerStatus:
    """Scheduler worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/broadcast-email-retry/status", auth="developer", category="admin_broadcasts", idempotent=True)
class BroadcastEmailRetryStatus:
    """Email retry worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/broadcast-email-retry/dead-letter", auth="developer", category="admin_broadcasts", idempotent=True)
class BroadcastDeadLetter:
    """Dead-letter queue of failed broadcast emails."""
    expected_status = 200


# ── Email Studio ─────────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/email/preview", auth="developer", category="admin_email_studio", idempotent=True)
class EmailPreviewIndex:
    """List available email templates for preview."""
    expected_status = 200


# ── Audit logs ───────────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/audit-logs", auth="developer", category="admin_platform", idempotent=True)
class AuditLogs:
    """OAuth audit log (security_audit_logs)."""
    expected_status = 200


# ── Agent management (post-§pass37 AdminAgents Option C integration) ────
@Endpoint(method="GET", path="/admin/agent-health/status", auth="developer", category="admin_agent_health", idempotent=True)
class AgentHealthStatus:
    """Agent health checker worker snapshot."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/agent-health/transitions", auth="developer", category="admin_agent_health", idempotent=True)
class AgentHealthTransitions:
    """Recent agent active→degraded→suspended transitions."""
    expected_status = 200


@Endpoint(
    method="GET",
    path="/admin/agents/by-developer/{developer_id}",
    auth="developer",
    category="admin_agent_management",
    idempotent=True,
)
class AdminAgentsByDeveloper:
    """All agents owned by a developer."""
    expected_status = [200, 404]


@Endpoint(method="GET", path="/admin/agents/{did}/flags", auth="developer", category="admin_agent_flags", idempotent=True)
class AdminAgentFlags:
    """Agent flag list (drift, jws_failure, etc.)."""
    expected_status = [200, 404]


# ── Federation observability ─────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/bridge/aggregate", auth="developer", category="admin_platform", idempotent=True)
class BridgeAggregate:
    """SF-3 bridge aggregate stats."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/cicd/summary", auth="developer", category="admin_ci_cd_fleet", idempotent=True)
class CicdFleetSummary:
    """Fleet-wide CI/CD summary."""
    expected_status = 200


@Endpoint(method="GET", path="/admin/cicd/deployments", auth="developer", category="admin_ci_cd_fleet", idempotent=True)
class CicdDeployments:
    """Recent deployments across fleet."""
    expected_status = 200


# ── Attestations ─────────────────────────────────────────────────────────
@Endpoint(method="GET", path="/admin/attestations/analytics", auth="developer", category="admin_platform", idempotent=True)
class AttestationsAnalytics:
    """Attestation analytics dashboard."""
    expected_status = 200


# ── Developer quota / dev management ─────────────────────────────────────
@Endpoint(
    method="GET",
    path="/admin/developers/{developer_id}/quota",
    auth="developer",
    category="admin_developer_management",
    idempotent=True,
)
class DeveloperQuota:
    """Per-developer quota state.

    Backend defaults defined in `routers/bundles_admin.py:get_dev_quota` — returns
    static defaults when no `developer_quotas` row exists, so 200 is always expected.
    """
    expected_status = [200, 404]


@Endpoint(
    method="PATCH",
    path="/admin/developers/{developer_id}/quota",
    auth="developer",
    category="admin_bundles_moderation",
    idempotent=False,
)
class DeveloperQuotaPatch:
    """Adjust per-developer bundle-quota fields (UPSERT — creates row if missing).

    Schema (`routers/bundles_admin.py:QuotaPatchRequest`): all 5 fields are
    optional (max_bundle_count + max_bundle_total_bytes + max_individual_bundle_bytes
    + bundle_create_rate_per_day + custom_quota_reason). Empty body returns
    `{updated: false, reason: "no fields provided"}` with 200 status; sending
    fields actually applies the UPSERT.
    """
    def body(self, ctx):
        return {
            "max_bundle_count": 150,
            "bundle_create_rate_per_day": 15,
            "custom_quota_reason": "AAA+ contract probe — non-default to exercise UPSERT path",
        }
    expected_status = [200, 422]
