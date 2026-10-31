"""§pass68 (2026-05-23) — Fire-and-forget MCP tool call audit writer.

Wires per-tool MCP audit logging into the existing `security_audit_logs`
table. Closes the gap surfaced by Luca King's email: MCP tool calls
were landing only in container stdout, not in the immutable audit ledger.

Design choices:
  - Fire-and-forget via `asyncio.create_task`. The MCP response path is
    NEVER blocked by the audit write. This matches the 8 existing
    `asyncio.create_task` sites in `main.py` and avoids threading
    BackgroundTasks through `handle_rpc` (which is called from multiple
    SSE wrappers — see server.py `mcp_streamable_http` / `mcp_streamable_post`).
  - Sanitization is mandatory and runs INSIDE the background task — never
    leaks an unsanitized arg or response.
  - Errors swallowed + counted as `mcp_audit_log_writes_total{outcome="write_error"}`.
  - Per-request DB session via `get_db_context()` (no contention with the
    request-cycle session).
  - OPA shadow decision threaded in via a contextvar set by `opa_shadow.shadow_check`.
    When OPA isn't called for a tool (most tools today, OPA is admin-only
    on shadow A and now Frame A), the field is simply absent from details.
  - Feature-flagged: `MCP_AUDIT_LOGGING_ENABLED` (default false). Code is
    deployed in OFF state to verify no regression, then flipped per-env.

What lands in each audit row:
  event_type:   mcp_tool_invoked | mcp_tool_failed
  correlation_id: uuid linking this audit row to the HTTP request_id
  actor_type:   admin | developer | agent | anonymous
  actor_id:     developer_id (string) OR agent_did OR null for anonymous
  actor_ip:     remote address
  target_type:  "mcp_tool"
  target_id:    tool name (e.g. "theprotocol_transferUnits")
  action:       "invoke"
  outcome:      success | failure | error
  severity:     info | warning | error
  details:      JSON: { tool, tier, args (sanitized), result_summary (sanitized),
                        latency_ms, opa? (when OPA shadow ran),
                        is_admin_server (bool), error? (truncated) }
  error_message: present iff outcome != success (max 500 chars)
  request_id:   X-Request-Id header or generated UUID
  user_agent:   client UA string
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

from prometheus_client import Counter, Histogram

from ..database import get_db_context
from ..security_oauth.audit_logger import SecurityEventType, security_auditor
from .audit_sanitizer import cap_details_json, sanitize_args, sanitize_result
from .binary_answers import CONTENT_KEY  # §MCPTEST30 V0640: a file's content never reaches a row

logger = logging.getLogger(__name__)

# ── Feature flag ─────────────────────────────────────────────────────────
MCP_AUDIT_LOGGING_ENABLED = (
    os.getenv("MCP_AUDIT_LOGGING_ENABLED", "false").lower() == "true"
)

# ── OPA shadow contextvar ────────────────────────────────────────────────
#
# Set by opa_shadow.shadow_check() when an OPA shadow query runs. Read by
# emit_mcp_audit when building the details JSON. The contextvar is per-request
# (because asyncio task-local), so concurrent requests don't see each other's
# OPA decisions.
mcp_opa_decision_var: contextvars.ContextVar[Optional[Dict[str, Any]]] = (
    contextvars.ContextVar("mcp_opa_decision", default=None)
)

# ── Prometheus metrics ────────────────────────────────────────────────────
MCP_AUDIT_WRITES_TOTAL = Counter(
    "mcp_audit_log_writes_total",
    "MCP audit log writes by outcome and tier",
    ["outcome", "tier", "admin_server"],
)
MCP_AUDIT_WRITE_LATENCY = Histogram(
    "mcp_audit_log_write_latency_seconds",
    "Latency of MCP audit log INSERTs",
    buckets=(0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
MCP_AUDIT_SANITIZER_DROPS = Counter(
    "mcp_audit_sanitizer_drops_total",
    "Audit rows where sanitizer had to cap or drop fields",
    ["reason"],
)

# ── Tier classification ───────────────────────────────────────────────────
# §pass70 Sprint 1 — getGovernanceProposals moved Tier 3 → Tier 1
# §pass70 Sprint 2 — +13 tools (Wave 1 Tier 2 + Wave 2 Tier 3)
# §pass70 Sprint 3 — +15 non-admin tools (Wave 3 Tier 1 + Wave 4 Tier 2/3) + 10 admin (tier resolved by is_admin_server flag)
_TIER_1_TOOLS = {
    "theprotocol_getOrgTrackRecord",
    "theprotocol_getOrgPublicFeed",
    "theprotocol_listTransparentOrganizations",
    # Gateway meta-tools (2026-07-14 L1, tools_gateway.py). invokeTool is
    # unwrapped before dispatch so its audit rows carry the INNER tool name;
    # listed here only so any unexpected direct row never reads tier=unknown.
    "theprotocol_searchTools",
    "theprotocol_describeTools",
    "theprotocol_listToolsets",
    "theprotocol_invokeTool",
    "theprotocol_discoverRegistries",
    "theprotocol_discoverAgents",
    "theprotocol_getAgentProfile",
    "theprotocol_getNetworkStats",
    "theprotocol_getLockPayoutTiers",
    "theprotocol_getGovernanceProposals",
    # GÖDEL FORGE public arena reads (2026-07-19 batch-3)
    "theprotocol_getForgeStatus",
    "theprotocol_getForgeLineage",
    # THE GUILD public reads (2026-07-08)
    "theprotocol_guildListOrders",
    "theprotocol_guildGetOrder",
    "theprotocol_guildNetworkBoard",
    # Sprint 3 Wave 3
    "theprotocol_getRegistryCard",
    "theprotocol_getFiatTiers",
    "theprotocol_getFiatProviders",
    "theprotocol_getFiatQuote",
    "theprotocol_getLockStats",
    "theprotocol_getNetworkHealth",
    # Sprint 4
    "theprotocol_getFederationInfo",
    # Sprint 5
    "theprotocol_getAttestationSigningPubkey",
    # Sprint 6
    "theprotocol_getAchievementCatalog",
    "theprotocol_getAttestationHealth",
    "theprotocol_getCircuits",
    "theprotocol_getLockPayoutRuns",
    "theprotocol_getLockPayoutStats",
    "theprotocol_reverifyAttestation",
    # Sprint 8
    "theprotocol_getSystemActivityFeed",
    # Sprint 9 (Tier 1 — 10 new)
    "theprotocol_getCircuitACIR",
    "theprotocol_getCircuitSource",
    "theprotocol_getCircuitNargoToml",
    "theprotocol_getCircuitVerificationKey",
    "theprotocol_getCircuitMetadata",
    "theprotocol_getPipelineTemplates",
    "theprotocol_getAgentByDID",
    "theprotocol_getAgentCardExport",
    "theprotocol_getAgentPublicKey",
    "theprotocol_getTegPrice",
    "theprotocol_getTegReputationRankings",
    "theprotocol_getAgentLocations",
    # Sprint 10 (Tier 1 — 2 new)
    "theprotocol_getFiatStatsPublic",
    "theprotocol_getAuthRegistrationConfig",
    # Sprint 11 (Tier 1 — 3 new)
    "theprotocol_getAgentFlare",
    "theprotocol_getDeveloperFlare",
    "theprotocol_getLockPayoutTiersTeg",
    # Sprint 12 (Tier 1 — 8 new)
    "theprotocol_getFederationHealthCheck",
    "theprotocol_getFederationNetworkStats",
    "theprotocol_listFederationRegistries",
    "theprotocol_listFederationAgentCards",
    "theprotocol_listFederationRegistryCards",
    "theprotocol_getFederationPolicyCompliance",
    "theprotocol_getFederationRegistryHealthProfile",
    "theprotocol_getSpireJWKS",
    # Sprint 17 (Tier 1 — 8 new)
    "theprotocol_listAgentCards",
    "theprotocol_getAgentCardByHRI",
    "theprotocol_getAgentCardByHumanReadableId",
    "theprotocol_getAgentCardById",
    "theprotocol_getDownloadsManifest",
    "theprotocol_getStackHealth",
    "theprotocol_getActivityFeedByType",
    # Sprint 19 (Tier 1 — 4 new)
    "theprotocol_getMcpStdioBridgeJs",
    "theprotocol_getMcpStdioBridgeAdminJs",
    "theprotocol_getPublicRegistryConfig",
    "theprotocol_verifyPublicAttestationBundle",
    # Sprint 20 (Tier 1 — 5 new)
    "theprotocol_getPublicShowcaseCall",
    "theprotocol_authRecover2FA",
    "theprotocol_listPublicOperatorApplications",
    "theprotocol_getAgentByDIDAlt",
    # Sprint 21 (Tier 1 — 7 new: arena)
    "theprotocol_listArenaMatches",
    "theprotocol_getArenaMatch",
    "theprotocol_getArenaMatchBets",
    "theprotocol_getArenaMatchMap",
    "theprotocol_getArenaLeaderboard",
    "theprotocol_getArenaAgentStats",
    # Sprint 18 (Tier 1 — 21 new)
    "theprotocol_getAgentLocationsOperator",
    "theprotocol_getAgentLocationsEmissionPolicies",
    "theprotocol_getAgentLocationsTrustedRegistries",
    "theprotocol_getAgentAttestationsByDID",
    "theprotocol_getAgentAttestationSchedulesByDID",
    "theprotocol_getAgentANP",
    "theprotocol_getAgentDIDDoc",
    "theprotocol_getPublicShowcaseAgents",
    "theprotocol_getPublicEventStoreRecent",
    "theprotocol_getPublicEventStoreStats",
    "theprotocol_getWellKnownRegistryCard",
    "theprotocol_getWellKnownDevJwks",
    "theprotocol_getFiatPurchaseSession",
    "theprotocol_authRegister",
    "theprotocol_authForgotPassword",
    "theprotocol_authResetPassword",
    "theprotocol_authSetNewPassword",
    "theprotocol_authRecoverAccount",
    "theprotocol_authResendVerification",
    "theprotocol_authVerifyEmail",
    "theprotocol_authValidate2FA",
}
_TIER_2_TOOLS = {
    "theprotocol_getMyBalance",
    "theprotocol_getTegDisputeDetail",  # §MCPTEST30 2026-10-01: GET /teg/disputes/{id} is agent-authed (a party check); as T3 every call was a 401
    "theprotocol_resolveTegDispute",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates an agent)
    "theprotocol_getAgentReputation",  # §pass73.3.19: agent-authed endpoint (was mis-tiered T3)
    "theprotocol_deleteMyAgent",  # §pass73.3.19: agent self-delete — was mis-tiered T3
    "theprotocol_transferUnits",
    # THE GUILD agent actions (2026-07-08)
    "theprotocol_guildPostOrder",
    "theprotocol_guildBid",
    "theprotocol_guildAward",
    "theprotocol_guildSubmitWork",
    "theprotocol_guildVerify",
    # GÖDEL FORGE agent-triggered eval run (2026-07-19 batch-3)
    "theprotocol_runForgeEval",
    "theprotocol_guildCancelOrder",
    "theprotocol_guildMyWork",
    "theprotocol_guildCrossRegistryBid",
    "theprotocol_smartSend",
    "theprotocol_lockUnits",
    "theprotocol_unlockUnits",
    "theprotocol_castVote",
    "theprotocol_bridgeTransfer",
    "theprotocol_submitDispute",
    "theprotocol_createProposal",
    # Sprint 2 Wave 1
    "theprotocol_getMyLocks",
    "theprotocol_getMyVotingPower",
    "theprotocol_getMyIncome",
    "theprotocol_authorizePayment",
    "theprotocol_verifyPayment",
    "theprotocol_settlePayment",
    "theprotocol_releasePayment",
    "theprotocol_submitFundingRequest",
    # Sprint 3 Wave 4 (Tier 2)
    "theprotocol_getMyAgentInfo",
    "theprotocol_agentHeartbeat",
    "theprotocol_enableMtls",
    "theprotocol_getMyPayoutRelock",
    "theprotocol_getMyPayoutHistory",
    # Sprint 4 (Tier 2)
    "theprotocol_getMyLockStatus",
    "theprotocol_getMyLockHistory",
    "theprotocol_getMyAgentHealth",
    # Sprint 5 (Tier 2 — 10 new)
    "theprotocol_getMyLockStats",
    "theprotocol_claimLockPayouts",
    "theprotocol_listMyAttestationSchedules",
    "theprotocol_createAttestationSchedule",
    "theprotocol_submitAttestation",
    "theprotocol_getMyFundingRequests",
    "theprotocol_getMyContracts",
    "theprotocol_getAgentContracts",
    "theprotocol_getMyVoteOnProposal",
    "theprotocol_getMyPaymentAuthorizations",
    # Sprint 6 (Tier 2 — 2 new)
    "theprotocol_getMyAgentDisputes",
    "theprotocol_estimateMyLockPayouts",
    # Sprint 7 (Tier 2 — 7 new; getDisputeById re-tiered to dev)
    "theprotocol_agentRevokeAttestation",
    "theprotocol_disableMyAttestationSchedule",
    "theprotocol_releasePaymentById",
    "theprotocol_approveContractCompletion",
    "theprotocol_markContractFailed",
    "theprotocol_submitDisputeEvidence",
    "theprotocol_getContractById",
    # Sprint 8 (Tier 2 — 2 new)
    "theprotocol_logEnhancedDispute",
    "theprotocol_getRegistryFederationProposals",
    # Sprint 9 (Tier 2 — 3 new)
    "theprotocol_getMyTegBalance",
    "theprotocol_getMyTegTransactions",
    "theprotocol_getMyTegDisputes",
    # Sprint 10 (Tier 2 — 2 new; exportAgent + updateMyAgentLocation re-tiered to dev)
    "theprotocol_getMyReputationBondStatus",
    "theprotocol_depositReputationBond",
    "theprotocol_unlockReputationBond",  # §BATCH0911 item 4
    # Sprint 11 (Tier 2 — 2 new)
    "theprotocol_getTegAttestations",
    "theprotocol_getTegAdvancedTransactions",
    # Sprint 13 (Tier 2 — 5 new)
    "theprotocol_tegSystemTransfer",
    "theprotocol_logTegDispute",
    "theprotocol_crossTegBalanceSync",
    "theprotocol_applyReputationSignal",
    # Sprint 17 (Tier 2 — 8 new)
    "theprotocol_getMyMtlsStatus",
    "theprotocol_disableMyMtls",
    "theprotocol_acceptContract",
    "theprotocol_engageAgent",
    "theprotocol_getContractV2",
    "theprotocol_submitContractMilestone",
    "theprotocol_releaseContractMilestone",
    "theprotocol_instantiateContractTemplate",
    "theprotocol_submitContractWork",
    "theprotocol_createMalpracticeDispute",
    "theprotocol_federationVoteProposal",
    "theprotocol_tallyProposal",
    "theprotocol_submitTegAttestation",
    # Sprint 18 (Tier 2 — 3 new)
    "theprotocol_getRegistryTreasury",
    "theprotocol_getUnitPayouts",
    "theprotocol_getUnitTransactions",
    # Sprint 19 (Tier 2 — 10 new)
    "theprotocol_getRevokedIdentities",
    "theprotocol_crossRegistryContractProxy",
    "theprotocol_acceptContractFederated",
    "theprotocol_submitContractWorkFederated",
    "theprotocol_getMyEnforcementStatus",
    "theprotocol_tegLockDirect",
    "theprotocol_tegUnlockDirect",
    "theprotocol_tegCrossRegistryTransferDirect",
    # Sprint 20 (Tier 2 — 3 new)
    "theprotocol_submitOnboardRegister",
    "theprotocol_tegReputationSignal",
    "theprotocol_federationSyncRequest",
}
_TIER_3_TOOLS = {
    "theprotocol_getSupportReviewState",
    "theprotocol_createArenaMatch",  # D6-634 (2026-10-16): was tier 1; its route admits only an administrator
    "theprotocol_claimTegPayouts",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates the agent's developer)
    "theprotocol_relayAction",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates the agent's developer)
    "theprotocol_getRelayStatus",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates the agent's developer)
    "theprotocol_getCommunityAnnouncements",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates a developer)
    "theprotocol_grantSupportReview",
    "theprotocol_revokeSupportReview",
    "theprotocol_listOrganizationInvitations",
    "theprotocol_withdrawOrganizationInvitation",
    "theprotocol_getMyAgents",
    "theprotocol_createAgent",
    # Sprint 2 Wave 2
    "theprotocol_getMyDeveloperProfile",
    "theprotocol_getMyApiKeys",
    "theprotocol_createApiKey",
    "theprotocol_getMyOrganizations",
    "theprotocol_getMyAgentBundles",
    # Sprint 3 Wave 4 (Tier 3)
    "theprotocol_submitSupportTicket",
    "theprotocol_getMySupportTickets",
    "theprotocol_revokeApiKey",
    "theprotocol_getMyDisputes",
    # Sprint 4 (Tier 3 — 12 new)
    "theprotocol_getMyWebhooks",
    "theprotocol_createWebhook",
    "theprotocol_getWebhook",
    "theprotocol_updateWebhook",
    "theprotocol_deleteWebhook",
    "theprotocol_getWebhookDeliveries",
    "theprotocol_testWebhook",
    "theprotocol_getSupportedWebhookEvents",
    "theprotocol_getDeveloperStats",
    "theprotocol_getMyCicdPipelines",
    "theprotocol_getMyCicdVersions",
    "theprotocol_getMyCicdDeployments",
    # Sprint 5 (Tier 3 — 8 new)
    "theprotocol_getMyMcpAuditLog",
    "theprotocol_getMyDeletionStatus",
    "theprotocol_getMyAchievements",
    "theprotocol_getMyUnreadNotifications",
    "theprotocol_markNotificationRead",
    "theprotocol_getOrganization",
    "theprotocol_listOrganizationMembers",
    "theprotocol_getFeaturedBundles",
    # Sprint 6 (Tier 3 — 7 new)
    "theprotocol_listMyAttestations",
    "theprotocol_getAttestationDetail",
    "theprotocol_getAttestationBundle",
    "theprotocol_getTrustScore",
    "theprotocol_getVolumeProfile",
    "theprotocol_getCrossFrameReputation",
    "theprotocol_getReputationComputationStatus",
    # Sprint 7 (Tier 3 — 11 new; +getDisputeById moved from Tier 2)
    "theprotocol_createOrganization",
    "theprotocol_updateOrganization",
    "theprotocol_deleteOrganization",
    "theprotocol_inviteOrganizationMember",
    "theprotocol_listOrganizationTeams",
    "theprotocol_createOrganizationTeam",
    "theprotocol_getOrganizationTeam",
    "theprotocol_addTeamMember",
    "theprotocol_assignAgentToOrg",
    "theprotocol_getOrganizationBySlug",
    "theprotocol_getDisputeById",
    # Sprint 9 (Tier 3 — 12 new)
    "theprotocol_getMyAgentCicdStats",
    "theprotocol_getMyAgentLogs",
    "theprotocol_listAgentTemplates",
    "theprotocol_getAgentTemplate",
    "theprotocol_getMyDeveloperActivity",
    "theprotocol_getMyDeveloperTegSummary",
    "theprotocol_getMyTreasuryBalance",
    "theprotocol_getMyNotificationPrefs",
    "theprotocol_getNotificationCatalog",
    "theprotocol_getMyNotificationMatrix",
    "theprotocol_updateNotificationPrefs",
    "theprotocol_getMySigningKeys",
    "theprotocol_getMyFlareStatus",
    "theprotocol_getMyFiatPurchases",
    "theprotocol_getMy2FAStatus",
    # Sprint 10 (Tier 3 — 15 new: 13 CI/CD mutations + 2 re-tiered)
    "theprotocol_createPipeline",
    "theprotocol_updatePipeline",
    "theprotocol_deletePipeline",
    "theprotocol_createVersion",
    "theprotocol_deleteVersion",
    "theprotocol_activateVersion",
    "theprotocol_rollbackVersion",
    "theprotocol_triggerDeployment",
    "theprotocol_getDeployment",
    "theprotocol_appendDeploymentLogs",
    "theprotocol_updateDeploymentStatus",
    "theprotocol_cloneAgent",
    "theprotocol_exportAgentDev",
    "theprotocol_updateMyDeveloperLocation",
    # Sprint 11 (Tier 3 — 7 new)
    "theprotocol_getTransactionsAnalytics",
    "theprotocol_getAgentPayoutHistory",
    "theprotocol_getAgentPendingPayouts",
    "theprotocol_getAgentLockedBalance",
    "theprotocol_getAgentLockHistory",
    "theprotocol_listTegPolicies",
    "theprotocol_getTegPoliciesComplianceDashboard",
    # Sprint 12 (Tier 3 — 16 new)
    "theprotocol_listFederationPeers",
    "theprotocol_getMyFederationRegistrations",
    "theprotocol_triggerFederationSync",
    "theprotocol_getFederationSyncStatusDev",
    "theprotocol_rotateFederationLicenseSelf",
    "theprotocol_logoutSession",
    "theprotocol_getAuthProfile",
    "theprotocol_setup2FA",
    "theprotocol_verify2FA",
    "theprotocol_disable2FASelf",
    "theprotocol_changePassword",
    "theprotocol_getBundleManifest",
    "theprotocol_rateBundle",
    "theprotocol_reportBundle",
    "theprotocol_forkBundle",
    "theprotocol_deleteBundle",
    # Sprint 13 (Tier 3 — 12 new)
    "theprotocol_getTegTransactionDetail",
    "theprotocol_getAgentTransactionHistory",
    "theprotocol_exportTegTransactions",
    "theprotocol_createTegPolicy",
    "theprotocol_updateTegPolicy",
    "theprotocol_deleteTegPolicy",
    "theprotocol_getTegPolicy",
    "theprotocol_createFrameInvitation",
    "theprotocol_finalizeFrameInvitation",
    # Sprint 14 (Tier 3 — 15 new)
    "theprotocol_validateAgentCard",
    "theprotocol_downloadBundleViaOnboard",
    "theprotocol_resetAgentCredentialsOnboard",
    "theprotocol_getFederationDisputeSettlements",
    "theprotocol_getFederationDisputeSettlement",
    "theprotocol_approveDisputeSettlement",
    "theprotocol_rejectDisputeSettlement",
    "theprotocol_getPeerSlashConfig",
    "theprotocol_updatePeerSlashConfig",
    "theprotocol_getFederationPeerByID",
    "theprotocol_updateFederationPeer",
    "theprotocol_deleteFederationPeerSelf",
    "theprotocol_createFederationPeer",
    "theprotocol_federationSlashRequest",
    "theprotocol_federationSlashConfirmation",
    # Sprint 15 (Tier 3 — 12 new)
    "theprotocol_setFlareCornerVariant",
    "theprotocol_setFlareOverlay",
    "theprotocol_setFlareVariant",
    "theprotocol_flareCelebrationAcknowledge",
    "theprotocol_customizeFlare",
    "theprotocol_equipFlare",
    "theprotocol_moveFlare",
    "theprotocol_selectFlare",
    "theprotocol_unequipFlare",
    "theprotocol_previewSlashReductionAttestation",
    "theprotocol_previewVotingPowerAttestation",
    "theprotocol_mcpPassthroughGetAgentProfile",
    # Sprint 16 (Tier 3 — 10 new)
    "theprotocol_getLockPayoutRecords",
    "theprotocol_updatePayoutRelock",
    "theprotocol_triggerLockPayoutRun",
    "theprotocol_downloadBundle",
    "theprotocol_restoreBundle",
    "theprotocol_restoreFromUpload",
    "theprotocol_patchBundle",
    "theprotocol_createBundle",
    "theprotocol_previewAdminEmailWithContext",
    "theprotocol_previewAdminEmailText",
    # Sprint 17 (Tier 3 — 12 new)
    "theprotocol_rotateMySigningKey",
    "theprotocol_getMyApiKeyDetail",
    "theprotocol_deleteMyApiKey",
    "theprotocol_getBatchAgentBalances",
    "theprotocol_getMyAgentBalance",
    "theprotocol_deleteMyAgentByDev",
    "theprotocol_getOperatorMyStatus",
    "theprotocol_getOperatorMyBundle",
    "theprotocol_getOperatorMyLifecycle",
    "theprotocol_activateOperator",
    "theprotocol_requestFrame",
    "theprotocol_selfProvisionOperator",
    # Sprint 18 (Tier 3 — 7 new)
    "theprotocol_importAgent",
    "theprotocol_validateAgentImport",
    "theprotocol_agentBulkExport",
    "theprotocol_authRefresh",
    "theprotocol_regenerateBackupCodes",
    "theprotocol_operatorPortalSelfLogs",
    "theprotocol_operatorPortalSelfRestart",
    # Sprint 19 (Tier 3 — 8 new)
    "theprotocol_getMyDeveloperJwks",
    "theprotocol_getOAuthFederationStatus",
    "theprotocol_oauthIntrospect",
    "theprotocol_oauthRevoke",
    "theprotocol_oauthFederationTrustList",
    "theprotocol_oauthTokenExchange",
    "theprotocol_acceptOrgInvitation",
    "theprotocol_getSupportTicketDetail",
    "theprotocol_replySupportTicket",
    "theprotocol_requestSelfRevocation",
    # Sprint 20 (Tier 3 — 12 new)
    "theprotocol_getMyDeveloperActivityEventstore",
    "theprotocol_listDeveloperApikeysMe",
    "theprotocol_createDeveloperApikeyMe",
    "theprotocol_listDeveloperWebhooks",
    "theprotocol_getProposalDetail",
    "theprotocol_getProposalVotes",
    "theprotocol_getAutoTallyConfig",
    "theprotocol_federationProposeRaise",
    "theprotocol_federationVetoProposal",
    "theprotocol_getDevTrustGraph",
    "theprotocol_getAgentMetrics",
    "theprotocol_agentBuilderGenerate",
    # Sprint 21 (Tier 3 — 9 new)
    "theprotocol_listAgentBuilderTemplates",
    "theprotocol_agentBuilderGenerateTemplate",
    "theprotocol_updateMyDeveloperProfile",
    "theprotocol_listDeveloperWebhooksAlt",
    "theprotocol_getDeveloperWebhookDeliveriesAlt",
    "theprotocol_testDeveloperWebhookAlt",
    "theprotocol_downloadPipelineTemplate",
    "theprotocol_purchasePipelineTemplate",
    "theprotocol_createTegPoliciesBatch",
    # Sprint 8 (Tier 3 — 13 new; getRegistryFederationProposals re-tiered to agent)
    "theprotocol_getFeeCurrentRate",
    "theprotocol_requestAccountDeletion",
    "theprotocol_cancelAccountDeletion",
    "theprotocol_claimPendingAchievements",
    "theprotocol_recordAchievement",
    "theprotocol_listOrganizationAgents",
    "theprotocol_getOrganizationCicdSummary",
    "theprotocol_removeOrganizationMember",
    "theprotocol_updateOrganizationTeam",
    "theprotocol_deleteOrganizationTeam",
    "theprotocol_removeTeamMember",
    "theprotocol_unassignAgentFromOrg",
    "theprotocol_getPayoutRelockForAgent",
}
_TIER_0_TOOLS = {"theprotocol_getAgentToken"}


def _tier_for(tool_name: str, is_admin_server: bool) -> str:
    if is_admin_server:
        return "admin"
    if tool_name in _TIER_1_TOOLS:
        return "1"
    if tool_name in _TIER_2_TOOLS:
        return "2"
    if tool_name in _TIER_3_TOOLS:
        return "3"
    if tool_name in _TIER_0_TOOLS:
        return "0"
    return "unknown"


def _actor_fields(auth_ctx: Any) -> Dict[str, Optional[str]]:
    """Extract actor type + id from MCPAuthContext (or None for anonymous)."""
    if auth_ctx is None:
        return {"actor_type": "anonymous", "actor_id": None}
    # MCPAuthContext properties (see auth_bridge.py)
    try:
        if getattr(auth_ctx, "is_developer", False):
            actor_type = "admin" if getattr(auth_ctx, "is_admin", False) else "developer"
            actor_id = str(getattr(auth_ctx, "developer_id", None)) if getattr(auth_ctx, "developer_id", None) is not None else None
            return {"actor_type": actor_type, "actor_id": actor_id}
        if getattr(auth_ctx, "is_agent", False):
            return {
                "actor_type": "agent",
                "actor_id": getattr(auth_ctx, "agent_did", None),
            }
    except Exception:  # noqa: BLE001
        pass
    return {"actor_type": "anonymous", "actor_id": None}


def _without_file_content(result: Any) -> Any:
    """§MCPTEST30 (V0640): an answer carrying a file (mcp/binary_answers, `content_base64`) reaches the audit without it:
    the key goes from the result, from its structuredContent and from the JSON of its text content, before anything is
    cut or kept, so a file's bytes (a generated package can carry an env file) never sit in an audit row."""
    if not isinstance(result, dict):
        return result
    out = {k: v for k, v in result.items() if k != CONTENT_KEY}
    sc = out.get("structuredContent")
    if isinstance(sc, dict) and CONTENT_KEY in sc:
        out["structuredContent"] = {k: v for k, v in sc.items() if k != CONTENT_KEY}
    content = out.get("content")
    if isinstance(content, list):
        items = []
        for it in content:
            text = it.get("text") if isinstance(it, dict) else None
            if isinstance(text, str) and CONTENT_KEY in text:
                try:
                    doc = json.loads(text)
                except ValueError:
                    doc = None
                if isinstance(doc, dict):
                    doc.pop(CONTENT_KEY, None)
                    it = {**it, "text": json.dumps(doc, indent=2, default=str)}
                else:
                    it = {**it, "text": "<a file's content, withheld from the audit>"}
            items.append(it)
        out["content"] = items
    return out


def _summarize_result(result: Any) -> Any:
    """Compact a tool result for the audit details field. Lists get a head
    sample + count; dicts get sanitized + length-capped via the sanitizer.
    Tool errors (isError=true) include the error text.
    """
    if result is None:
        return None
    result = _without_file_content(result)
    if isinstance(result, dict):
        sanitized = sanitize_result(result)
        # MCP tool result shape is {"content": [...], "isError": bool}
        if isinstance(sanitized, dict) and "content" in sanitized:
            content = sanitized.get("content", [])
            return {
                "isError": sanitized.get("isError", False),
                "content_count": len(content) if isinstance(content, list) else 1,
                "content_head": content[:2] if isinstance(content, list) else content,
            }
        return sanitized
    return sanitize_result(result)


async def _write_audit_row(
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    auth_ctx: Any,
    outcome: str,
    result_or_error: Any,
    latency_ms: float,
    actor_ip: Optional[str],
    user_agent: Optional[str],
    request_id: Optional[str],
    is_admin_server: bool,
) -> None:
    """The actual INSERT — runs inside an asyncio.create_task. Never raises
    into the caller. Errors are counted as `outcome="write_error"` in the
    Prometheus counter.
    """
    tier = _tier_for(tool_name, is_admin_server)
    actor = _actor_fields(auth_ctx)

    # Pull OPA shadow decision (if set by opa_shadow during this request)
    opa_decision = mcp_opa_decision_var.get()

    # Build details JSON
    details: Dict[str, Any] = {
        "tool": tool_name,
        "tier": tier,
        "is_admin_server": is_admin_server,
        "args": sanitize_args(arguments) if arguments else {},
        "latency_ms": round(latency_ms, 2),
    }
    if outcome == "success":
        details["result_summary"] = _summarize_result(result_or_error)
    else:
        # Failure / error path
        err_text = str(result_or_error) if result_or_error is not None else ""
        details["error"] = err_text[:500]

    if opa_decision is not None:
        details["opa"] = opa_decision

    # Cap the JSON to MAX_DETAILS_BYTES
    capped = cap_details_json(details)
    if capped.get("_details_truncated"):
        MCP_AUDIT_SANITIZER_DROPS.labels(reason="size_cap").inc()

    # Map outcome → event_type + severity
    if outcome == "success":
        event_type = SecurityEventType.MCP_TOOL_INVOKED
        severity = "info"
        error_message = None
    elif outcome == "failure":
        # Auth-failure / known MCPAuthError — log as info-level failure
        event_type = SecurityEventType.MCP_TOOL_INVOKED
        severity = "warning"
        error_message = (str(result_or_error)[:500]) if result_or_error else None
    else:
        # Unhandled exception
        event_type = SecurityEventType.MCP_TOOL_FAILED
        severity = "error"
        error_message = (str(result_or_error)[:500]) if result_or_error else None

    started = time.perf_counter()
    try:
        async with get_db_context() as db:
            await security_auditor.log_event(
                db=db,
                event_type=event_type,
                action="invoke",
                outcome=outcome,
                severity=severity,
                actor_type=actor["actor_type"],
                actor_id=actor["actor_id"],
                actor_ip=actor_ip,
                target_type="mcp_tool",
                target_id=tool_name,
                details=capped,
                error_message=error_message,
                request_id=request_id,
                user_agent=user_agent,
            )
            await db.commit()
        MCP_AUDIT_WRITES_TOTAL.labels(outcome=outcome, tier=tier, admin_server=str(is_admin_server).lower()).inc()
    except Exception as exc:  # noqa: BLE001
        # Never re-raise — audit failures must not affect the MCP response
        logger.debug("MCP audit write failed: %s", exc)
        MCP_AUDIT_WRITES_TOTAL.labels(outcome="write_error", tier=tier, admin_server=str(is_admin_server).lower()).inc()
    finally:
        MCP_AUDIT_WRITE_LATENCY.observe(time.perf_counter() - started)


async def emit_mcp_audit(
    *,
    tool_name: str,
    arguments: Dict[str, Any],
    auth_ctx: Any,
    outcome: str,
    result_or_error: Any,
    latency_ms: float,
    actor_ip: Optional[str],
    user_agent: Optional[str],
    request_id: Optional[str],
    is_admin_server: bool = False,
) -> None:
    """Public entry point — called from the dispatcher hook in server.py /
    server_admin.py. Fire-and-forget: schedules the write and returns
    immediately. The caller does not await this in the response path.
    """
    if not MCP_AUDIT_LOGGING_ENABLED:
        return
    # Schedule background write
    try:
        asyncio.create_task(
            _write_audit_row(
                tool_name=tool_name,
                arguments=arguments or {},
                auth_ctx=auth_ctx,
                outcome=outcome,
                result_or_error=result_or_error,
                latency_ms=latency_ms,
                actor_ip=actor_ip,
                user_agent=user_agent,
                request_id=request_id,
                is_admin_server=is_admin_server,
            )
        )
    except Exception as exc:  # noqa: BLE001
        # If we can't even schedule the task, count + drop quietly
        logger.debug("Failed to schedule MCP audit task: %s", exc)
        MCP_AUDIT_WRITES_TOTAL.labels(
            outcome="schedule_error",
            tier=_tier_for(tool_name, is_admin_server),
            admin_server=str(is_admin_server).lower(),
        ).inc()


# AGORA exchange tools (2026-06-12) — tier classification for audit rows.
_TIER_1_TOOLS.update({
    "theprotocol_getAgoraListings",
    "theprotocol_getAgoraListing",
    "theprotocol_getAgoraOrderBook",
    "theprotocol_getAgoraTrades",
    "theprotocol_getAgoraCandles",
})
_TIER_2_TOOLS.update({
    "theprotocol_placeAgoraOrder",
    "theprotocol_cancelAgoraOrder",
    "theprotocol_getMyAgoraOrders",
    "theprotocol_getMyAgoraHoldings",
    "theprotocol_buyAgoraLaunch",
})
_TIER_3_TOOLS.update({
    "theprotocol_createAgoraListing",
    "theprotocol_declareAgoraDistribution",
})

# §OURSTATE-1 (2026-08-24) — OurChat chat tools (dual-auth passthrough; tier 2
# in dispatch so the inline agent_jwt swap works).
_TIER_2_TOOLS.update({
    "theprotocol_listConversations",
    "theprotocol_readThread",
    "theprotocol_sendChatMessage",
    "theprotocol_respondChatRequest",
    "theprotocol_blockChatPrincipal",
    "theprotocol_unblockChatPrincipal",
})

# V0650 (a) (2026-10-31) — an agent's status line and its organization's presence (mcp/tools_presence.py).
_TIER_2_TOOLS.update({
    "theprotocol_setMyAgentStatus",
    "theprotocol_getOrganizationPresence",
})

# §MEMBERSHIP (2026-10-02) — membership and the commons (mcp/tools_commons.py); the six admin tools are on the admin
# server, whose rows are tier "admin".
_TIER_1_TOOLS.update({
    "theprotocol_getMembershipStats",
    "theprotocol_getCommonsSeasons",
    "theprotocol_getCommonsSeason",
})
_TIER_2_TOOLS.update({
    "theprotocol_submitCommonsWork",
    "theprotocol_castCommonsBallot",
})
_TIER_3_TOOLS.update({
    "theprotocol_getMyMembership",
    "theprotocol_getMyCommonsSeason",
})

# V0650 (l) (2026-10-31) — approvals in the chat (mcp/tools_chat_approvals.py).
_TIER_2_TOOLS.update({
    "theprotocol_requestChatApproval",
    "theprotocol_getChatApprovalStatus",
})
_TIER_3_TOOLS.update({
    "theprotocol_decideChatApproval",
})
