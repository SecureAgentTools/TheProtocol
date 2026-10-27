"""
TheProtocol MCP Admin Server — Commander-only sovereign gateway.

Mounted at /mcp/admin — separate from the public /mcp server.

Endpoints:
    POST /mcp/admin/rpc     — JSON-RPC 2.0, 8 admin tools
    GET  /mcp/admin/health  — Health + tool listing
    GET  /mcp/admin/tools   — Convenience tool listing

Auth:
    ALL requests require an admin developer JWT.
    Non-admin tokens receive -32001 Unauthorized.

Tools (8):
    theprotocol.adminGetDeveloperToken — Get developer JWT (no auth needed)
    theprotocol.adminRequest           — Proxy any registry endpoint
    theprotocol.adminQueryEventStore   — Query EventStore immutable ledger
    theprotocol.adminPromQuery         — Execute PromQL against Prometheus
    theprotocol.adminGrafanaQuery      — Query Grafana HTTP API
    theprotocol.supportListTickets     — List support tickets by status
    theprotocol.supportReplyTicket     — Reply to a support ticket
    theprotocol.supportCloseTicket     — Close/resolve a support ticket

Mounted in main.py at: app.include_router(admin_mcp_router, prefix="/mcp/admin")
"""
import json
import asyncio
import os
import time
import logging
from typing import Any, Dict, List, Optional, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .arguments import argument_problems  # §MCPTEST30 V0524: arguments checked against the inputSchema
from .arguments import ToolArgumentsRefused, refuse_unbindable  # §MCPTEST30 V0545: arguments bound before the call
from .audit import emit_mcp_audit
from .tool_aliases import resolve_alias  # §AGORAWORDS (V0419)

from .auth_bridge import authenticate_mcp_token, MCPAuthError, MCPAuthUnavailable, safe_exception_text  # §MCPTEST30 V0529
from .tools_admin import (
    admin_review_grants,
    admin_review_messages,
    get_developer_token,
    admin_request,
    admin_query_event_store,
    admin_prom_query,
    admin_grafana_query,
    support_list_tickets,
    support_reply_ticket,
    support_close_ticket,
    # §pass70 Sprint 3
    get_reactor_status,
    get_event_emission_policies,
    set_event_emission_policy,
    get_cloud_operators,
    get_admin_agents,
    get_admin_dashboard,
    get_treasury_aggregate,
    trigger_projection_snapshot,
    trigger_supply_audit,
    get_admin_broadcasts,
    # §pass70 Sprint 4
    get_admin_developers,
    get_canary_status,
    get_canary_results,
    fire_canary_path,
    toggle_canary_path,
    set_canary_maintenance,
    admin_canary_fleet_status,
    admin_canary_fleet_pause,
    admin_canary_fleet_resume,
    admin_canary_fleet_upsert_remote_paths,
    admin_exchange_overview,
    admin_exchange_invariant,
    admin_exchange_participants,
    admin_exchange_approve_listing,
    admin_exchange_halt_listing,
    admin_exchange_delist_listing,
    admin_exchange_global_halt,
    preview_admin_email,
    get_pending_peer_registries,
    approve_peer_registry,
    reject_peer_registry,
    deactivate_peer_registry,
    reactivate_peer_registry,
    get_federation_sync_status,
    get_federation_sync_peers,
    # §pass70 Sprint 5
    get_enforcement_policy,
    get_enforcement_pending,
    get_enforcement_agent_status,
    get_collusion_rings,
    get_cross_teg_sweeper_status,
    get_canary_judge_status,
    get_canary_rebalancer_status,
    get_saga_timeout_status,
    get_agent_card_drift_list,
    get_invite_codes,
    get_admin_funding_pending,
    get_eventstore_balances,
    # §pass70 Sprint 6
    get_canary_ironhand_status,
    get_canary_ironhand_events,
    get_agent_health_status,
    get_cicd_summary,
    get_cicd_deployments,
    get_webhook_aggregate,
    get_recent_webhook_deliveries,
    get_reward_funding_policy,
    get_eventstore_stats,
    get_eventstore_recent,
    get_admin_audit_logs,
    get_fee_collector_info,
    get_diagnostic_checks,
    # §pass70 Sprint 7
    get_diagnostic_targets,
    get_diagnostic_actions,
    get_broadcast_templates,
    get_agent_card_pullsync_status,
    get_agent_card_pullsync_events,
    get_admin_mcp_audit_log_by_actor,
    get_admin_health_check_simple,
    get_admin_health_check_public_only,
    get_admin_health_check_authenticated,
    get_admin_test_tokens,
    # §pass70 Sprint 8
    get_admin_funding_all,
    get_agent_health_transitions,
    get_combined_health,
    get_cloud_operator_health,
    approve_funding,
    reject_funding,
    trigger_eigentrust_computation,
    svid_refresh,
    run_all_diagnostics,
    trigger_diagnostic_action,
    # §pass70 Sprint 9
    get_docker_stats,
    get_prometheus_metrics,
    get_operator_lifecycle,
    get_admin_flags,
    get_admin_registry_card,
    get_system_resources,
    get_canary_judge_events,
    get_canary_rebalancer_events,
    get_saga_timeout_events,
    get_cross_teg_sweeper_events,
    get_email_templates,
    get_admin_agent_detail,
    get_admin_developer_detail,
    list_ironhand_identities,
    get_admin_fiat_stats,
    # §pass70 Sprint 10 (Admin — 20 new)
    suspend_agent,
    reinstate_agent_enforcement,
    pause_agent_rewards,
    resume_agent_rewards,
    slash_agent_stake,
    preview_slash_stake,
    record_agent_offense,
    approve_pending_enforcement,
    reject_pending_enforcement,
    list_quarantined_registries,
    compose_broadcast,
    get_admin_broadcasts_overview,
    get_broadcast_stats,
    retract_broadcast,
    update_broadcast,
    reinstate_broadcast,
    get_admin_agents_by_developer,
    get_admin_agent_orphans,
    get_admin_agent_flags,
    get_admin_agent_signing_keys,
    # §pass70 Sprint 11 (Admin — 28 new)
    get_admin_fiat_pricing,
    get_admin_fiat_purchases,
    get_admin_fiat_purchase_detail,
    get_admin_fiat_flares,
    simulate_fiat_pricing,
    validate_fiat_pricing,
    refund_fiat_purchase,
    replay_fiat_purchase,
    grant_fiat_flare,
    revoke_fiat_flare,
    get_admin_simulation_status,
    get_admin_simulation_agents,
    get_admin_simulation_supply_audit,
    get_admin_simulation_topology,
    get_admin_simulation_deadman_status,
    get_admin_simulation_fund_status,
    get_admin_simulation_logs,
    start_simulation,
    stop_simulation,
    mint_frame_b_simulation,
    fund_simulation_agents,
    simulation_funding_preview,
    suspend_developer,
    reinstate_developer,
    get_admin_developer_activity,
    get_admin_developer_quota,
    force_email_verify,
    revoke_developer_api_keys,
    disable_developer_2fa,
    # §pass70 Sprint 12 (Admin — 15 new)
    get_operators_lifecycle_overview,
    get_bridge_aggregate,
    rotate_registry_signing_key,
    get_cloud_operator_logs,
    restart_cloud_operator_service,
    provision_cloud_operator,
    teardown_cloud_operator,
    get_cloud_operator_self_logs,
    cloud_operator_self_restart,
    update_dispute_ruling,
    get_event_store_cross_frame_peers,
    get_event_store_federation_operators,
    composite_health_check,
    # §pass70 Sprint 13 (Admin — 25 new)
    teg_treasury_mint,
    teg_treasury_receive,
    teg_cross_teg_fund,
    get_enforcement_policy_defaults,
    update_enforcement_policy,
    quarantine_registry,
    lift_quarantine,
    accept_compliance_baseline,
    blacklist_registry,
    bulk_suspend_agents,
    bulk_reinstate_agents,
    bulk_refresh_agent_cards,
    transfer_agent_ownership,
    rotate_agent_credentials,
    rotate_agent_signing_key,
    force_mtls_enroll,
    delete_admin_agent,
    acknowledge_agent_flag,
    update_developer_admin_flags,
    soft_delete_developer,
    force_developer_password_reset,
    gift_provisioning,
    patch_developer_quota,
    block_federation_agent,
    unblock_federation_agent,
    federation_cli_audit,
    # §pass70 Sprint 14 (Admin — 20 new)
    list_admin_operator_applications,
    get_admin_operator_application,
    approve_operator_application,
    reject_operator_application,
    suspend_operator,
    reinstate_operator,
    revoke_operator_access,
    rotate_operator_pull_token,
    backfill_pull_tokens,
    admin_download_operator_bundle,
    get_api_test_archive_runs,
    get_api_test_endpoints,
    get_api_test_flow_values,
    reset_api_test_flow_values,
    test_api_endpoint,
    eager_bootstrap_api_test,
    get_api_test_sandbox_credentials,
    get_api_test_bucket_classification,
    get_peer_registry_card,
    get_health_check_with_agent_auth,
    # §pass70 Sprint 15 (Admin — 30 new)
    get_admission_status,
    complete_admission,
    get_federation_compliance_drifts,
    get_federation_compliance_enforcement_mode,
    set_federation_compliance_enforcement_mode,
    get_federation_compliance_events,
    get_federation_compliance_overview,
    get_federation_compliance_peer_by_operator,
    get_federation_compliance_peer_by_id,
    poll_peer_compliance_now,
    preview_quarantine,
    federation_drift_scan,
    list_admin_frame_invitations,
    get_admin_frame_invitation,
    approve_frame_invitation,
    reject_frame_invitation,
    finalize_retry_frame_invitation,
    get_frames_spire_status,
    resync_frame_eventstore,
    revoke_frame,
    list_federation_licenses,
    generate_federation_license,
    get_federation_topology_overview,
    probe_topology_peer,
    validate_federation_policy,
    run_attestation_expiry_sweep,
    run_attestation_schedule_cron,
    admin_revoke_attestation,
    ironhand_enroll_agent,
    ironhand_revoke_agent,
    delete_spire_orphan,
    # §pass70 Sprint 16 (Admin — 20 new)
    get_federation_local_events,
    get_all_federation_peers_admin,
    get_admin_federation_policy_compliance,
    federation_policy_update_request,
    federation_request_admission,
    get_admin_federation_self_health,
    get_topology_peer_events,
    get_federation_license_detail,
    delete_federation_license,
    reinstate_federation_license,
    revoke_federation_license,
    suspend_federation_license,
    ironhand_delete_agent_proxy,
    ironhand_register_agent_proxy,
    # §pass70 Sprint 17 (Admin — 12 new)
    get_agent_card_drift_detail,
    force_register_agent_card,
    refresh_agent_card_drift,
    get_broadcast_template_detail,
    get_broadcast_email_retry_status,
    get_broadcast_email_retry_dead_letter,
    get_broadcast_scheduler_status,
    reset_api_test_sandbox,
    run_all_api_tests,
    test_api_category,
    test_api_flow,
    get_attestations_analytics,
    # §pass70 Sprint 18 (Admin — 4 new: bridge)
    bridge_mint_wrapped,
    bridge_redeem,
    bridge_unlock,
    get_bridge_status,
    # §pass70 Sprint 19 (Admin)
    list_admin_bundles_reports,
    dismiss_bundle_report,
    hide_bundle,
    unhide_bundle,
    get_canary_ironhand_svids,
    get_collusion_status,
    get_admin_metrics_agent_activity,
    get_admin_collusion_by_agent,
    # §pass70 Sprint 20 (Admin — 20 new)
    get_supply_auditor_status,
    get_supply_auditor_events,
    get_admin_workers_status,
    search_admin_events,
    get_events_aggregate,
    upload_registry_card_icon,
    distribute_from_fee_collector,
    generate_invite_codes,
    validate_invite_code_admin,
    revoke_invite_code,
    disable_webhook_admin,
    enable_webhook_admin,
    test_webhook_admin,
    get_tutorial_health,
    execute_tutorial,
    generate_tutorial_proof,
    run_diagnostics_subset,
    get_diagnostic_config,
    # §pass70 Sprint 21 (Admin — 5 new: final gap fillers)
    test_api_federation,
    delete_oauth_federation_trust,
    reconcile_fiat_provisioning,
    resend_fiat_magic_link,
    update_support_ticket_status,
    ADMIN_TOOL_SCHEMAS,
)
from ..database import get_db_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["MCP Admin Server"])

# ---------------------------------------------------------------------------
# Server Info
# ---------------------------------------------------------------------------

ADMIN_SERVER_INFO = {
    "name": "TheProtocol-Admin",
    "version": "1.0.0",
    "description": (
        "Commander-only sovereign gateway. "
        "Full access to registry API, EventStore ledger, and Prometheus metrics."
    ),
    "protocolVersion": "2025-11-25",
    # 2026-07-14 reference-grade pass: listChanged for L2 dynamic toolsets,
    # resources (registry identity/state), experimental async tasks on the
    # long-running admin tools. Prompts stay public-server-only.
    "capabilities": {
        "tools": {"listChanged": True},
        "resources": {"subscribe": False, "listChanged": False},
        "tasks": None,  # set post-import (mcp_tasks.TASKS_CAPABILITY) below
    },
    "icons": [
        {"src": "https://registry.theprotocol.cloud/pwa-512.png",
         "mimeType": "image/png", "sizes": ["512x512"]},
    ],
}

# ---------------------------------------------------------------------------
# Tool dispatch
# ---------------------------------------------------------------------------

ADMIN_TOOL_DISPATCH: Dict[str, Any] = {
    "theprotocol_adminReviewGrants": admin_review_grants,
    "theprotocol_adminReviewMessages": admin_review_messages,
    "theprotocol_adminGetDeveloperToken": get_developer_token,
    "theprotocol_adminRequest":           admin_request,
    "theprotocol_adminQueryEventStore":   admin_query_event_store,
    "theprotocol_adminPromQuery":         admin_prom_query,
    "theprotocol_adminGrafanaQuery":      admin_grafana_query,
    "theprotocol_supportListTickets":     support_list_tickets,
    "theprotocol_supportReplyTicket":     support_reply_ticket,
    "theprotocol_supportCloseTicket":     support_close_ticket,
    # ─── §pass70 Sprint 3 — first-class admin tools (replace hot adminRequest paths) ─
    "theprotocol_getReactorStatus":          get_reactor_status,
    "theprotocol_getEventEmissionPolicies":  get_event_emission_policies,
    "theprotocol_setEventEmissionPolicy":    set_event_emission_policy,
    "theprotocol_getCloudOperators":         get_cloud_operators,
    "theprotocol_getAdminAgents":            get_admin_agents,
    "theprotocol_getAdminDashboard":         get_admin_dashboard,
    "theprotocol_getTreasuryAggregate":      get_treasury_aggregate,
    "theprotocol_triggerProjectionSnapshot": trigger_projection_snapshot,
    "theprotocol_triggerSupplyAudit":        trigger_supply_audit,
    "theprotocol_getAdminBroadcasts":        get_admin_broadcasts,
    # ─── §pass70 Sprint 4 — 14 new admin tools ────────────────────────────
    "theprotocol_getAdminDevelopers":        get_admin_developers,
    "theprotocol_getCanaryStatus":           get_canary_status,
    "theprotocol_getCanaryResults":          get_canary_results,
    "theprotocol_fireCanaryPath":            fire_canary_path,
    "theprotocol_toggleCanaryPath":          toggle_canary_path,
    "theprotocol_setCanaryMaintenance":      set_canary_maintenance,
    "theprotocol_adminCanaryFleetStatus":    admin_canary_fleet_status,
    "theprotocol_adminCanaryFleetPause":     admin_canary_fleet_pause,
    "theprotocol_adminCanaryFleetResume":    admin_canary_fleet_resume,
    "theprotocol_adminCanaryFleetUpsertRemotePaths": admin_canary_fleet_upsert_remote_paths,
    "theprotocol_adminAgoraOverview":     admin_exchange_overview,
    "theprotocol_adminAgoraInvariant":    admin_exchange_invariant,
    "theprotocol_adminAgoraParticipants": admin_exchange_participants,
    "theprotocol_adminAgoraApproveListing": admin_exchange_approve_listing,
    "theprotocol_adminAgoraHaltListing":  admin_exchange_halt_listing,
    "theprotocol_adminAgoraDelistListing": admin_exchange_delist_listing,
    "theprotocol_adminAgoraGlobalHalt":   admin_exchange_global_halt,
    "theprotocol_previewAdminEmail":         preview_admin_email,
    "theprotocol_getPendingPeerRegistries":  get_pending_peer_registries,
    "theprotocol_approvePeerRegistry":       approve_peer_registry,
    "theprotocol_rejectPeerRegistry":        reject_peer_registry,
    "theprotocol_deactivatePeerRegistry":    deactivate_peer_registry,
    "theprotocol_reactivatePeerRegistry":    reactivate_peer_registry,
    "theprotocol_getFederationSyncStatus":   get_federation_sync_status,
    "theprotocol_getFederationSyncPeers":    get_federation_sync_peers,
    # ─── §pass70 Sprint 5 — 12 new admin tools ────────────────────────────
    "theprotocol_getEnforcementPolicy":       get_enforcement_policy,
    "theprotocol_getEnforcementPending":      get_enforcement_pending,
    "theprotocol_getEnforcementAgentStatus":  get_enforcement_agent_status,
    "theprotocol_getCollusionRings":          get_collusion_rings,
    "theprotocol_getCrossTegSweeperStatus":   get_cross_teg_sweeper_status,
    "theprotocol_getCanaryJudgeStatus":       get_canary_judge_status,
    "theprotocol_getCanaryRebalancerStatus":  get_canary_rebalancer_status,
    "theprotocol_getSagaTimeoutStatus":       get_saga_timeout_status,
    "theprotocol_getAgentCardDriftList":      get_agent_card_drift_list,
    "theprotocol_getInviteCodes":             get_invite_codes,
    "theprotocol_getAdminFundingPending":     get_admin_funding_pending,
    "theprotocol_getEventStoreBalances":      get_eventstore_balances,
    # ─── §pass70 Sprint 6 — 13 new admin tools ────────────────────────────
    "theprotocol_getCanaryIronhandStatus":    get_canary_ironhand_status,
    "theprotocol_getCanaryIronhandEvents":    get_canary_ironhand_events,
    "theprotocol_getAgentHealthStatus":       get_agent_health_status,
    "theprotocol_getCicdSummary":             get_cicd_summary,
    "theprotocol_getCicdDeployments":         get_cicd_deployments,
    "theprotocol_getWebhookAggregate":        get_webhook_aggregate,
    "theprotocol_getRecentWebhookDeliveries": get_recent_webhook_deliveries,
    "theprotocol_getPayoutFundingPolicy":     get_reward_funding_policy,
    "theprotocol_getEventStoreStats":         get_eventstore_stats,
    "theprotocol_getEventStoreRecent":        get_eventstore_recent,
    "theprotocol_getAdminAuditLogs":          get_admin_audit_logs,
    "theprotocol_getFeeCollectorInfo":        get_fee_collector_info,
    "theprotocol_getDiagnosticChecks":        get_diagnostic_checks,
    # ─── §pass70 Sprint 7 — 10 new admin tools ────────────────────────────
    "theprotocol_getDiagnosticTargets":         get_diagnostic_targets,
    "theprotocol_getDiagnosticActions":         get_diagnostic_actions,
    "theprotocol_getBroadcastTemplates":        get_broadcast_templates,
    "theprotocol_getAgentCardPullsyncStatus":   get_agent_card_pullsync_status,
    "theprotocol_getAgentCardPullsyncEvents":   get_agent_card_pullsync_events,
    "theprotocol_getAdminMcpAuditLogByActor":   get_admin_mcp_audit_log_by_actor,
    "theprotocol_getAdminHealthCheckSimple":    get_admin_health_check_simple,
    "theprotocol_getAdminHealthCheckPublicOnly": get_admin_health_check_public_only,
    "theprotocol_getAdminHealthCheckAuthenticated": get_admin_health_check_authenticated,
    "theprotocol_getAdminTestTokens":           get_admin_test_tokens,
    # ─── §pass70 Sprint 8 — 10 new admin tools (4 safe + 6 destructive) ───
    "theprotocol_getAdminFundingAll":           get_admin_funding_all,
    "theprotocol_getAgentHealthTransitions":    get_agent_health_transitions,
    "theprotocol_getCombinedHealth":            get_combined_health,
    "theprotocol_getCloudOperatorHealth":       get_cloud_operator_health,
    "theprotocol_approveFunding":               approve_funding,
    "theprotocol_rejectFunding":                reject_funding,
    "theprotocol_triggerEigentrustComputation": trigger_eigentrust_computation,
    "theprotocol_svidRefresh":                  svid_refresh,
    "theprotocol_runAllDiagnostics":            run_all_diagnostics,
    "theprotocol_triggerDiagnosticAction":      trigger_diagnostic_action,
    # ─── §pass70 Sprint 9 — 15 new admin tools ────────────────────────────
    "theprotocol_getDockerStats":               get_docker_stats,
    "theprotocol_getPrometheusMetrics":         get_prometheus_metrics,
    "theprotocol_getOperatorLifecycle":         get_operator_lifecycle,
    "theprotocol_getAdminFlags":                get_admin_flags,
    "theprotocol_getAdminRegistryCard":         get_admin_registry_card,
    "theprotocol_getSystemResources":           get_system_resources,
    "theprotocol_getCanaryJudgeEvents":         get_canary_judge_events,
    "theprotocol_getCanaryRebalancerEvents":    get_canary_rebalancer_events,
    "theprotocol_getSagaTimeoutEvents":         get_saga_timeout_events,
    "theprotocol_getCrossTegSweeperEvents":     get_cross_teg_sweeper_events,
    "theprotocol_getEmailTemplates":            get_email_templates,
    "theprotocol_getAdminAgentDetail":          get_admin_agent_detail,
    "theprotocol_getAdminDeveloperDetail":      get_admin_developer_detail,
    "theprotocol_listIronhandIdentities":       list_ironhand_identities,
    "theprotocol_getAdminFiatStats":            get_admin_fiat_stats,
    # ─── §pass70 Sprint 10 — 20 new admin tools ───────────────────────────
    "theprotocol_suspendAgent":                 suspend_agent,
    "theprotocol_reinstateAgentEnforcement":    reinstate_agent_enforcement,
    "theprotocol_pauseAgentPayouts":            pause_agent_rewards,
    "theprotocol_resumeAgentPayouts":           resume_agent_rewards,
    "theprotocol_slashAgent":              slash_agent_stake,
    "theprotocol_previewSlash":            preview_slash_stake,
    "theprotocol_recordAgentOffense":           record_agent_offense,
    "theprotocol_approvePendingEnforcement":    approve_pending_enforcement,
    "theprotocol_rejectPendingEnforcement":     reject_pending_enforcement,
    "theprotocol_listQuarantinedRegistries":    list_quarantined_registries,
    "theprotocol_composeBroadcast":             compose_broadcast,
    "theprotocol_getAdminBroadcastsOverview":   get_admin_broadcasts_overview,
    "theprotocol_getBroadcastStats":            get_broadcast_stats,
    "theprotocol_retractBroadcast":             retract_broadcast,
    "theprotocol_updateBroadcast":              update_broadcast,
    "theprotocol_reinstateBroadcast":           reinstate_broadcast,
    "theprotocol_getAdminAgentsByDeveloper":    get_admin_agents_by_developer,
    "theprotocol_getAdminAgentOrphans":         get_admin_agent_orphans,
    "theprotocol_getAdminAgentFlags":           get_admin_agent_flags,
    "theprotocol_getAdminAgentSigningKeys":     get_admin_agent_signing_keys,
    # ─── §pass70 Sprint 11 — 28 new admin tools (fiat + sim + dev mgmt) ───
    "theprotocol_getAdminFiatPricing":          get_admin_fiat_pricing,
    "theprotocol_getAdminFiatPurchases":        get_admin_fiat_purchases,
    "theprotocol_getAdminFiatPurchaseDetail":   get_admin_fiat_purchase_detail,
    "theprotocol_getAdminFiatFlares":           get_admin_fiat_flares,
    "theprotocol_simulateFiatPricing":          simulate_fiat_pricing,
    "theprotocol_validateFiatPricing":          validate_fiat_pricing,
    "theprotocol_refundFiatPurchase":           refund_fiat_purchase,
    "theprotocol_replayFiatPurchase":           replay_fiat_purchase,
    "theprotocol_grantFiatFlare":               grant_fiat_flare,
    "theprotocol_revokeFiatFlare":              revoke_fiat_flare,
    "theprotocol_getAdminSimulationStatus":     get_admin_simulation_status,
    "theprotocol_getAdminSimulationAgents":     get_admin_simulation_agents,
    "theprotocol_getAdminSimulationSupplyAudit": get_admin_simulation_supply_audit,
    "theprotocol_getAdminSimulationTopology":   get_admin_simulation_topology,
    "theprotocol_getAdminSimulationDeadmanStatus": get_admin_simulation_deadman_status,
    "theprotocol_getAdminSimulationFundStatus": get_admin_simulation_fund_status,
    "theprotocol_getAdminSimulationLogs":       get_admin_simulation_logs,
    "theprotocol_startSimulation":              start_simulation,
    "theprotocol_stopSimulation":               stop_simulation,
    "theprotocol_issueFrameBSimulation":         mint_frame_b_simulation,
    "theprotocol_fundSimulationAgents":         fund_simulation_agents,
    "theprotocol_simulationFundingPreview":     simulation_funding_preview,
    "theprotocol_suspendDeveloper":             suspend_developer,
    "theprotocol_reinstateDeveloper":           reinstate_developer,
    "theprotocol_getAdminDeveloperActivity":    get_admin_developer_activity,
    "theprotocol_getAdminDeveloperQuota":       get_admin_developer_quota,
    "theprotocol_forceEmailVerify":             force_email_verify,
    "theprotocol_revokeDeveloperApiKeys":       revoke_developer_api_keys,
    "theprotocol_disableDeveloper2FA":          disable_developer_2fa,
    # ─── §pass70 Sprint 12 — 15 new admin tools ───────────────────────────
    "theprotocol_getOperatorsLifecycleOverview": get_operators_lifecycle_overview,
    "theprotocol_getBridgeAggregate":           get_bridge_aggregate,
    "theprotocol_rotateRegistrySigningKey":     rotate_registry_signing_key,
    "theprotocol_getCloudOperatorLogs":         get_cloud_operator_logs,
    "theprotocol_restartCloudOperatorService":  restart_cloud_operator_service,
    "theprotocol_provisionCloudOperator":       provision_cloud_operator,
    "theprotocol_teardownCloudOperator":        teardown_cloud_operator,
    "theprotocol_getCloudOperatorSelfLogs":     get_cloud_operator_self_logs,
    "theprotocol_cloudOperatorSelfRestart":     cloud_operator_self_restart,
    "theprotocol_updateDisputeRuling":          update_dispute_ruling,
    "theprotocol_getEventStoreCrossFramePeers": get_event_store_cross_frame_peers,
    "theprotocol_getEventStoreFederationOperators": get_event_store_federation_operators,
    "theprotocol_compositeHealthCheck":         composite_health_check,
    # ─── §pass70 Sprint 13 — 25 new admin tools ───────────────────────────
    "theprotocol_tegTreasuryIssue":              teg_treasury_mint,
    "theprotocol_tegTreasuryReceive":           teg_treasury_receive,
    "theprotocol_tegCrossTegFund":              teg_cross_teg_fund,
    "theprotocol_getEnforcementPolicyDefaults": get_enforcement_policy_defaults,
    "theprotocol_updateEnforcementPolicy":      update_enforcement_policy,
    "theprotocol_quarantineRegistry":           quarantine_registry,
    "theprotocol_liftQuarantine":               lift_quarantine,
    "theprotocol_acceptComplianceBaseline":     accept_compliance_baseline,
    "theprotocol_blacklistRegistry":            blacklist_registry,
    "theprotocol_bulkSuspendAgents":            bulk_suspend_agents,
    "theprotocol_bulkReinstateAgents":          bulk_reinstate_agents,
    "theprotocol_bulkRefreshAgentCards":        bulk_refresh_agent_cards,
    "theprotocol_transferAgentOwnership":       transfer_agent_ownership,
    "theprotocol_rotateAgentCredentials":       rotate_agent_credentials,
    "theprotocol_rotateAgentSigningKey":        rotate_agent_signing_key,
    "theprotocol_forceMtlsEnroll":              force_mtls_enroll,
    "theprotocol_deleteAdminAgent":             delete_admin_agent,
    "theprotocol_acknowledgeAgentFlag":         acknowledge_agent_flag,
    "theprotocol_updateDeveloperAdminFlags":    update_developer_admin_flags,
    "theprotocol_softDeleteDeveloper":          soft_delete_developer,
    "theprotocol_forceDeveloperPasswordReset":  force_developer_password_reset,
    "theprotocol_giftProvisioning":             gift_provisioning,
    "theprotocol_patchDeveloperQuota":          patch_developer_quota,
    "theprotocol_blockFederationAgent":         block_federation_agent,
    "theprotocol_unblockFederationAgent":       unblock_federation_agent,
    "theprotocol_federationCliAudit":           federation_cli_audit,
    # ─── §pass70 Sprint 14 — 20 new admin tools ───────────────────────────
    "theprotocol_listAdminOperatorApplications": list_admin_operator_applications,
    "theprotocol_getAdminOperatorApplication":  get_admin_operator_application,
    "theprotocol_approveOperatorApplication":   approve_operator_application,
    "theprotocol_rejectOperatorApplication":    reject_operator_application,
    "theprotocol_suspendOperator":              suspend_operator,
    "theprotocol_reinstateOperator":            reinstate_operator,
    "theprotocol_revokeOperatorAccess":         revoke_operator_access,
    "theprotocol_rotateOperatorPullToken":      rotate_operator_pull_token,
    "theprotocol_backfillPullTokens":           backfill_pull_tokens,
    "theprotocol_adminDownloadOperatorBundle":  admin_download_operator_bundle,
    "theprotocol_getApiTestArchiveRuns":        get_api_test_archive_runs,
    "theprotocol_getApiTestEndpoints":          get_api_test_endpoints,
    "theprotocol_getApiTestFlowValues":         get_api_test_flow_values,
    "theprotocol_resetApiTestFlowValues":       reset_api_test_flow_values,
    "theprotocol_testApiEndpoint":              test_api_endpoint,
    "theprotocol_eagerBootstrapApiTest":        eager_bootstrap_api_test,
    "theprotocol_getApiTestSandboxCredentials": get_api_test_sandbox_credentials,
    "theprotocol_getApiTestBucketClassification": get_api_test_bucket_classification,
    "theprotocol_getPeerRegistryCard":          get_peer_registry_card,
    "theprotocol_getHealthCheckWithAgentAuth":  get_health_check_with_agent_auth,
    # ─── §pass70 Sprint 15 — 30 new admin tools ───────────────────────────
    "theprotocol_getAdmissionStatus":           get_admission_status,
    "theprotocol_completeAdmission":            complete_admission,
    "theprotocol_getFederationComplianceDrifts": get_federation_compliance_drifts,
    "theprotocol_getFederationComplianceEnforcementMode": get_federation_compliance_enforcement_mode,
    "theprotocol_setFederationComplianceEnforcementMode": set_federation_compliance_enforcement_mode,
    "theprotocol_getFederationComplianceEvents": get_federation_compliance_events,
    "theprotocol_getFederationComplianceOverview": get_federation_compliance_overview,
    "theprotocol_getFederationCompliancePeerByOperator": get_federation_compliance_peer_by_operator,
    "theprotocol_getFederationCompliancePeerByID": get_federation_compliance_peer_by_id,
    "theprotocol_pollPeerComplianceNow":        poll_peer_compliance_now,
    "theprotocol_previewQuarantine":            preview_quarantine,
    "theprotocol_federationDriftScan":          federation_drift_scan,
    "theprotocol_listAdminFrameInvitations":    list_admin_frame_invitations,
    "theprotocol_getAdminFrameInvitation":      get_admin_frame_invitation,
    "theprotocol_approveFrameInvitation":       approve_frame_invitation,
    "theprotocol_rejectFrameInvitation":        reject_frame_invitation,
    "theprotocol_finalizeRetryFrameInvitation": finalize_retry_frame_invitation,
    "theprotocol_getFramesSpireStatus":         get_frames_spire_status,
    "theprotocol_resyncFrameEventStore":        resync_frame_eventstore,
    "theprotocol_revokeFrame":                  revoke_frame,
    "theprotocol_listFederationLicenses":       list_federation_licenses,
    "theprotocol_generateFederationLicense":    generate_federation_license,
    "theprotocol_getFederationTopologyOverview": get_federation_topology_overview,
    "theprotocol_probeTopologyPeer":            probe_topology_peer,
    "theprotocol_validateFederationPolicy":     validate_federation_policy,
    "theprotocol_runAttestationExpirySweep":    run_attestation_expiry_sweep,
    "theprotocol_runAttestationScheduleCron":   run_attestation_schedule_cron,
    "theprotocol_adminRevokeAttestation":       admin_revoke_attestation,
    "theprotocol_ironhandEnrollAgent":          ironhand_enroll_agent,
    "theprotocol_ironhandRevokeAgent":          ironhand_revoke_agent,
    "theprotocol_deleteSpireOrphan":            delete_spire_orphan,
    # ─── §pass70 Sprint 16 — 21 new admin tools ───────────────────────────
    "theprotocol_getFederationLocalEvents":     get_federation_local_events,
    "theprotocol_getAllFederationPeersAdmin":   get_all_federation_peers_admin,
    "theprotocol_getAdminFederationPolicyCompliance": get_admin_federation_policy_compliance,
    "theprotocol_federationPolicyUpdateRequest": federation_policy_update_request,
    "theprotocol_federationRequestAdmission":   federation_request_admission,
    "theprotocol_getAdminFederationSelfHealth": get_admin_federation_self_health,
    "theprotocol_getTopologyPeerEvents":        get_topology_peer_events,
    "theprotocol_getFederationLicenseDetail":   get_federation_license_detail,
    "theprotocol_deleteFederationLicense":      delete_federation_license,
    "theprotocol_reinstateFederationLicense":   reinstate_federation_license,
    "theprotocol_revokeFederationLicense":      revoke_federation_license,
    "theprotocol_suspendFederationLicense":     suspend_federation_license,
    "theprotocol_ironhandDeleteAgentProxy":     ironhand_delete_agent_proxy,
    "theprotocol_ironhandRegisterAgentProxy":   ironhand_register_agent_proxy,
    # ─── §pass70 Sprint 17 — 12 new admin tools ───────────────────────────
    "theprotocol_getAgentCardDriftDetail":      get_agent_card_drift_detail,
    "theprotocol_forceRegisterAgentCard":       force_register_agent_card,
    "theprotocol_refreshAgentCardDrift":        refresh_agent_card_drift,
    "theprotocol_getBroadcastTemplateDetail":   get_broadcast_template_detail,
    "theprotocol_getBroadcastEmailRetryStatus": get_broadcast_email_retry_status,
    "theprotocol_getBroadcastEmailRetryDeadLetter": get_broadcast_email_retry_dead_letter,
    "theprotocol_getBroadcastSchedulerStatus":  get_broadcast_scheduler_status,
    "theprotocol_resetApiTestSandbox":          reset_api_test_sandbox,
    "theprotocol_runAllApiTests":               run_all_api_tests,
    "theprotocol_testApiCategory":              test_api_category,
    "theprotocol_testApiFlow":                  test_api_flow,
    "theprotocol_getAttestationsAnalytics":     get_attestations_analytics,
    # ─── §pass70 Sprint 18 — 4 new admin tools (bridge) ───────────────────
    "theprotocol_bridgeIssueWrapped":            bridge_mint_wrapped,
    "theprotocol_bridgeRedeem":                 bridge_redeem,
    "theprotocol_bridgeUnlock":                 bridge_unlock,
    "theprotocol_getBridgeStatus":              get_bridge_status,
    # ─── §pass70 Sprint 19 — 8 new admin tools ────────────────────────────
    "theprotocol_listAdminBundlesReports":      list_admin_bundles_reports,
    "theprotocol_dismissBundleReport":          dismiss_bundle_report,
    "theprotocol_hideBundle":                   hide_bundle,
    "theprotocol_unhideBundle":                 unhide_bundle,
    "theprotocol_getCanaryIronhandSvids":       get_canary_ironhand_svids,
    "theprotocol_getCollusionStatus":           get_collusion_status,
    "theprotocol_getAdminMetricsAgentActivity": get_admin_metrics_agent_activity,
    "theprotocol_getAdminCollusionByAgent":     get_admin_collusion_by_agent,
    # ─── §pass70 Sprint 20 — 20 new admin tools ───────────────────────────
    "theprotocol_getSupplyAuditorStatus":       get_supply_auditor_status,
    "theprotocol_getSupplyAuditorEvents":       get_supply_auditor_events,
    "theprotocol_getAdminWorkersStatus":        get_admin_workers_status,
    "theprotocol_searchAdminEvents":            search_admin_events,
    "theprotocol_getEventsAggregate":           get_events_aggregate,
    "theprotocol_uploadRegistryCardIcon":       upload_registry_card_icon,
    "theprotocol_distributeFromFeeCollector":   distribute_from_fee_collector,
    "theprotocol_generateInviteCodes":          generate_invite_codes,
    "theprotocol_validateInviteCodeAdmin":      validate_invite_code_admin,
    "theprotocol_revokeInviteCode":             revoke_invite_code,
    "theprotocol_disableWebhookAdmin":          disable_webhook_admin,
    "theprotocol_enableWebhookAdmin":           enable_webhook_admin,
    "theprotocol_testWebhookAdmin":             test_webhook_admin,
    "theprotocol_getTutorialHealth":            get_tutorial_health,
    "theprotocol_executeTutorial":              execute_tutorial,
    "theprotocol_generateTutorialProof":        generate_tutorial_proof,
    "theprotocol_runDiagnosticsSubset":         run_diagnostics_subset,
    "theprotocol_getDiagnosticConfig":          get_diagnostic_config,
    # ─── §pass70 Sprint 21 — 5 new admin tools (final gap fillers) ────────
    "theprotocol_testApiFederation":            test_api_federation,
    "theprotocol_deleteOauthFederationTrust":   delete_oauth_federation_trust,
    "theprotocol_reconcileFiatProvisioning":    reconcile_fiat_provisioning,
    "theprotocol_resendFiatMagicLink":          resend_fiat_magic_link,
    "theprotocol_updateSupportTicketStatus":    update_support_ticket_status,
}

# Tools that require NO admin auth (they ARE the auth step)
ADMIN_NO_AUTH_TOOLS = {"theprotocol_adminGetDeveloperToken"}


# ---------------------------------------------------------------------------
# Gateway meta-tools + toolset filtering (2026-07-14 L0/L1 — mirrors server.py;
# see STRATEGY_2026-07-14_MCP_TOOL_LOADING.md). Listing-only; admin tier auth
# on tools/call is untouched. search/describe/listToolsets join
# ADMIN_NO_AUTH_TOOLS because they reveal exactly what the unauthenticated
# tools/list handshake already serves (schemas + bucket names, no data).
# ---------------------------------------------------------------------------
from . import mcp_tasks, resources, tools_gateway
from .tool_categories import (
    ADMIN_BUCKETS,
    ADMIN_CORE_TOOLS,
    bare_name,
    filter_schemas,
    parse_toolsets,
)
from .tool_metadata import decorate_schemas, task_tools
from agentvault_registry.mcp.route_constraints import apply_route_constraints  # §MCPTEST30 (V0548)
from .tool_result import is_failure  # §MCPTEST30: one rule for a failed result

ADMIN_SERVER_INFO["capabilities"]["tasks"] = mcp_tasks.TASKS_CAPABILITY


def _admin_result_payload(result: Any) -> Dict[str, Any]:
    """CallToolResult with structuredContent dual-emit + honest isError —
    admin twin of server.py's _tool_result_payload."""
    is_err = is_failure(result)   # §MCPTEST30: an `error` VALUE, never the key alone (mcp/tool_result.py)
    payload: Dict[str, Any] = {
        "content": [{"type": "text", "text": _format_result(result)}],
        "isError": bool(is_err),
    }
    if isinstance(result, dict) and not is_err:
        payload["structuredContent"] = result
    return payload


async def _gateway_admin_search_tools(query: str = "", toolsets: str = None, limit: int = 10) -> Dict[str, Any]:
    return await tools_gateway.search_tools(
        ADMIN_TOOL_SCHEMAS, is_admin=True, query=query, toolsets=toolsets, limit=limit
    )


async def _gateway_admin_describe_tools(names: list = None) -> Dict[str, Any]:
    return await tools_gateway.describe_tools(ADMIN_TOOL_SCHEMAS, is_admin=True, names=names or [])


async def _gateway_admin_list_toolsets() -> Dict[str, Any]:
    return await tools_gateway.list_toolsets(ADMIN_TOOL_SCHEMAS, is_admin=True)


# §MEMBERSHIP phase B (2026-10-02): the commons seasons' admin tools (admin_treasury; mcp/tools_commons.py)
from .tools_commons import (  # noqa: E402
    COMMONS_ADMIN_TOOL_SCHEMAS,
    admin_commons_cancel_season,
    admin_commons_close_season,
    admin_commons_open_season,
    admin_commons_pay_season,
    admin_commons_strike_submission,
    admin_commons_write_off_award,
)

ADMIN_TOOL_DISPATCH.update({
    "theprotocol_adminCommonsOpenSeason": admin_commons_open_season,
    "theprotocol_adminCommonsCloseSeason": admin_commons_close_season,
    "theprotocol_adminCommonsStrikeSubmission": admin_commons_strike_submission,
    "theprotocol_adminCommonsPaySeason": admin_commons_pay_season,
    "theprotocol_adminCommonsWriteOffAward": admin_commons_write_off_award,
    "theprotocol_adminCommonsCancelSeason": admin_commons_cancel_season,
})
ADMIN_TOOL_SCHEMAS.extend(COMMONS_ADMIN_TOOL_SCHEMAS)

ADMIN_TOOL_DISPATCH.update({
    tools_gateway.SEARCH_TOOL: _gateway_admin_search_tools,
    tools_gateway.DESCRIBE_TOOL: _gateway_admin_describe_tools,
    tools_gateway.LIST_TOOLSETS_TOOL: _gateway_admin_list_toolsets,
    tools_gateway.INVOKE_TOOL: tools_gateway._invoke_stub,
})
ADMIN_TOOL_SCHEMAS.extend(tools_gateway.GATEWAY_TOOL_SCHEMAS)

# 2026-07-14 reference-grade pass — stamp title/annotations (+ curated
# outputSchema / execution.taskSupport for the admin task tools) onto the
# final catalog. Idempotent: gateway schema objects are shared with server.py.
decorate_schemas(ADMIN_TOOL_SCHEMAS, is_admin=True)
# §MCPTEST30 (V0548): each tool's inputSchema states what its route enforces (mcp/route_constraints.py, kept equal to
# the routes by test_mcp_schemas_state_route_constraints.py); a key the tool states itself is never changed
apply_route_constraints(ADMIN_TOOL_SCHEMAS)
ADMIN_NO_AUTH_TOOLS |= {
    tools_gateway.SEARCH_TOOL, tools_gateway.DESCRIBE_TOOL, tools_gateway.LIST_TOOLSETS_TOOL,
}


def _resolve_admin_tool_visibility(request: Request):
    """Admin twin of server.py's resolver (?mode=/?toolsets= + X-MCP-* headers)."""
    q = request.query_params
    mode = (q.get("mode") or request.headers.get("x-mcp-mode") or "full").strip().lower()
    raw_toolsets = q.get("toolsets") or request.headers.get("x-mcp-toolsets")
    problems = []
    if mode not in ("full", "gateway"):
        problems.append(f"unknown mode '{mode}' (valid: full, gateway)")
        mode = "full"
    selected, unknown = parse_toolsets(raw_toolsets, is_admin=True)
    if unknown:
        problems.append(f"unknown toolsets {unknown} (valid: {sorted(ADMIN_BUCKETS.keys())})")
    return mode, selected, problems


def _admin_tools_listing(mode: str, selected) -> List[Dict[str, Any]]:
    visible = filter_schemas(ADMIN_TOOL_SCHEMAS, selected, is_admin=True)
    if mode == "gateway":
        visible = [
            s for s in visible
            if s.get("name") in tools_gateway.GATEWAY_TOOL_NAMES
            or bare_name(s.get("name", "")) in ADMIN_CORE_TOOLS
        ]
    return visible

# ---------------------------------------------------------------------------
# JSON-RPC helpers (same pattern as server.py)
# ---------------------------------------------------------------------------

class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Union[Dict[str, Any], List[Any]]] = None


def _ok(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse(content={"jsonrpc": "2.0", "id": request_id, "result": result})


def _err(request_id: Any, code: int, message: str) -> JSONResponse:
    http_status = 500
    if code in (-32700, -32600, -32602):
        http_status = 400
    elif code in (-32601, -32002):   # §MCPTEST30: -32002 resource not found is the client's miss, not a 500
        http_status = 404
    elif code == -32001:
        http_status = 401
    elif code == -32003:   # §MCPTEST30 V0529: the credential could not be checked (the database did not answer)
        http_status = 503
    return JSONResponse(
        status_code=http_status,
        content={"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        headers={"Retry-After": "5"} if http_status == 503 else None,
    )


def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or request.headers.get("authorization", "")
    parts = auth.split()
    return parts[1] if len(parts) == 2 and parts[0].lower() == "bearer" else None


def _format_result(result: Any) -> str:
    if is_failure(result):
        return f"Error: {result['error']}"
    try:
        return json.dumps(result, indent=2, default=str)
    except Exception:
        return str(result)


# ---------------------------------------------------------------------------
# Streamable HTTP endpoint (MCP spec 2025-03-26)
# ---------------------------------------------------------------------------

# §MCPTEST30 (V0524): every tool's inputSchema by name, built at first use: ADMIN_TOOL_SCHEMAS is extended in place after its
# definition (the Guild, the gateway), so a map taken at import would miss those tools.
_INPUT_SCHEMA_BY_NAME: Dict[str, Any] = {}


def _input_schema(name: str) -> Optional[Dict[str, Any]]:
    if not _INPUT_SCHEMA_BY_NAME:
        _INPUT_SCHEMA_BY_NAME.update({t["name"]: t.get("inputSchema") for t in ADMIN_TOOL_SCHEMAS if isinstance(t, dict) and "name" in t})
    return _INPUT_SCHEMA_BY_NAME.get(name)


async def _incoming_is_notification(request: Request) -> bool:
    """§MCPTEST30 (2026-10-01): is the posted message a JSON-RPC notification (a method, no id)? MCP Streamable HTTP
    accepts one with 202 and no body; this endpoint used to answer it with 200 and a JSON-RPC result."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 — not JSON: the handler answers it as a parse error
        return False
    return isinstance(body, dict) and "id" not in body and str(body.get("method") or "").startswith("notifications/")


async def _request_json(request: Request) -> Any:
    """The posted JSON-RPC message (Starlette keeps the parse), or None when it was not JSON."""
    try:
        return await request.json()
    except Exception:  # noqa: BLE001 — the handler already answered it as a parse error
        return None


@router.post("", summary="Admin MCP Streamable HTTP (POST)")
async def admin_streamable_post(request: Request):
    """Streamable HTTP transport for admin MCP. Returns 401 without auth to trigger OAuth."""
    import json as _json
    from fastapi.responses import StreamingResponse

    # Return 401 to trigger OAuth flow when no token
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    has_token = bool(auth_header and len(auth_header.split()) == 2 and auth_header.split()[0].lower() == "bearer")
    if not has_token:
        try:
            body = await request.json()
            method = body.get("method", "")
        except Exception:
            method = ""
        if method not in ("initialize", "ping"):
            proto = request.headers.get("x-forwarded-proto", "https")
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
            resource_url = f"{proto}://{host}/.well-known/oauth-protected-resource"
            return JSONResponse(
                status_code=401,
                content={"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Admin authentication required"}},
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_url}"'},
            )

    # §MCPTEST30: a notification is handled and accepted with 202, no body (the receiver never replies to one)
    if await _incoming_is_notification(request):
        from starlette.responses import Response as _Response
        await handle_admin_rpc(request)
        return _Response(status_code=202)

    json_response = await handle_admin_rpc(request)
    response_body = json_response.body.decode("utf-8")

    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        try:
            parsed = _json.loads(response_body)
            if parsed.get("id") is None and not parsed.get("error"):
                return StreamingResponse(iter([]), status_code=200, media_type="text/event-stream")
        except Exception:
            pass
        sse_payload = tools_gateway.sse_answer(await _request_json(request), response_body)   # D6-725
        async def _sse():
            yield sse_payload
        return StreamingResponse(
            _sse(), status_code=200, media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )
    return json_response


@router.get("", summary="Admin MCP Streamable HTTP (GET — notifications)")
async def admin_streamable_get(request: Request):
    """SSE stream for server-initiated admin notifications."""
    import json as _json
    import asyncio as _asyncio
    from fastapi.responses import StreamingResponse

    async def _stream():
        info = {"jsonrpc": "2.0", "method": "notifications/serverInfo", "params": ADMIN_SERVER_INFO}
        yield f"event: message\ndata: {_json.dumps(info)}\n\n"
        try:
            while True:
                await _asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass
    return StreamingResponse(
        _stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.delete("", summary="Admin MCP Streamable HTTP (DELETE — close session)")
async def admin_streamable_delete():
    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# OAuth metadata under /mcp/admin/ (Claude Desktop looks here for admin connector)
# ---------------------------------------------------------------------------

@router.get("/.well-known/oauth-authorization-server")
async def admin_oauth_metadata(request: Request):
    """OAuth metadata discovery — redirects to root well-known."""
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    issuer = f"{proto}://{host}"
    return JSONResponse(
        content={
            "issuer": issuer,
            "authorization_endpoint": f"{issuer}/oauth/authorize",
            "token_endpoint": f"{issuer}/oauth/token",
            "registration_endpoint": f"{issuer}/oauth/register",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_methods_supported": ["client_secret_post"],
            "code_challenge_methods_supported": ["S256"],
            "scopes_supported": ["mcp:tools", "mcp:admin"],
        },
        headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "mcp-protocol-version"},
    )


@router.get("/.well-known/oauth-protected-resource")
async def admin_protected_resource(request: Request):
    """Protected resource metadata for admin MCP."""
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
    issuer = f"{proto}://{host}"
    return JSONResponse(
        content={
            "resource": f"{issuer}/mcp/admin",
            "authorization_servers": [issuer],
            "scopes_supported": ["mcp:admin"],
            "bearer_methods_supported": ["header"],
        },
        headers={"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Headers": "mcp-protocol-version"},
    )


# ---------------------------------------------------------------------------
# Legacy JSON-RPC endpoint (backward compatibility)
# ---------------------------------------------------------------------------

@router.post("/rpc", response_class=JSONResponse, summary="MCP Admin JSON-RPC 2.0 endpoint (legacy)")
async def handle_admin_rpc(request: Request) -> JSONResponse:
    """
    TheProtocol Admin MCP Server — JSON-RPC 2.0 endpoint.

    Requires admin developer JWT (is_admin=True).

    Tools:
        theprotocol.adminRequest           — Proxy any registry HTTP call
        theprotocol.adminQueryEventStore   — EventStore immutable ledger
        theprotocol.adminPromQuery         — PromQL queries against Prometheus

    Authentication:
        Authorization: Bearer <admin_developer_jwt>
    """
    request_id = None

    try:
        raw_body = await request.json()
    except Exception:
        return _err(None, -32700, "Parse error: invalid JSON")

    if not isinstance(raw_body, dict):
        return _err(None, -32600, "Invalid Request: body must be a JSON object")

    try:
        payload = JsonRpcRequest(**raw_body)
        request_id = payload.id
    except Exception as e:
        return _err(None, -32600, f"Invalid Request: {e}")

    method = payload.method
    params = payload.params or {}
    if isinstance(params, list):
        params = {}

    token = _extract_token(request)
    logger.info(f"MCP Admin RPC: method={method} id={request_id} auth={'yes' if token else 'no'}")

    # Return 401 with WWW-Authenticate to trigger OAuth flow
    # Allow handshake + discovery (initialize, ping, tools/list, notifications) without token
    # Allow all methods through — admin is enforced at the tool execution level, not the gate.
    # This lets tools with inline developer_jwt params (adminRequest, etc.) work
    # even when no bridge-level token is present (OAuth connector flow).
    handshake_methods = ("initialize", "ping", "tools/list", "resources/list",
                         "resources/templates/list", "prompts/list")
    is_handshake = method in handshake_methods or method.startswith("notifications/")
    is_tools_call = (method == "tools/call")
    if not token and not is_handshake and not is_tools_call:
        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
        resource_url = f"{proto}://{host}/.well-known/oauth-protected-resource"
        return JSONResponse(
            status_code=401,
            content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "Admin authentication required"}},
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_url}"'},
        )

    # --- Auth: discovery methods pass through, admin enforced on tools/call ---
    # Let initialize, ping, tools/list, resources/list, prompts/list, notifications/*
    # through without admin check — so Claude Desktop can discover tools via OAuth.
    # Admin is enforced on tools/call (the actual execution).
    discovery_methods = ("initialize", "ping", "tools/list", "resources/list",
                         "resources/templates/list", "prompts/list")
    is_discovery = method in discovery_methods or method.startswith("notifications/")

    if not is_discovery:
        # Try to authenticate if token is present
        if token:
            try:
                async with get_db_context() as db:
                    auth_ctx = await authenticate_mcp_token(token, db)
            except MCPAuthUnavailable as e:   # §MCPTEST30 V0529: "try again", never "admin access required"
                return _err(request_id, -32003, str(e))
            if not auth_ctx.is_developer or not auth_ctx.is_admin:
                # Token present but not admin — check if tool has inline jwt
                if not is_tools_call:
                    return _err(
                        request_id, -32001,
                        "Admin access required. "
                        "Provide an admin developer JWT or admin API key "
                        "(account must have is_admin=True)."
                    )
                # For tools/call, let it through — tool handler checks inline developer_jwt
                auth_ctx = None
        else:
            # No token — tools/call will use inline developer_jwt if provided
            auth_ctx = None
    else:
        auth_ctx = None

    try:
        # --- Protocol methods ---

        if method == "initialize":
            return _ok(request_id, {
                "protocolVersion": ADMIN_SERVER_INFO["protocolVersion"],
                "capabilities":    ADMIN_SERVER_INFO["capabilities"],
                "serverInfo": {
                    "name":        ADMIN_SERVER_INFO["name"],
                    "version":     ADMIN_SERVER_INFO["version"],
                    "description": ADMIN_SERVER_INFO["description"],
                    "icons":       ADMIN_SERVER_INFO["icons"],
                },
                "instructions": (
                    "TheProtocol Admin MCP Server — Commander-only.\n"
                    "Tools:\n"
                    "  theprotocol.adminRequest          — Any registry endpoint\n"
                    "  theprotocol.adminQueryEventStore  — EventStore ledger\n"
                    "  theprotocol.adminPromQuery        — Prometheus PromQL\n"
                    "All tools require admin developer JWT.\n"
                    "Authorization: Bearer <admin_jwt>\n"
                    "CONTEXT-SAVING OPTIONS: ?mode=gateway (or X-MCP-Mode: gateway) lists only "
                    "the escape-hatch core plus listToolsets/searchTools/describeTools/invokeTool/"
                    "enableToolset/disableToolset; ?toolsets=canary,simulation (X-MCP-Toolsets) "
                    "lists chosen buckets; enableToolset persists a per-credential selection (24h). "
                    "No parameters = the full catalog, unchanged.\n"
                    "ALSO: MCP resources (registry card, solvency card, JWKS, OpenAPI, network "
                    "stats, agent cards by DID — resources/read is admin-gated here) and "
                    "experimental async tasks on long admin tools (testApiFlow, drift scans, "
                    "lifecycle tests…): tools/call with params.task={ttl} → poll tasks/get → "
                    "tasks/result. Every tool carries title + behavior annotations."
                ),
            })

        elif method == "ping":
            return _ok(request_id, {})

        elif method.startswith("notifications/"):   # §MCPTEST30: a notification is accepted, never refused
            return _ok(request_id, {})

        elif method == "tools/list":
            mode, selected, problems = _resolve_admin_tool_visibility(request)
            if problems:
                return _err(request_id, -32602, "Invalid params: " + "; ".join(problems))
            # L2 session selection (enableToolset/disableToolset) when the
            # request carries no explicit filter.
            if selected is None and token:
                selected = await tools_gateway.get_session_selection(
                    mcp_tasks.ctx_hash(token), is_admin=True
                )
            listing = {"tools": _admin_tools_listing(mode, selected)}
            cursor = (params or {}).get("cursor")
            if cursor is not None:
                try:
                    offset = int(cursor)
                    if offset < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return _err(request_id, -32602, "Invalid params: bad cursor")
                full = listing["tools"]
                listing = {"tools": full[offset:offset + 100]}
                if offset + 100 < len(full):
                    listing["nextCursor"] = str(offset + 100)
            return _ok(request_id, listing)

        elif method == "resources/list":
            return _ok(request_id, resources.list_resources())

        elif method == "resources/templates/list":
            return _ok(request_id, resources.list_templates())

        elif method == "resources/read":
            # Reaches here only past the admin gate above (not a discovery method).
            uri = (params or {}).get("uri", "")
            contents, res_err = await resources.read_resource(uri)
            if res_err:
                return _err(request_id, resources.error_code(res_err), res_err)
            return _ok(request_id, contents)

        elif method == "prompts/list":
            return _ok(request_id, {"prompts": []})

        # --- Async tasks (2025-11-25 experimental; auth-context bound) ---

        elif method == "tasks/get":
            rec = await mcp_tasks.get_task((params or {}).get("taskId", ""), mcp_tasks.ctx_hash(token))
            if rec is None:
                return _err(request_id, -32602, "Failed to retrieve task: Task not found")
            return _ok(request_id, mcp_tasks.task_public(rec))

        elif method == "tasks/result":
            rec, terr = await mcp_tasks.wait_result((params or {}).get("taskId", ""), mcp_tasks.ctx_hash(token))
            if terr:
                return _err(request_id, -32602 if "not found" in terr else -32603, terr)
            final = dict(rec.get("result") or {"content": [{"type": "text", "text": rec.get("statusMessage", "")}],
                                               "isError": rec["status"] != "completed"})
            final.setdefault("_meta", {})[mcp_tasks.RELATED_TASK_META] = {"taskId": rec["taskId"]}
            return _ok(request_id, final)

        elif method == "tasks/cancel":
            rec, terr = await mcp_tasks.cancel_task((params or {}).get("taskId", ""), mcp_tasks.ctx_hash(token))
            if terr:
                return _err(request_id, -32602, terr)
            return _ok(request_id, mcp_tasks.task_public(rec))

        elif method == "tasks/list":
            listing, terr = await mcp_tasks.list_tasks(mcp_tasks.ctx_hash(token), (params or {}).get("cursor"))
            if terr:
                return _err(request_id, -32602, terr)
            return _ok(request_id, listing)

        elif method == "tools/call":
            # §AGORAWORDS (V0419): a renamed tool still executes under its old name (mcp/tool_aliases.py).
            tool_name = resolve_alias(params.get("name", ""))
            arguments = params.get("arguments", {}) or {}

            if not tool_name:
                return _err(request_id, -32602, "Invalid params: 'name' required for tools/call")

            # Gateway invokeTool unwraps BEFORE dispatch so the inner tool
            # keeps its own admin-auth rules and audit row (mirrors server.py).
            if tool_name == tools_gateway.INVOKE_TOOL:
                try:
                    tool_name, arguments = tools_gateway.unwrap_invoke(arguments, ADMIN_TOOL_DISPATCH)
                except ValueError as ve:
                    return _err(request_id, -32602, str(ve))

            # L2 dynamic toolsets — session listing preference (mirrors server.py).
            if tool_name in (tools_gateway.ENABLE_TOOLSET_TOOL, tools_gateway.DISABLE_TOOLSET_TOOL):
                sel_result = await tools_gateway.modify_session_toolsets(
                    mcp_tasks.ctx_hash(token), arguments.get("toolsets"),
                    is_admin=True, enable=(tool_name == tools_gateway.ENABLE_TOOLSET_TOOL),
                )
                return _ok(request_id, _admin_result_payload(sel_result))

            if tool_name not in ADMIN_TOOL_DISPATCH:
                return _err(
                    request_id, -32601,
                    f"Tool not found: '{tool_name}'. "
                    f"Available: {list(ADMIN_TOOL_DISPATCH.keys())}"
                )

            # §MCPTEST30 (V0524): an argument its tool's inputSchema cannot take is the caller's -32602, before the tool
            # runs (mcp/arguments.py; 72 of 107 mistyped reads answered -32603 "Internal error" on sbx-alpha, V0521)
            _arg_problems = argument_problems(_input_schema(tool_name), arguments)
            if _arg_problems:
                return _err(request_id, -32602, "Invalid params: " + "; ".join(_arg_problems))

            tool_fn = ADMIN_TOOL_DISPATCH[tool_name]

            # §pass68 — per-tool audit hook. Same pattern as public server.py.
            # Captures actor (after auth), args (sanitized via deny-list incl.
            # `developer_jwt`), outcome, latency. Fire-and-forget — never blocks.
            actor_ip = request.client.host if request.client else None
            ua = request.headers.get("user-agent")
            req_id = request.headers.get("x-request-id") or (str(request_id) if request_id else None)

            # --- Task-augmented execution (2025-11-25 experimental) ---------
            task_params = params.get("task")
            if task_params is not None:
                if bare_name(tool_name) not in task_tools(is_admin=True):
                    return _err(
                        request_id, -32601,
                        f"Tool '{tool_name}' does not support task-augmented execution "
                        "(execution.taskSupport is absent) — call it normally."
                    )
                if auth_ctx is None and tool_name not in ADMIN_NO_AUTH_TOOLS:
                    return _err(request_id, -32001,
                                "Admin auth required for task-augmented execution.")
                ttl_ms = task_params.get("ttl") if isinstance(task_params, dict) else None
                rec = await mcp_tasks.create_task(mcp_tasks.ctx_hash(token), ttl_ms, tool_name)

                async def _bg_admin_call(tool_fn=tool_fn, tool_name=tool_name, arguments=arguments,
                                         auth_ctx=auth_ctx, actor_ip=actor_ip, ua=ua, req_id=req_id):
                    bg_t0 = time.perf_counter()
                    try:
                        if tool_name in ADMIN_NO_AUTH_TOOLS:
                            r = await tool_fn(**arguments)
                        else:
                            r = await tool_fn(auth_ctx, **arguments)
                        payload, outcome = _admin_result_payload(r), "success"
                    except Exception as e:  # noqa: BLE001 — task boundary
                        payload = {"content": [{"type": "text", "text": f"Error: {e!r}"}], "isError": True}
                        outcome = "error"
                    await emit_mcp_audit(
                        tool_name=tool_name, arguments=arguments, auth_ctx=auth_ctx,
                        outcome=outcome, result_or_error=payload,
                        latency_ms=(time.perf_counter() - bg_t0) * 1000.0,
                        actor_ip=actor_ip, user_agent=ua, request_id=req_id,
                        is_admin_server=True,
                    )
                    return payload

                mcp_tasks.spawn(rec["taskId"], _bg_admin_call)
                return _ok(request_id, {
                    "task": mcp_tasks.task_public(rec),
                    "_meta": {mcp_tasks.IMMEDIATE_RESPONSE_META: (
                        f"Task {rec['taskId']} accepted for {tool_name}; poll tasks/get, "
                        "then fetch the outcome with tasks/result."
                    )},
                })

            t0_admin = time.perf_counter()
            audit_outcome = "success"
            audit_result_or_error: Any = None

            try:
                # getDeveloperToken needs no auth context — it IS the auth step
                if tool_name in ADMIN_NO_AUTH_TOOLS:
                    refuse_unbindable(tool_fn, (), arguments)
                    result = await tool_fn(**arguments)
                elif auth_ctx is None and tool_name != "theprotocol_adminRequest":
                    # No auth context and tool doesn't support inline jwt
                    audit_outcome = "failure"
                    audit_result_or_error = "admin auth required"
                    latency_ms = (time.perf_counter() - t0_admin) * 1000.0
                    await emit_mcp_audit(
                        tool_name=tool_name,
                        arguments=arguments,
                        auth_ctx=auth_ctx,
                        outcome=audit_outcome,
                        result_or_error=audit_result_or_error,
                        latency_ms=latency_ms,
                        actor_ip=actor_ip,
                        user_agent=ua,
                        request_id=req_id,
                        is_admin_server=True,
                    )
                    return _err(request_id, -32001,
                        f"Tool '{tool_name}' requires admin auth. "
                        "Call adminGetDeveloperToken first, then use adminRequest with developer_jwt param."
                    )
                else:
                    refuse_unbindable(tool_fn, (auth_ctx,), arguments, auth_ctx)
                    result = await tool_fn(auth_ctx, **arguments)
                audit_result_or_error = result
            except MCPAuthError as e:
                latency_ms = (time.perf_counter() - t0_admin) * 1000.0
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx,
                    outcome="failure",
                    result_or_error=str(e),
                    latency_ms=latency_ms,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=True,
                )
                return _err(request_id, -32001, str(e))
            except ToolArgumentsRefused as bad:
                # §MCPTEST30 (V0545): arguments that do not bind to the tool are the caller's -32602, audited as a
                # refusal under the caller, never as a tool failure (the TypeError branch below keeps a TypeError
                # raised INSIDE a running tool, which binding cannot see)
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx,
                    outcome="failure",
                    result_or_error=f"Invalid params: {bad}",
                    latency_ms=(time.perf_counter() - t0_admin) * 1000.0,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=True,
                )
                return _err(request_id, -32602, f"Invalid params: {bad}")
            except TypeError as e:
                latency_ms = (time.perf_counter() - t0_admin) * 1000.0
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx,
                    outcome="error",
                    result_or_error=repr(e),
                    latency_ms=latency_ms,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=True,
                )
                return _err(request_id, -32602, f"Invalid params: {e}")

            # Success path — emit audit then return
            latency_ms = (time.perf_counter() - t0_admin) * 1000.0
            await emit_mcp_audit(
                tool_name=tool_name,
                arguments=arguments,
                auth_ctx=auth_ctx,
                outcome="success",
                result_or_error=audit_result_or_error,
                latency_ms=latency_ms,
                actor_ip=actor_ip,
                user_agent=ua,
                request_id=req_id,
                is_admin_server=True,
            )
            return _ok(request_id, _admin_result_payload(result))

        else:
            return _err(request_id, -32601, f"Method not found: '{method}'")

    except MCPAuthError as e:
        return _err(request_id, -32001, str(e))
    except MCPAuthUnavailable as e:   # §MCPTEST30 V0529
        return _err(request_id, -32003, str(e))
    except TypeError as e:
        logger.warning(f"MCP Admin param error for {method}: {e}")
        return _err(request_id, -32602, f"Invalid params: {e}")
    except Exception as e:
        logger.error(f"MCP Admin RPC error for {method}: {e}", exc_info=True)
        # §MCPTEST30 V0529: the exception's text, never a database driver's words
        return _err(request_id, -32603, f"Internal error: {safe_exception_text(e)}")


# ---------------------------------------------------------------------------
# Convenience endpoints
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SSE endpoint — required by mcp-remote (Claude Desktop transport)
# ---------------------------------------------------------------------------

@router.get("/sse", summary="Admin MCP SSE transport endpoint (Claude Desktop)")
async def admin_mcp_sse(request: Request):
    """
    SSE transport endpoint. Allows unauthenticated connections for tool discovery.
    Auth enforced on tools/call.
    """
    from fastapi.responses import StreamingResponse

    async def event_generator():
        rpc_url = os.environ.get("MCP_ADMIN_PUBLIC_RPC_URL", "http://localhost:8000/mcp/admin/rpc")
        yield f"event: endpoint\ndata: {rpc_url}\n\n"

        info_event = {
            "jsonrpc": "2.0",
            "method": "notifications/serverInfo",
            "params": ADMIN_SERVER_INFO,
        }
        yield f"event: message\ndata: {json.dumps(info_event)}\n\n"

        try:
            while True:
                await asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/sse", summary="Admin MCP Streamable HTTP endpoint (mcp-remote POST transport)")
async def admin_mcp_streamable_http(request: Request):
    """
    Streamable HTTP POST transport — required by mcp-remote (Claude Desktop).

    mcp-remote POSTs JSON-RPC requests with Accept: text/event-stream and
    expects the response wrapped as a single SSE message event.
    Delegates to handle_admin_rpc and wraps the result.
    """
    from fastapi.responses import StreamingResponse

    json_response = await handle_admin_rpc(request)
    response_body = json_response.body.decode("utf-8")

    # Notifications (no id) — return empty 200
    try:
        parsed = json.loads(response_body)
        if parsed.get("id") is None and not parsed.get("error"):
            return StreamingResponse(
                iter([]),
                status_code=200,
                media_type="text/event-stream",
            )
    except Exception:
        pass

    sse_payload = tools_gateway.sse_answer(await _request_json(request), response_body)   # D6-725

    async def _stream():
        yield sse_payload

    return StreamingResponse(
        _stream(),
        status_code=200,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------

@router.get("/tools", summary="List admin MCP tools")
async def list_admin_tools(request: Request) -> Dict[str, Any]:
    """HTTP GET convenience endpoint for admin tool listing. Honors the same
    ?mode=/?toolsets= visibility params as tools/list and annotates categories."""
    from .tool_categories import get_category

    mode, selected, problems = _resolve_admin_tool_visibility(request)
    if problems:
        return {"error": "; ".join(problems)}
    listed = _admin_tools_listing(mode, selected)
    return {
        "server":       ADMIN_SERVER_INFO["name"],
        "version":      ADMIN_SERVER_INFO["version"],
        "total_tools":  len(ADMIN_TOOL_SCHEMAS),
        "listed_tools": len(listed),
        "mode":         mode,
        "toolsets":     sorted(selected) if selected is not None else None,
        "buckets":      ADMIN_BUCKETS,
        "auth_required": "Admin developer JWT (is_admin=True)",
        "tools":        [dict(t, category=get_category(t.get("name", ""), is_admin=True)) for t in listed],
    }


@router.get("/health", summary="Admin MCP server health check")
async def admin_mcp_health() -> Dict[str, Any]:
    """Returns admin MCP server health status."""
    return {
        "status":          "ok",
        "server":          ADMIN_SERVER_INFO["name"],
        "version":         ADMIN_SERVER_INFO["version"],
        "tools_available": len(ADMIN_TOOL_SCHEMAS),
        "auth_required":   "Admin developer JWT (is_admin=True)",
        "endpoints": {
            "rpc":    "POST /mcp/admin/rpc",
            "sse":    "GET  /mcp/admin/sse",
            "tools":  "GET  /mcp/admin/tools",
            "health": "GET  /mcp/admin/health",
        },
    }
