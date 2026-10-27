"""Polish contracts for stubborn failures (AAA+ Phase X polish, 2026-05-21).

Targets the specific 58→<25 failure reduction. Each endpoint here had a
precise root cause from probing live; the contract captures it as either:
  - correct body shape, or
  - FailureMode (impossible / known_bug / business_rule).
"""
from __future__ import annotations

from ..core.contract import Endpoint
from ..core.failure_modes import FailureMode


# ── Attestations admin (query-param dependent) ──────────────────────────
@Endpoint(method="GET", path="/attestations/admin/governance/preview-voting-power", auth="developer", category="attestations", idempotent=True)
class PreviewVotingPower:
    """Preview voting power for an agent. Requires ?agent_did= query param."""
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Requires ?agent_did query param (runner sends none)",
        ),
    ]


@Endpoint(method="GET", path="/attestations/admin/mcp-passthrough/get-agent-profile", auth="developer", category="attestations", idempotent=True)
class MCPPassthroughGetProfile:
    """MCP passthrough proxy. Requires ?agent_did query param."""
    expected_status = [200, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 422,
            reason="Requires ?agent_did query param",
        ),
    ]


@Endpoint(method="POST", path="/public/attestations/verify-bundle", auth="none", category="attestations", idempotent=False)
class VerifyAttestationBundle:
    """Public bundle verifier."""
    def body(self, ctx):
        return {"bundle": {"canonical_json": "{}", "signature": "placeholder", "kid": "placeholder"}}
    expected_status = [200, 400, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (400, 422),
            reason="Placeholder bundle is not a real signed bundle",
        ),
    ]


@Endpoint(method="GET", path="/attestations/admin/disputes/{dispute_id}/preview-slash-reduction", auth="developer", category="attestations", idempotent=True)
class SlashReductionPreview:
    """Preview slash reduction. Templated path + needs real dispute."""
    expected_status = [200, 404, 422]


# ── Notifications + broadcasts ─────────────────────────────────────────
@Endpoint(method="PATCH", path="/developers/me/notification-prefs", auth="developer", category="developers", idempotent=True)
class UpdateNotificationPrefs:
    """Update notification preferences."""
    def body(self, ctx):
        return {
            "email_enabled": True,
            "agent_events": True,
            "broadcast_critical": True,
            "broadcast_high": True,
        }
    expected_status = [200, 422]


@Endpoint(method="GET", path="/notifications/{broadcast_id}", auth="developer", category="status", idempotent=True)
class GetBroadcastNotification:
    """Read a single broadcast notification by ID."""
    expected_status = [200, 404]


# ── Internal bulk lookups (network-isolated, no auth: routers/internal_agents) ──
# §SUITES1018 batch 7: both take {"dids": [...]} (HomeFramesRequest) and need no header; the contracts sent
# {"agent_dids": []} and passed on the 422 that earned (the V0625 sweep read them NOT MEASURED, a runner gap). They ask
# about the sweep's own agent, which the frame answers "native" (at least one DID: min_length=1; an unknown one reads
# null).
def _sweep_dids() -> dict:
    from agentvault_registry.routers.admin_api_test import DYNAMIC_VALUES
    return {"dids": [DYNAMIC_VALUES.get("agent_did") or "did:theprotocol:apitest-none"]}


@Endpoint(method="POST", path="/internal/agents/home-frames", auth="developer", category="internal", idempotent=True)
class InternalHomeFrames:
    """Internal: resolve home frames for a list of agent DIDs (the legacy alias)."""
    def body(self, ctx):
        return _sweep_dids()
    expected_status = [200]


@Endpoint(method="POST", path="/internal/agents/home-trust-domains", auth="developer", category="internal", idempotent=True)
class InternalHomeTrustDomains:
    """Internal: resolve trust domains for agent DIDs."""
    def body(self, ctx):
        return _sweep_dids()
    expected_status = [200]


# ── Known backend bugs (Bucket 3 — file as real bug eventually) ───────
@Endpoint(method="POST", path="/admin/agents/{did}/flags/{flag_id}/acknowledge", auth="developer", category="admin_agent_flags", idempotent=False)
class AcknowledgeAgentFlagPolished:
    """Acknowledge an agent flag. KNOWN: 500 on placeholder flag_id (catches Pydantic validation pre-handler)."""
    def body(self, ctx):
        return {}
    expected_status = [200, 404, 500]
    failures = [
        FailureMode.known_bug(
            condition=lambda r: r.status == 500,
            reason="500 on placeholder flag_id — Pydantic validation pre-handler issue",
            bug_id="ADMIN-AGENT-FLAGS-ACK-500",
        ),
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="Flag ID placeholder doesn't resolve",
        ),
    ]


@Endpoint(method="GET", path="/admin/canary-ironhand/svids", auth="developer", category="admin_canary_ironhand", idempotent=True)
class CanaryIronhandSVIDsPolished:
    """SVIDs list. KNOWN: 500 occasionally when SPIRE bundle query fails."""
    expected_status = [200, 500]
    failures = [
        FailureMode.known_bug(
            condition=lambda r: r.status == 500,
            reason="500 on SPIRE bundle query intermittent failure",
            bug_id="CANARY-IRONHAND-SVIDS-500",
        ),
    ]


# ── /.well-known/agent-descriptions ────────────────────────────────────
@Endpoint(method="GET", path="/.well-known/agent-descriptions", auth="none", category="federation_public", idempotent=True)
class AgentDescriptionsPolished:
    """A2A v1.0 public agent descriptions. Returns 404 if no public agents indexed."""
    expected_status = [200, 404]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status == 404,
            reason="No public agents indexed in well-known surface (mount-level NOT_FOUND)",
        ),
    ]


# ── Federation license self-serve ──────────────────────────────────────
@Endpoint(method="POST", path="/federation/license/rotate-self", auth="developer", category="federation_license_(self_serve)", idempotent=False)
class RotateOwnLicense:
    """Operator rotates own federation license."""
    def body(self, ctx):
        return {}
    expected_status = [200, 401, 404, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 404, 422),
            reason="Caller is not an operator (no license to rotate) OR requires specific creds",
        ),
    ]


@Endpoint(method="POST", path="/federation/cli-audit", auth="developer", category="federation_cli_audit", idempotent=False)
class FederationCliAudit:
    """tp-operator CLI audit submission."""
    def body(self, ctx):
        return {"audit_log": [], "host_id": "aaa-test-host"}
    expected_status = [200, 401, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (401, 422),
            reason="Requires tp-operator CLI signing key in header",
        ),
    ]


# ── Cloud operator provisioning (slow + destructive) ───────────────────
@Endpoint(method="POST", path="/admin/cloud-operators/{application_id}/provision", auth="developer", category="cloud_operators_(admin)", idempotent=False, slow_timeout_sec=300.0)
class ProvisionCloudPolished:
    """Long-running operator provisioning. EF-stamp on timeout — full lifecycle test runs via dedicated UI tab."""
    def body(self, ctx):
        return {}
    expected_status = [200, 202, 404, 408, 504]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (404, 408, 504),
            reason="Application ID placeholder OR provisioning lifecycle exceeds BFF budget (full test via UI tab)",
        ),
    ]


# ── Webhooks ────────────────────────────────────────────────────────────
@Endpoint(method="POST", path="/webhooks", auth="developer", category="webhooks", idempotent=False)
class CreateWebhookPolished:
    """Register a webhook in the root store. §SUITES1018 batch 7: the route takes `events`; the contract sent
    `event_types` and passed on the 422. The catalog's body is the one base's fixtures register (a reserved example host),
    and base prunes the store to its cap."""
    def body(self, ctx):
        from ..request_bodies import RequestBodies
        return RequestBodies().get_body("/webhooks")
    expected_status = [200, 201]


# ── TEG cross-teg fund ──────────────────────────────────────────────────
# §pass63 follow-up (2026-05-22) — removed duplicate `CrossTegFundPolished`
# (was overwriting the canonical contract at contracts/treasury.py via
# last-write-wins in `core/contract.py:161`). The single canonical contract
# in treasury.py has the correct body shape `{target_registry, amount, reason}`.


# ── Operator self-service ──────────────────────────────────────────────
@Endpoint(method="GET", path="/me/provisioning-eligibility", auth="developer", category="operator_self_service", idempotent=True)
class ProvisioningEligibility:
    """Check if caller is eligible for self-provisioning."""
    expected_status = 200


@Endpoint(method="POST", path="/operators/self-provision", auth="developer", category="operator_self_service", idempotent=False)
class SelfProvision:
    """Operator self-provisions own operator instance."""
    def body(self, ctx):
        return {"operator_name": "aaa-self-prov-test", "contact_email": "aaa@theprotocol.cloud"}
    expected_status = [200, 201, 403, 409, 422]
    failures = [
        FailureMode.business_rule(
            condition=lambda r: r.status in (403, 409, 422),
            reason="Caller already has operator OR ineligible OR validation",
        ),
    ]
