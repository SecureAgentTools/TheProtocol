"""
TheProtocol MCP Server — FastAPI router implementing MCP JSON-RPC 2.0 protocol.

Transport: Streamable HTTP at /mcp (POST + GET) — MCP spec 2025-03-26
           Raw JSON-RPC 2.0 over HTTP POST at /mcp/rpc (backward compat)
           SSE transport at /mcp/sse (deprecated, backward compat)
           Tool listing at /mcp/tools
           Health check at /mcp/health

MCP Protocol Methods (JSON-RPC 2.0):
    initialize         — Handshake: returns server info + capabilities
    ping               — Keepalive
    tools/list         — List all 14 available tools with schemas
    tools/call         — Execute a named tool with arguments

Auth:
    Passed via Authorization: Bearer <token> HTTP header.
    auth_bridge.py maps the token to an MCPAuthContext.

Mounted in main.py at: app.include_router(mcp_router, prefix="/mcp")
"""
import json
import asyncio
import os
import time
import logging
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from .arguments import argument_problems  # §MCPTEST30 V0524: arguments checked against the inputSchema
from .arguments import ToolArgumentsRefused, refuse_unbindable  # §MCPTEST30 V0545: arguments bound before the call
from .audit import emit_mcp_audit
from .protocol_version import negotiate_protocol_version
from .tool_aliases import resolve_alias  # §AGORAWORDS (V0419)
from .tool_switches import filter_listed, listed as _tool_listed   # W3: the registry's switches decide the listing

from .auth_bridge import (
    authenticate_mcp_token, MCPAuthError, set_mcp_client_ip,
    set_mcp_capability_token, get_mcp_capability_token,
    MCPAuthUnavailable, safe_exception_text, format_tool_exception,   # §MCPTEST30 V0529
)
# 2026-07-14 tool-loading work (L0 buckets + L1 gateway) — see
# STRATEGY_2026-07-14_MCP_TOOL_LOADING.md. Categories/gateway affect LISTING
# only; tier auth + audit below are untouched.
from . import mcp_tasks, prompts, resources, tools_gateway
from .tool_categories import (
    PUBLIC_BUCKETS,
    PUBLIC_CORE_TOOLS,
    bare_name,
    filter_schemas,
    parse_toolsets,
)
from .tool_metadata import decorate_schemas, task_tools
from agentvault_registry.mcp.route_constraints import apply_route_constraints  # §MCPTEST30 (V0548)
from .tool_result import is_failure  # §MCPTEST30: one rule for a failed result
from .tools_discovery import (
    get_org_track_record,
    get_org_public_feed,
    list_transparent_organizations,
    discover_agents,
    get_agent_profile,
    get_network_stats,
    get_governance_proposals,
    get_apy_rates,
    discover_registries,
    # §pass70 Sprint 3 Wave 3
    get_registry_card,
    get_fiat_tiers,
    get_fiat_providers,
    get_fiat_quote,
    get_staking_global_stats,
    get_network_health,
    # §pass70 Sprint 4
    get_federation_info,
    # §pass70 Sprint 5
    get_attestation_signing_pubkey,
    # §pass70 Sprint 6
    get_achievement_catalog,
    get_attestation_health,
    get_circuits,
    get_staking_distributions,
    get_staking_distribution_stats,
    reverify_attestation,
    # §pass70 Sprint 8
    get_system_activity_feed,
    # §pass70 Sprint 9
    get_circuit_acir,
    get_circuit_source,
    get_circuit_nargo_toml,
    get_circuit_verification_key,
    get_circuit_metadata,
    get_pipeline_templates,
    get_agent_by_did,
    get_agent_card_export,
    get_agent_public_key,
    get_teg_price,
    get_teg_reputation_rankings,
    get_agent_locations,
    # §pass70 Sprint 10
    get_fiat_stats_public,
    get_auth_registration_config,
    # §pass70 Sprint 11
    get_agent_flare,
    get_developer_flare,
    get_staking_apy_tiers_teg,
    # §pass70 Sprint 12
    get_federation_health_check,
    get_federation_network_stats,
    list_federation_registries,
    list_federation_agent_cards,
    list_federation_registry_cards,
    get_federation_policy_compliance,
    get_federation_registry_health_profile,
    get_spire_jwks,
    # §pass70 Sprint 17 (Tier 1 — 8 new)
    list_agent_cards,
    get_agent_card_by_hri,
    get_agent_card_by_human_readable_id,
    get_agent_card_by_id,
    get_community_announcements,
    get_downloads_manifest,
    get_stack_health,
    get_activity_feed_by_type,
    # §pass70 Sprint 18 (Tier 1 — 21 new)
    get_agent_locations_operator,
    get_agent_locations_emission_policies,
    get_agent_locations_trusted_registries,
    get_agent_attestations_by_did,
    get_agent_attestation_schedules_by_did,
    get_agent_anp,
    get_agent_did_doc,
    get_public_showcase_agents,
    get_public_event_store_recent,
    get_public_event_store_stats,
    get_well_known_registry_card,
    get_well_known_dev_jwks,
    get_fiat_purchase_session,
    auth_register,
    auth_forgot_password,
    auth_reset_password,
    auth_set_new_password,
    auth_recover_account,
    auth_resend_verification,
    auth_verify_email,
    auth_validate_2fa,
    # §pass70 Sprint 19 (Tier 1)
    get_mcp_stdio_bridge_js,
    get_mcp_stdio_bridge_admin_js,
    get_public_registry_config,
    verify_public_attestation_bundle,
    # §pass70 Sprint 20 (Tier 1)
    get_public_showcase_call,
    auth_recover_2fa,
    list_public_operator_applications,
    get_agent_by_did_alt,
    # §pass70 Sprint 21 (Tier 1 — arena)
    list_arena_matches,
    get_arena_match,
    get_arena_match_bets,
    get_arena_match_map,
    get_arena_leaderboard,
    get_arena_agent_stats,
    create_arena_match,
    DISCOVERY_TOOL_SCHEMAS,
)
from .tools_agent import (
    get_agent_token,
    get_my_balance,
    transfer_tokens,
    smart_send_tool,
    bridge_transfer,
    stake_tokens,
    unstake_tokens,
    cast_vote,
    # §pass70 Sprint 2 Wave 1
    get_my_stakes,
    get_my_voting_power,
    get_my_earnings,
    authorize_payment,
    verify_payment,
    settle_payment,
    release_payment,
    submit_funding_request,
    # §pass70 Sprint 3 Wave 4 (Tier 2)
    get_my_agent_info,
    agent_heartbeat,
    enable_mtls,
    get_my_auto_compound,
    get_my_reward_history,
    # §pass70 Sprint 4 (Tier 2)
    get_my_staking_status,
    get_my_staking_history,
    get_my_agent_health,
    # §pass70 Sprint 5 (Tier 2)
    get_my_stake_stats,
    claim_staking_rewards,
    list_my_attestation_schedules,
    create_attestation_schedule,
    submit_attestation,
    get_my_funding_requests,
    get_my_contracts,
    get_agent_contracts,
    get_my_vote_on_proposal,
    get_my_a2a_payment_tokens,
    # §pass70 Sprint 6 (Tier 2)
    get_my_agent_disputes,
    estimate_my_staking_rewards,
    # §pass70 Sprint 7 (Tier 2)
    agent_revoke_attestation,
    disable_my_attestation_schedule,
    release_payment_by_id,
    approve_contract_completion,
    mark_contract_failed,
    submit_dispute_evidence,
    get_contract_by_id,
    # §pass70 Sprint 8 (Tier 2)
    log_enhanced_dispute,
    get_registry_federation_proposals,
    # §pass70 Sprint 9 (Tier 2)
    get_my_teg_balance,
    get_my_teg_transactions,
    get_my_teg_disputes,
    # §pass70 Sprint 10 (Tier 2 — re-tiered: exportAgent + updateMyAgentLocation moved to dev)
    get_my_reputation_bond_status,
    deposit_reputation_bond,
    unlock_reputation_bond,  # §BATCH0911 item 4
    # §pass70 Sprint 11 (Tier 2)
    get_teg_attestations,
    get_teg_advanced_transactions,
    # §pass70 Sprint 13 (Tier 2 — TEG mutations)
    teg_system_transfer,
    claim_teg_rewards,
    log_teg_dispute,
    cross_teg_balance_sync,
    apply_reputation_signal,
    # §pass70 Sprint 17 (Tier 2)
    get_my_mtls_status,
    disable_my_mtls,
    accept_contract,
    engage_agent_v2,
    # §OURSTATE-1 (2026-08-24) — OurChat chat (dual-auth passthrough)
    chat_list_conversations,
    chat_read_thread,
    chat_send_message,
    chat_respond_request,
    chat_block_principal,
    chat_unblock_principal,
    get_contract_v2_mcp,
    submit_contract_milestone,
    release_contract_milestone,
    instantiate_contract_template,
    submit_contract_work,
    create_malpractice_dispute,
    federation_vote_proposal,
    tally_proposal,
    submit_teg_attestation,
    # §pass70 Sprint 18 (Tier 2 — tokenomics)
    get_tokenomics_treasury,
    get_tokenomics_rewards,
    get_tokenomics_transactions,
    # §pass70 Sprint 19 (Tier 2)
    get_revoked_identities,
    cross_registry_contract_proxy,
    accept_contract_federated,
    submit_contract_work_federated,
    relay_action,
    get_relay_status,
    get_my_enforcement_status,
    teg_stake_direct,
    teg_unstake_direct,
    teg_cross_registry_transfer_direct,
    # §pass70 Sprint 20 (Tier 2)
    submit_onboard_register,
    teg_reputation_signal_token,
    federation_sync_request,
    AGENT_TOOL_SCHEMAS,
)
from .tools_developer import (
    get_my_agents,
    create_agent,
    submit_dispute,
    create_proposal,
    # §pass70 Sprint 2 Wave 2
    get_my_developer_profile,
    get_my_api_keys,
    create_api_key,
    get_my_organizations,
    get_my_agent_bundles,
    # §pass70 Sprint 3 Wave 4 (Tier 3)
    submit_support_ticket,
    get_my_support_tickets,
    revoke_api_key,
    get_my_disputes,
    # §pass70 Sprint 4 (Tier 3)
    get_my_webhooks,
    create_webhook,
    get_webhook,
    update_webhook,
    delete_webhook,
    get_webhook_deliveries,
    test_webhook,
    get_supported_webhook_events,
    get_developer_stats,
    get_my_cicd_pipelines,
    get_my_cicd_versions,
    get_my_cicd_deployments,
    # §pass70 Sprint 5 (Tier 3)
    get_my_mcp_audit_log,
    get_my_deletion_status,
    get_my_achievements,
    get_my_unread_notifications,
    mark_notification_read,
    get_organization,
    list_organization_members,
    get_featured_bundles,
    # §pass70 Sprint 6 (Tier 3)
    list_my_attestations,
    get_attestation_detail,
    get_attestation_bundle,
    get_trust_score,
    get_volume_profile,
    get_cross_frame_reputation,
    get_reputation_computation_status,
    # §pass70 Sprint 7 (Tier 3)
    create_organization,
    update_organization,
    delete_organization,
    invite_organization_member,
    list_organization_teams,
    create_organization_team,
    get_organization_team,
    add_team_member,
    assign_agent_to_org,
    get_organization_by_slug,
    get_dispute_by_id,
    # §pass70 Sprint 8 (Tier 3)
    get_fee_current_rate,
    # §pass70 Sprint 9 (Tier 3)
    get_my_agent_cicd_stats,
    get_my_agent_logs,
    list_agent_templates,
    get_agent_template,
    get_my_developer_activity,
    get_my_developer_teg_summary,
    get_my_treasury_balance,
    get_my_notification_prefs,
    get_notification_catalog,
    get_my_notification_matrix,
    update_notification_prefs,
    get_my_signing_keys,
    get_my_flare_status,
    get_my_fiat_purchases,
    get_my_2fa_status,
    # §pass70 Sprint 10 (Tier 3 — CI/CD mutations + re-tiered from Tier 2)
    create_pipeline,
    update_pipeline,
    delete_pipeline,
    create_version,
    delete_version,
    activate_version,
    rollback_version,
    trigger_deployment,
    get_deployment,
    append_deployment_logs,
    update_deployment_status,
    clone_agent,
    delete_my_agent,
    export_agent_dev,
    update_my_developer_location,
    # §pass70 Sprint 11 (Tier 3)
    get_transactions_analytics,
    get_agent_rewards_history,
    get_agent_pending_rewards,
    get_agent_staking_balance,
    get_agent_staking_history,
    list_teg_policies,
    get_teg_policies_compliance_dashboard,
    # §pass70 Sprint 12 (Tier 3)
    list_federation_peers,
    get_my_federation_registrations,
    trigger_federation_sync,
    get_federation_sync_status_dev,
    rotate_federation_license_self,
    logout_session,
    get_auth_profile,
    setup_2fa,
    verify_2fa,
    disable_2fa_self,
    change_password,
    get_bundle_manifest,
    rate_bundle,
    report_bundle,
    fork_bundle,
    delete_bundle,
    # §pass70 Sprint 13 (Tier 3 — TEG + federation peer + frame inv)
    get_teg_transaction_detail,
    get_agent_transaction_history,
    export_teg_transactions,
    create_teg_policy,
    update_teg_policy,
    delete_teg_policy,
    get_teg_policy,
    resolve_teg_dispute,
    get_teg_dispute_detail,
    get_agent_reputation,
    create_frame_invitation,
    finalize_frame_invitation,
    # §pass70 Sprint 14 (Tier 3 — federation slash + peer mgmt + onboard + utils)
    validate_agent_card,
    download_bundle_via_onboard,
    reset_agent_credentials_onboard,
    get_federation_dispute_settlements,
    get_federation_dispute_settlement,
    approve_dispute_settlement,
    reject_dispute_settlement,
    get_peer_slash_config,
    update_peer_slash_config,
    get_federation_peer_by_id,
    update_federation_peer,
    delete_federation_peer_self,
    create_federation_peer,
    federation_slash_request,
    federation_slash_confirmation,
    # §pass70 Sprint 15 (Tier 3 — flare mgmt + attestation admin previews)
    set_flare_corner_variant,
    set_flare_overlay,
    set_flare_variant,
    flare_celebration_acknowledge,
    customize_flare,
    equip_flare,
    move_flare,
    select_flare,
    unequip_flare,
    preview_slash_reduction_attestation,
    preview_voting_power_attestation,
    mcp_passthrough_get_agent_profile,
    # §pass70 Sprint 16 (Tier 3)
    get_staking_distribution_records,
    update_auto_compound,
    trigger_manual_distribution,
    download_bundle,
    restore_bundle,
    restore_from_upload,
    patch_bundle,
    create_bundle,
    preview_admin_email_with_context,
    preview_admin_email_text,
    # §pass70 Sprint 17 (Tier 3)
    rotate_my_signing_key,
    get_my_api_key_detail,
    delete_my_api_key,
    get_batch_agent_balances,
    get_my_agent_balance,
    delete_my_agent_by_dev,
    get_operator_my_status,
    get_operator_my_bundle,
    get_operator_my_lifecycle,
    activate_operator,
    request_frame,
    self_provision_operator,
    # §pass70 Sprint 18 (Tier 3)
    import_agent,
    validate_agent_import,
    agent_bulk_export,
    auth_refresh,
    regenerate_backup_codes,
    operator_portal_self_logs,
    operator_portal_self_restart,
    # §pass70 Sprint 19 (Tier 3)
    get_my_developer_jwks,
    get_oauth_federation_status,
    oauth_introspect,
    oauth_revoke,
    oauth_federation_trust_list,
    oauth_token_exchange,
    accept_org_invitation,
    get_support_ticket_detail,
    reply_support_ticket,
    request_self_revocation,
    # §pass70 Sprint 20 (Tier 3)
    get_my_developer_activity_eventstore,
    list_developer_apikeys_me,
    create_developer_apikey_me,
    list_developer_webhooks,
    get_proposal_detail,
    get_proposal_votes,
    get_auto_tally_config,
    federation_propose_raise,
    federation_veto_proposal,
    get_dev_trust_graph,
    get_agent_metrics,
    agent_builder_generate,
    # §pass70 Sprint 21 (Tier 3)
    list_agent_builder_templates,
    agent_builder_generate_template,
    update_my_developer_profile,
    list_developer_webhooks_alt,
    get_developer_webhook_deliveries_alt,
    test_developer_webhook_alt,
    download_pipeline_template,
    purchase_pipeline_template,
    create_teg_policies_batch,
    request_account_deletion,
    cancel_account_deletion,
    claim_pending_achievements,
    record_achievement,
    list_organization_agents,
    get_support_review_state,
    grant_support_review,
    revoke_support_review,
    list_organization_invitations,
    withdraw_organization_invitation,
    get_organization_cicd_summary,
    remove_organization_member,
    update_organization_team,
    delete_organization_team,
    remove_team_member,
    unassign_agent_from_org,
    get_auto_compound_for_agent,
    DEVELOPER_TOOL_SCHEMAS,
)
from ..database import get_db_context

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

router = APIRouter(tags=["MCP Server"])

# ---------------------------------------------------------------------------
# MCP Server Info
# ---------------------------------------------------------------------------

MCP_SERVER_INFO = {
    "name": "TheProtocol",
    "version": "1.0.0",
    "description": (
        "Sovereign AI agent registry: DID-based agent identity, discovery, payments in the "
        "frame's own units, contracts, the Guild work exchange and governance."
    ),
    # 2026-07-14 reference-grade pass: full 2025-11-25 surface. listChanged is
    # true because L2 dynamic toolsets (enableToolset/disableToolset) mutate
    # the session's listing server-side; tasks is the experimental async-task
    # capability (mcp_tasks.py); completions serves prompt-argument vocab.
    "capabilities": {
        "tools": {"listChanged": True},
        "resources": {"subscribe": False, "listChanged": False},
        "prompts": {"listChanged": False},
        "completions": {},
        "tasks": mcp_tasks.TASKS_CAPABILITY,
    },
    "protocolVersion": "2025-11-25",
    "icons": [
        {"src": "https://registry.theprotocol.cloud/pwa-512.png",
         "mimeType": "image/png", "sizes": ["512x512"]},
    ],
}

ALL_TOOL_SCHEMAS: List[Dict[str, Any]] = (
    DISCOVERY_TOOL_SCHEMAS + AGENT_TOOL_SCHEMAS + DEVELOPER_TOOL_SCHEMAS
)

# ---------------------------------------------------------------------------
# Tool dispatch table
# ---------------------------------------------------------------------------

# Mapping from MCP tool name → callable
# Tier 1 tools are called directly (no auth context needed)
# Tier 2/3 tools receive auth context as first positional arg

TOOL_DISPATCH: Dict[str, Any] = {
    # Tier 0 — no auth (auth utility)
    "theprotocol_getAgentToken": get_agent_token,
    # Tier 1 — no auth
    "theprotocol_discoverRegistries": discover_registries,
    "theprotocol_discoverAgents": discover_agents,
    "theprotocol_getAgentProfile": get_agent_profile,
    "theprotocol_getNetworkStats": get_network_stats,
    "theprotocol_getLockPayoutTiers": get_apy_rates,
    "theprotocol_getGovernanceProposals": get_governance_proposals,  # §pass70: dropped Tier 3 gate; HTTP endpoint is public
    # Tier 2 — agent auth
    "theprotocol_getMyBalance": get_my_balance,
    "theprotocol_transferUnits": transfer_tokens,
    "theprotocol_smartSend": smart_send_tool,
    "theprotocol_lockUnits": stake_tokens,
    "theprotocol_unlockUnits": unstake_tokens,
    "theprotocol_castVote": cast_vote,
    "theprotocol_bridgeTransfer": bridge_transfer,
    # Tier 3 — developer auth
    "theprotocol_getMyAgents": get_my_agents,
    "theprotocol_createAgent": create_agent,
    "theprotocol_submitDispute": submit_dispute,
    "theprotocol_createProposal": create_proposal,
    # ─── §pass70 Sprint 2 Wave 1 (Tier 2 agent) ───────────────────────────
    "theprotocol_getMyLocks": get_my_stakes,
    "theprotocol_getMyVotingPower": get_my_voting_power,
    "theprotocol_getMyIncome": get_my_earnings,
    "theprotocol_authorizePayment": authorize_payment,
    "theprotocol_verifyPayment": verify_payment,
    "theprotocol_settlePayment": settle_payment,
    "theprotocol_releasePayment": release_payment,
    "theprotocol_submitFundingRequest": submit_funding_request,
    # ─── §pass70 Sprint 2 Wave 2 (Tier 3 developer) ───────────────────────
    "theprotocol_getMyDeveloperProfile": get_my_developer_profile,
    "theprotocol_getMyApiKeys": get_my_api_keys,
    "theprotocol_createApiKey": create_api_key,
    "theprotocol_getMyOrganizations": get_my_organizations,
    "theprotocol_getMyAgentBundles": get_my_agent_bundles,
    # ─── §pass70 Sprint 3 Wave 3 (Tier 1 public) ──────────────────────────
    "theprotocol_getRegistryCard": get_registry_card,
    "theprotocol_getFiatTiers": get_fiat_tiers,
    "theprotocol_getFiatProviders": get_fiat_providers,
    "theprotocol_getFiatQuote": get_fiat_quote,
    "theprotocol_getLockStats": get_staking_global_stats,
    "theprotocol_getNetworkHealth": get_network_health,
    # ─── §pass70 Sprint 3 Wave 4 (Tier 2 agent) ───────────────────────────
    "theprotocol_getMyAgentInfo": get_my_agent_info,
    "theprotocol_agentHeartbeat": agent_heartbeat,
    "theprotocol_enableMtls": enable_mtls,
    "theprotocol_getMyPayoutRelock": get_my_auto_compound,
    "theprotocol_getMyPayoutHistory": get_my_reward_history,
    # ─── §pass70 Sprint 3 Wave 4 (Tier 3 developer) ───────────────────────
    "theprotocol_submitSupportTicket": submit_support_ticket,
    "theprotocol_getMySupportTickets": get_my_support_tickets,
    "theprotocol_revokeApiKey": revoke_api_key,
    "theprotocol_getMyDisputes": get_my_disputes,
    # ─── §pass70 Sprint 4 ─────────────────────────────────────────────────
    "theprotocol_getFederationInfo": get_federation_info,
    "theprotocol_getMyLockStatus": get_my_staking_status,
    "theprotocol_getMyLockHistory": get_my_staking_history,
    "theprotocol_getMyAgentHealth": get_my_agent_health,
    "theprotocol_getMyWebhooks": get_my_webhooks,
    "theprotocol_createWebhook": create_webhook,
    "theprotocol_getWebhook": get_webhook,
    "theprotocol_updateWebhook": update_webhook,
    "theprotocol_deleteWebhook": delete_webhook,
    "theprotocol_getWebhookDeliveries": get_webhook_deliveries,
    "theprotocol_testWebhook": test_webhook,
    "theprotocol_getSupportedWebhookEvents": get_supported_webhook_events,
    "theprotocol_getDeveloperStats": get_developer_stats,
    "theprotocol_getMyCicdPipelines": get_my_cicd_pipelines,
    "theprotocol_getMyCicdVersions": get_my_cicd_versions,
    "theprotocol_getMyCicdDeployments": get_my_cicd_deployments,
    # ─── §pass70 Sprint 5 (Tier 1 public) ─────────────────────────────────
    "theprotocol_getAttestationSigningPubkey": get_attestation_signing_pubkey,
    # ─── §pass70 Sprint 5 (Tier 2 agent) ──────────────────────────────────
    "theprotocol_getMyLockStats": get_my_stake_stats,
    "theprotocol_claimLockPayouts": claim_staking_rewards,
    "theprotocol_listMyAttestationSchedules": list_my_attestation_schedules,
    "theprotocol_createAttestationSchedule": create_attestation_schedule,
    "theprotocol_submitAttestation": submit_attestation,
    "theprotocol_getMyFundingRequests": get_my_funding_requests,
    "theprotocol_getMyContracts": get_my_contracts,
    "theprotocol_getAgentContracts": get_agent_contracts,
    "theprotocol_getMyVoteOnProposal": get_my_vote_on_proposal,
    "theprotocol_getMyPaymentAuthorizations": get_my_a2a_payment_tokens,
    # ─── §pass70 Sprint 5 (Tier 3 dev) ────────────────────────────────────
    "theprotocol_getMyMcpAuditLog": get_my_mcp_audit_log,
    "theprotocol_getMyDeletionStatus": get_my_deletion_status,
    "theprotocol_getMyAchievements": get_my_achievements,
    "theprotocol_getMyUnreadNotifications": get_my_unread_notifications,
    "theprotocol_markNotificationRead": mark_notification_read,
    "theprotocol_getOrganization": get_organization,
    "theprotocol_listOrganizationMembers": list_organization_members,
    "theprotocol_getFeaturedBundles": get_featured_bundles,
    # ─── §pass70 Sprint 6 (Tier 1 public) ─────────────────────────────────
    "theprotocol_getAchievementCatalog": get_achievement_catalog,
    "theprotocol_getAttestationHealth": get_attestation_health,
    "theprotocol_getCircuits": get_circuits,
    "theprotocol_getLockPayoutRuns": get_staking_distributions,
    "theprotocol_getLockPayoutStats": get_staking_distribution_stats,
    "theprotocol_reverifyAttestation": reverify_attestation,
    # ─── §pass70 Sprint 6 (Tier 2 agent) ──────────────────────────────────
    "theprotocol_getMyAgentDisputes": get_my_agent_disputes,
    "theprotocol_estimateMyLockPayouts": estimate_my_staking_rewards,
    # ─── §pass70 Sprint 6 (Tier 3 dev) ────────────────────────────────────
    "theprotocol_listMyAttestations": list_my_attestations,
    "theprotocol_getAttestationDetail": get_attestation_detail,
    "theprotocol_getAttestationBundle": get_attestation_bundle,
    "theprotocol_getTrustScore": get_trust_score,
    "theprotocol_getVolumeProfile": get_volume_profile,
    "theprotocol_getCrossFrameReputation": get_cross_frame_reputation,
    "theprotocol_getReputationComputationStatus": get_reputation_computation_status,
    # ─── §pass70 Sprint 7 (Tier 2 agent) ──────────────────────────────────
    "theprotocol_agentRevokeAttestation": agent_revoke_attestation,
    "theprotocol_disableMyAttestationSchedule": disable_my_attestation_schedule,
    "theprotocol_releasePaymentById": release_payment_by_id,
    "theprotocol_approveContractCompletion": approve_contract_completion,
    "theprotocol_markContractFailed": mark_contract_failed,
    "theprotocol_submitDisputeEvidence": submit_dispute_evidence,
    "theprotocol_getContractById": get_contract_by_id,
    # ─── §pass70 Sprint 7 (Tier 3 dev) ────────────────────────────────────
    "theprotocol_createOrganization": create_organization,
    "theprotocol_updateOrganization": update_organization,
    "theprotocol_deleteOrganization": delete_organization,
    "theprotocol_inviteOrganizationMember": invite_organization_member,
    "theprotocol_listOrganizationTeams": list_organization_teams,
    "theprotocol_createOrganizationTeam": create_organization_team,
    "theprotocol_getOrganizationTeam": get_organization_team,
    "theprotocol_addTeamMember": add_team_member,
    "theprotocol_assignAgentToOrg": assign_agent_to_org,
    "theprotocol_getOrganizationBySlug": get_organization_by_slug,
    "theprotocol_getDisputeById": get_dispute_by_id,
    # ─── §pass70 Sprint 8 (Tier 1 public) ─────────────────────────────────
    "theprotocol_getSystemActivityFeed": get_system_activity_feed,
    # ─── §pass70 Sprint 8 (Tier 2 agent) ──────────────────────────────────
    "theprotocol_logEnhancedDispute": log_enhanced_dispute,
    "theprotocol_getRegistryFederationProposals": get_registry_federation_proposals,
    # ─── §pass70 Sprint 8 (Tier 3 dev) ────────────────────────────────────
    "theprotocol_getFeeCurrentRate": get_fee_current_rate,
    "theprotocol_requestAccountDeletion": request_account_deletion,
    "theprotocol_cancelAccountDeletion": cancel_account_deletion,
    "theprotocol_claimPendingAchievements": claim_pending_achievements,
    "theprotocol_recordAchievement": record_achievement,
    "theprotocol_listOrganizationAgents": list_organization_agents,
    "theprotocol_getSupportReviewState": get_support_review_state,
    "theprotocol_grantSupportReview": grant_support_review,
    "theprotocol_revokeSupportReview": revoke_support_review,
    "theprotocol_listOrganizationInvitations": list_organization_invitations,
    "theprotocol_withdrawOrganizationInvitation": withdraw_organization_invitation,
    "theprotocol_getOrgTrackRecord": get_org_track_record,
    "theprotocol_getOrgPublicFeed": get_org_public_feed,
    "theprotocol_listTransparentOrganizations": list_transparent_organizations,
    "theprotocol_getOrganizationCicdSummary": get_organization_cicd_summary,
    "theprotocol_removeOrganizationMember": remove_organization_member,
    "theprotocol_updateOrganizationTeam": update_organization_team,
    "theprotocol_deleteOrganizationTeam": delete_organization_team,
    "theprotocol_removeTeamMember": remove_team_member,
    "theprotocol_unassignAgentFromOrg": unassign_agent_from_org,
    "theprotocol_getPayoutRelockForAgent": get_auto_compound_for_agent,
    # ─── §pass70 Sprint 9 (Tier 1 public — 10 new) ────────────────────────
    "theprotocol_getCircuitACIR": get_circuit_acir,
    "theprotocol_getCircuitSource": get_circuit_source,
    "theprotocol_getCircuitNargoToml": get_circuit_nargo_toml,
    "theprotocol_getCircuitVerificationKey": get_circuit_verification_key,
    "theprotocol_getCircuitMetadata": get_circuit_metadata,
    "theprotocol_getPipelineTemplates": get_pipeline_templates,
    "theprotocol_getAgentByDID": get_agent_by_did,
    "theprotocol_getAgentCardExport": get_agent_card_export,
    "theprotocol_getAgentPublicKey": get_agent_public_key,
    "theprotocol_getTegPrice": get_teg_price,
    "theprotocol_getTegReputationRankings": get_teg_reputation_rankings,
    "theprotocol_getAgentLocations": get_agent_locations,
    # ─── §pass70 Sprint 9 (Tier 2 agent — 3 new) ──────────────────────────
    "theprotocol_getMyTegBalance": get_my_teg_balance,
    "theprotocol_getMyTegTransactions": get_my_teg_transactions,
    "theprotocol_getMyTegDisputes": get_my_teg_disputes,
    # ─── §pass70 Sprint 9 (Tier 3 dev — 12 new) ───────────────────────────
    "theprotocol_getMyAgentCicdStats": get_my_agent_cicd_stats,
    "theprotocol_getMyAgentLogs": get_my_agent_logs,
    "theprotocol_listAgentTemplates": list_agent_templates,
    "theprotocol_getAgentTemplate": get_agent_template,
    "theprotocol_getMyDeveloperActivity": get_my_developer_activity,
    "theprotocol_getMyDeveloperTegSummary": get_my_developer_teg_summary,
    "theprotocol_getMyTreasuryBalance": get_my_treasury_balance,
    "theprotocol_getMyNotificationPrefs": get_my_notification_prefs,
    "theprotocol_getNotificationCatalog": get_notification_catalog,
    "theprotocol_getMyNotificationMatrix": get_my_notification_matrix,
    "theprotocol_updateNotificationPrefs": update_notification_prefs,
    "theprotocol_getMySigningKeys": get_my_signing_keys,
    "theprotocol_getMyFlareStatus": get_my_flare_status,
    "theprotocol_getMyFiatPurchases": get_my_fiat_purchases,
    "theprotocol_getMy2FAStatus": get_my_2fa_status,
    # ─── §pass70 Sprint 10 (Tier 1 — 2 new) ───────────────────────────────
    "theprotocol_getFiatStatsPublic": get_fiat_stats_public,
    "theprotocol_getAuthRegistrationConfig": get_auth_registration_config,
    # ─── §pass70 Sprint 10 (Tier 2 — 2 new) ───────────────────────────────
    "theprotocol_getMyReputationBondStatus": get_my_reputation_bond_status,
    "theprotocol_depositReputationBond": deposit_reputation_bond,
    "theprotocol_unlockReputationBond": unlock_reputation_bond,  # §BATCH0911 item 4
    # ─── §pass70 Sprint 10 (Tier 3 — 13 new: CI/CD mutations) ─────────────
    "theprotocol_createPipeline": create_pipeline,
    "theprotocol_updatePipeline": update_pipeline,
    "theprotocol_deletePipeline": delete_pipeline,
    "theprotocol_createVersion": create_version,
    "theprotocol_deleteVersion": delete_version,
    "theprotocol_activateVersion": activate_version,
    "theprotocol_rollbackVersion": rollback_version,
    "theprotocol_triggerDeployment": trigger_deployment,
    "theprotocol_getDeployment": get_deployment,
    "theprotocol_appendDeploymentLogs": append_deployment_logs,
    "theprotocol_updateDeploymentStatus": update_deployment_status,
    "theprotocol_cloneAgent": clone_agent,
    "theprotocol_deleteMyAgent": delete_my_agent,
    "theprotocol_exportAgentDev": export_agent_dev,
    "theprotocol_updateMyDeveloperLocation": update_my_developer_location,
    # ─── §pass70 Sprint 11 (Tier 1 — 3 new) ───────────────────────────────
    "theprotocol_getAgentFlare": get_agent_flare,
    "theprotocol_getDeveloperFlare": get_developer_flare,
    "theprotocol_getLockPayoutTiersTeg": get_staking_apy_tiers_teg,
    # ─── §pass70 Sprint 11 (Tier 2 — 2 new) ───────────────────────────────
    "theprotocol_getTegAttestations": get_teg_attestations,
    "theprotocol_getTegAdvancedTransactions": get_teg_advanced_transactions,
    # ─── §pass70 Sprint 11 (Tier 3 — 7 new) ───────────────────────────────
    "theprotocol_getTransactionsAnalytics": get_transactions_analytics,
    "theprotocol_getAgentPayoutHistory": get_agent_rewards_history,
    "theprotocol_getAgentPendingPayouts": get_agent_pending_rewards,
    "theprotocol_getAgentLockedBalance": get_agent_staking_balance,
    "theprotocol_getAgentLockHistory": get_agent_staking_history,
    "theprotocol_listTegPolicies": list_teg_policies,
    "theprotocol_getTegPoliciesComplianceDashboard": get_teg_policies_compliance_dashboard,
    # ─── §pass70 Sprint 12 (Tier 1 — 8 new) ───────────────────────────────
    "theprotocol_getFederationHealthCheck": get_federation_health_check,
    "theprotocol_getFederationNetworkStats": get_federation_network_stats,
    "theprotocol_listFederationRegistries": list_federation_registries,
    "theprotocol_listFederationAgentCards": list_federation_agent_cards,
    "theprotocol_listFederationRegistryCards": list_federation_registry_cards,
    "theprotocol_getFederationPolicyCompliance": get_federation_policy_compliance,
    "theprotocol_getFederationRegistryHealthProfile": get_federation_registry_health_profile,
    "theprotocol_getSpireJWKS": get_spire_jwks,
    # ─── §pass70 Sprint 12 (Tier 3 — 16 new) ──────────────────────────────
    "theprotocol_listFederationPeers": list_federation_peers,
    "theprotocol_getMyFederationRegistrations": get_my_federation_registrations,
    "theprotocol_triggerFederationSync": trigger_federation_sync,
    "theprotocol_getFederationSyncStatusDev": get_federation_sync_status_dev,
    "theprotocol_rotateFederationLicenseSelf": rotate_federation_license_self,
    "theprotocol_logoutSession": logout_session,
    "theprotocol_getAuthProfile": get_auth_profile,
    "theprotocol_setup2FA": setup_2fa,
    "theprotocol_verify2FA": verify_2fa,
    "theprotocol_disable2FASelf": disable_2fa_self,
    "theprotocol_changePassword": change_password,
    "theprotocol_getBundleManifest": get_bundle_manifest,
    "theprotocol_rateBundle": rate_bundle,
    "theprotocol_reportBundle": report_bundle,
    "theprotocol_forkBundle": fork_bundle,
    "theprotocol_deleteBundle": delete_bundle,
    # ─── §pass70 Sprint 13 (Tier 2 — 5 new: TEG mutations) ────────────────
    "theprotocol_tegSystemTransfer": teg_system_transfer,
    "theprotocol_claimTegPayouts": claim_teg_rewards,
    "theprotocol_logTegDispute": log_teg_dispute,
    "theprotocol_crossTegBalanceSync": cross_teg_balance_sync,
    "theprotocol_applyReputationSignal": apply_reputation_signal,
    # ─── §pass70 Sprint 13 (Tier 3 — 12 new) ──────────────────────────────
    "theprotocol_getTegTransactionDetail": get_teg_transaction_detail,
    "theprotocol_getAgentTransactionHistory": get_agent_transaction_history,
    "theprotocol_exportTegTransactions": export_teg_transactions,
    "theprotocol_createTegPolicy": create_teg_policy,
    "theprotocol_updateTegPolicy": update_teg_policy,
    "theprotocol_deleteTegPolicy": delete_teg_policy,
    "theprotocol_getTegPolicy": get_teg_policy,
    "theprotocol_resolveTegDispute": resolve_teg_dispute,
    "theprotocol_getTegDisputeDetail": get_teg_dispute_detail,
    "theprotocol_getAgentReputation": get_agent_reputation,
    "theprotocol_createFrameInvitation": create_frame_invitation,
    "theprotocol_finalizeFrameInvitation": finalize_frame_invitation,
    # ─── §pass70 Sprint 14 (Tier 3 — 15 new) ──────────────────────────────
    "theprotocol_validateAgentCard": validate_agent_card,
    "theprotocol_downloadBundleViaOnboard": download_bundle_via_onboard,
    "theprotocol_resetAgentCredentialsOnboard": reset_agent_credentials_onboard,
    "theprotocol_getFederationDisputeSettlements": get_federation_dispute_settlements,
    "theprotocol_getFederationDisputeSettlement": get_federation_dispute_settlement,
    "theprotocol_approveDisputeSettlement": approve_dispute_settlement,
    "theprotocol_rejectDisputeSettlement": reject_dispute_settlement,
    "theprotocol_getPeerSlashConfig": get_peer_slash_config,
    "theprotocol_updatePeerSlashConfig": update_peer_slash_config,
    "theprotocol_getFederationPeerByID": get_federation_peer_by_id,
    "theprotocol_updateFederationPeer": update_federation_peer,
    "theprotocol_deleteFederationPeerSelf": delete_federation_peer_self,
    "theprotocol_createFederationPeer": create_federation_peer,
    "theprotocol_federationSlashRequest": federation_slash_request,
    "theprotocol_federationSlashConfirmation": federation_slash_confirmation,
    # ─── §pass70 Sprint 15 (Tier 3 — 12 new) ──────────────────────────────
    "theprotocol_setFlareCornerVariant": set_flare_corner_variant,
    "theprotocol_setFlareOverlay": set_flare_overlay,
    "theprotocol_setFlareVariant": set_flare_variant,
    "theprotocol_flareCelebrationAcknowledge": flare_celebration_acknowledge,
    "theprotocol_customizeFlare": customize_flare,
    "theprotocol_equipFlare": equip_flare,
    "theprotocol_moveFlare": move_flare,
    "theprotocol_selectFlare": select_flare,
    "theprotocol_unequipFlare": unequip_flare,
    "theprotocol_previewSlashReductionAttestation": preview_slash_reduction_attestation,
    "theprotocol_previewVotingPowerAttestation": preview_voting_power_attestation,
    "theprotocol_mcpPassthroughGetAgentProfile": mcp_passthrough_get_agent_profile,
    # ─── §pass70 Sprint 16 (Tier 3 — 10 new) ──────────────────────────────
    "theprotocol_getLockPayoutRecords": get_staking_distribution_records,
    "theprotocol_updatePayoutRelock": update_auto_compound,
    "theprotocol_triggerLockPayoutRun": trigger_manual_distribution,
    "theprotocol_downloadBundle": download_bundle,
    "theprotocol_restoreBundle": restore_bundle,
    "theprotocol_restoreFromUpload": restore_from_upload,
    "theprotocol_patchBundle": patch_bundle,
    "theprotocol_createBundle": create_bundle,
    "theprotocol_previewAdminEmailWithContext": preview_admin_email_with_context,
    "theprotocol_previewAdminEmailText": preview_admin_email_text,
    # ─── §pass70 Sprint 17 (Tier 1 — 8 new) ───────────────────────────────
    "theprotocol_listAgentCards": list_agent_cards,
    "theprotocol_getAgentCardByHRI": get_agent_card_by_hri,
    "theprotocol_getAgentCardByHumanReadableId": get_agent_card_by_human_readable_id,
    "theprotocol_getAgentCardById": get_agent_card_by_id,
    "theprotocol_getCommunityAnnouncements": get_community_announcements,
    "theprotocol_getDownloadsManifest": get_downloads_manifest,
    "theprotocol_getStackHealth": get_stack_health,
    "theprotocol_getActivityFeedByType": get_activity_feed_by_type,
    # ─── §pass70 Sprint 17 (Tier 2 — 8 new) ───────────────────────────────
    "theprotocol_getMyMtlsStatus": get_my_mtls_status,
    "theprotocol_disableMyMtls": disable_my_mtls,
    "theprotocol_acceptContract": accept_contract,
    "theprotocol_engageAgent": engage_agent_v2,
    # §OURSTATE-1 — OurChat chat (dual-auth: dev key or agent JWT both work)
    "theprotocol_listConversations": chat_list_conversations,
    "theprotocol_readThread": chat_read_thread,
    "theprotocol_sendChatMessage": chat_send_message,
    "theprotocol_respondChatRequest": chat_respond_request,
    "theprotocol_blockChatPrincipal": chat_block_principal,
    "theprotocol_unblockChatPrincipal": chat_unblock_principal,
    "theprotocol_getContractV2": get_contract_v2_mcp,
    "theprotocol_submitContractMilestone": submit_contract_milestone,
    "theprotocol_releaseContractMilestone": release_contract_milestone,
    "theprotocol_instantiateContractTemplate": instantiate_contract_template,
    "theprotocol_submitContractWork": submit_contract_work,
    "theprotocol_createMalpracticeDispute": create_malpractice_dispute,
    "theprotocol_federationVoteProposal": federation_vote_proposal,
    "theprotocol_tallyProposal": tally_proposal,
    "theprotocol_submitTegAttestation": submit_teg_attestation,
    # ─── §pass70 Sprint 17 (Tier 3 — 12 new) ──────────────────────────────
    "theprotocol_rotateMySigningKey": rotate_my_signing_key,
    "theprotocol_getMyApiKeyDetail": get_my_api_key_detail,
    "theprotocol_deleteMyApiKey": delete_my_api_key,
    "theprotocol_getBatchAgentBalances": get_batch_agent_balances,
    "theprotocol_getMyAgentBalance": get_my_agent_balance,
    "theprotocol_deleteMyAgentByDev": delete_my_agent_by_dev,
    "theprotocol_getOperatorMyStatus": get_operator_my_status,
    "theprotocol_getOperatorMyBundle": get_operator_my_bundle,
    "theprotocol_getOperatorMyLifecycle": get_operator_my_lifecycle,
    "theprotocol_activateOperator": activate_operator,
    "theprotocol_requestFrame": request_frame,
    "theprotocol_selfProvisionOperator": self_provision_operator,
    # ─── §pass70 Sprint 18 (Tier 1 — 21 new) ──────────────────────────────
    "theprotocol_getAgentLocationsOperator": get_agent_locations_operator,
    "theprotocol_getAgentLocationsEmissionPolicies": get_agent_locations_emission_policies,
    "theprotocol_getAgentLocationsTrustedRegistries": get_agent_locations_trusted_registries,
    "theprotocol_getAgentAttestationsByDID": get_agent_attestations_by_did,
    "theprotocol_getAgentAttestationSchedulesByDID": get_agent_attestation_schedules_by_did,
    "theprotocol_getAgentANP": get_agent_anp,
    "theprotocol_getAgentDIDDoc": get_agent_did_doc,
    "theprotocol_getPublicShowcaseAgents": get_public_showcase_agents,
    "theprotocol_getPublicEventStoreRecent": get_public_event_store_recent,
    "theprotocol_getPublicEventStoreStats": get_public_event_store_stats,
    "theprotocol_getWellKnownRegistryCard": get_well_known_registry_card,
    "theprotocol_getWellKnownDevJwks": get_well_known_dev_jwks,
    "theprotocol_getFiatPurchaseSession": get_fiat_purchase_session,
    "theprotocol_authRegister": auth_register,
    "theprotocol_authForgotPassword": auth_forgot_password,
    "theprotocol_authResetPassword": auth_reset_password,
    "theprotocol_authSetNewPassword": auth_set_new_password,
    "theprotocol_authRecoverAccount": auth_recover_account,
    "theprotocol_authResendVerification": auth_resend_verification,
    "theprotocol_authVerifyEmail": auth_verify_email,
    "theprotocol_authValidate2FA": auth_validate_2fa,
    # ─── §pass70 Sprint 18 (Tier 2 — 3 new: tokenomics) ───────────────────
    "theprotocol_getRegistryTreasury": get_tokenomics_treasury,
    "theprotocol_getUnitPayouts": get_tokenomics_rewards,
    "theprotocol_getUnitTransactions": get_tokenomics_transactions,
    # ─── §pass70 Sprint 18 (Tier 3 — 7 new) ───────────────────────────────
    "theprotocol_importAgent": import_agent,
    "theprotocol_validateAgentImport": validate_agent_import,
    "theprotocol_agentBulkExport": agent_bulk_export,
    "theprotocol_authRefresh": auth_refresh,
    "theprotocol_regenerateBackupCodes": regenerate_backup_codes,
    "theprotocol_operatorPortalSelfLogs": operator_portal_self_logs,
    "theprotocol_operatorPortalSelfRestart": operator_portal_self_restart,
    # ─── §pass70 Sprint 19 (Tier 1 — 4 new) ───────────────────────────────
    "theprotocol_getMcpStdioBridgeJs": get_mcp_stdio_bridge_js,
    "theprotocol_getMcpStdioBridgeAdminJs": get_mcp_stdio_bridge_admin_js,
    "theprotocol_getPublicRegistryConfig": get_public_registry_config,
    "theprotocol_verifyPublicAttestationBundle": verify_public_attestation_bundle,
    # ─── §pass70 Sprint 19 (Tier 2 — 10 new) ──────────────────────────────
    "theprotocol_getRevokedIdentities": get_revoked_identities,
    "theprotocol_crossRegistryContractProxy": cross_registry_contract_proxy,
    "theprotocol_acceptContractFederated": accept_contract_federated,
    "theprotocol_submitContractWorkFederated": submit_contract_work_federated,
    "theprotocol_relayAction": relay_action,
    "theprotocol_getRelayStatus": get_relay_status,
    "theprotocol_getMyEnforcementStatus": get_my_enforcement_status,
    "theprotocol_tegLockDirect": teg_stake_direct,
    "theprotocol_tegUnlockDirect": teg_unstake_direct,
    "theprotocol_tegCrossRegistryTransferDirect": teg_cross_registry_transfer_direct,
    # ─── §pass70 Sprint 19 (Tier 3 — 8 new) ───────────────────────────────
    "theprotocol_getMyDeveloperJwks": get_my_developer_jwks,
    "theprotocol_getOAuthFederationStatus": get_oauth_federation_status,
    "theprotocol_oauthIntrospect": oauth_introspect,
    "theprotocol_oauthRevoke": oauth_revoke,
    "theprotocol_oauthFederationTrustList": oauth_federation_trust_list,
    "theprotocol_oauthTokenExchange": oauth_token_exchange,
    "theprotocol_acceptOrgInvitation": accept_org_invitation,
    "theprotocol_getSupportTicketDetail": get_support_ticket_detail,
    "theprotocol_replySupportTicket": reply_support_ticket,
    "theprotocol_requestSelfRevocation": request_self_revocation,
    # ─── §pass70 Sprint 20 (Tier 1 — 5 new) ───────────────────────────────
    "theprotocol_getPublicShowcaseCall": get_public_showcase_call,
    "theprotocol_authRecover2FA": auth_recover_2fa,
    "theprotocol_listPublicOperatorApplications": list_public_operator_applications,
    "theprotocol_getAgentByDIDAlt": get_agent_by_did_alt,
    # ─── §pass70 Sprint 20 (Tier 2 — 3 new) ───────────────────────────────
    "theprotocol_submitOnboardRegister": submit_onboard_register,
    "theprotocol_tegReputationSignal": teg_reputation_signal_token,
    "theprotocol_federationSyncRequest": federation_sync_request,
    # ─── §pass70 Sprint 20 (Tier 3 — 12 new) ──────────────────────────────
    "theprotocol_getMyDeveloperActivityEventstore": get_my_developer_activity_eventstore,
    "theprotocol_listDeveloperApikeysMe": list_developer_apikeys_me,
    "theprotocol_createDeveloperApikeyMe": create_developer_apikey_me,
    "theprotocol_listDeveloperWebhooks": list_developer_webhooks,
    "theprotocol_getProposalDetail": get_proposal_detail,
    "theprotocol_getProposalVotes": get_proposal_votes,
    "theprotocol_getAutoTallyConfig": get_auto_tally_config,
    "theprotocol_federationProposeRaise": federation_propose_raise,
    "theprotocol_federationVetoProposal": federation_veto_proposal,
    "theprotocol_getDevTrustGraph": get_dev_trust_graph,
    "theprotocol_getAgentMetrics": get_agent_metrics,
    "theprotocol_agentBuilderGenerate": agent_builder_generate,
    # ─── §pass70 Sprint 21 (Tier 1 — 7 new: arena) ────────────────────────
    "theprotocol_listArenaMatches": list_arena_matches,
    "theprotocol_getArenaMatch": get_arena_match,
    "theprotocol_getArenaMatchBets": get_arena_match_bets,
    "theprotocol_getArenaMatchMap": get_arena_match_map,
    "theprotocol_getArenaLeaderboard": get_arena_leaderboard,
    "theprotocol_getArenaAgentStats": get_arena_agent_stats,
    "theprotocol_createArenaMatch": create_arena_match,
    # ─── §pass70 Sprint 21 (Tier 3 — 9 new) ───────────────────────────────
    "theprotocol_listAgentBuilderTemplates": list_agent_builder_templates,
    "theprotocol_agentBuilderGenerateTemplate": agent_builder_generate_template,
    "theprotocol_updateMyDeveloperProfile": update_my_developer_profile,
    "theprotocol_listDeveloperWebhooksAlt": list_developer_webhooks_alt,
    "theprotocol_getDeveloperWebhookDeliveriesAlt": get_developer_webhook_deliveries_alt,
    "theprotocol_testDeveloperWebhookAlt": test_developer_webhook_alt,
    "theprotocol_downloadPipelineTemplate": download_pipeline_template,
    "theprotocol_purchasePipelineTemplate": purchase_pipeline_template,
    "theprotocol_createTegPoliciesBatch": create_teg_policies_batch,
}

# Tier 2 tools require auth context as first positional argument
TIER2_TOOLS = {
    "theprotocol_getMyBalance",
    "theprotocol_getTegDisputeDetail",  # §MCPTEST30 2026-10-01: GET /teg/disputes/{id} is agent-authed (a party check); as T3 every call was a 401
    "theprotocol_resolveTegDispute",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates an agent: it sent the developer's token)
    "theprotocol_getAgentReputation",  # §pass73.3.19: agent-authed endpoint (was mis-tiered T3)
    "theprotocol_deleteMyAgent",  # §pass73.3.19: agent self-delete (DELETE /agents/me, get_current_agent) — was mis-tiered T3
    "theprotocol_transferUnits",
    "theprotocol_smartSend",
    "theprotocol_bridgeTransfer",
    "theprotocol_lockUnits",
    "theprotocol_unlockUnits",
    "theprotocol_castVote",
    "theprotocol_submitDispute",
    "theprotocol_createProposal",
    # §pass70 Sprint 2 Wave 1
    "theprotocol_getMyLocks",
    "theprotocol_getMyVotingPower",
    "theprotocol_getMyIncome",
    "theprotocol_authorizePayment",
    "theprotocol_verifyPayment",
    "theprotocol_settlePayment",
    "theprotocol_releasePayment",
    "theprotocol_submitFundingRequest",
    # §pass70 Sprint 3 Wave 4 (Tier 2)
    "theprotocol_getMyAgentInfo",
    "theprotocol_agentHeartbeat",
    "theprotocol_enableMtls",
    "theprotocol_getMyPayoutRelock",
    "theprotocol_getMyPayoutHistory",
    # §pass70 Sprint 4 (Tier 2)
    "theprotocol_getMyLockStatus",
    "theprotocol_getMyLockHistory",
    "theprotocol_getMyAgentHealth",
    # §pass70 Sprint 5 (Tier 2 — 10 new)
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
    # §pass70 Sprint 6 (Tier 2 — 2 new)
    "theprotocol_getMyAgentDisputes",
    "theprotocol_estimateMyLockPayouts",
    # §pass70 Sprint 7 (Tier 2 — 7 new; getDisputeById re-tiered to dev)
    "theprotocol_agentRevokeAttestation",
    "theprotocol_disableMyAttestationSchedule",
    "theprotocol_releasePaymentById",
    "theprotocol_approveContractCompletion",
    "theprotocol_markContractFailed",
    "theprotocol_submitDisputeEvidence",
    "theprotocol_getContractById",
    # §pass70 Sprint 8 (Tier 2 — 2 new; getRegistryFederationProposals re-tiered)
    "theprotocol_logEnhancedDispute",
    "theprotocol_getRegistryFederationProposals",
    # §pass70 Sprint 9 (Tier 2 — 3 new)
    "theprotocol_getMyTegBalance",
    "theprotocol_getMyTegTransactions",
    "theprotocol_getMyTegDisputes",
    # §pass70 Sprint 10 (Tier 2 — 2 new; exportAgent + updateMyAgentLocation re-tiered to dev)
    "theprotocol_getMyReputationBondStatus",
    "theprotocol_depositReputationBond",
    "theprotocol_unlockReputationBond",  # §BATCH0911 item 4
    # §pass70 Sprint 11 (Tier 2 — 2 new)
    "theprotocol_getTegAttestations",
    "theprotocol_getTegAdvancedTransactions",
    # §pass70 Sprint 13 (Tier 2 — 5 new: TEG mutations)
    "theprotocol_tegSystemTransfer",
    "theprotocol_logTegDispute",
    "theprotocol_crossTegBalanceSync",
    "theprotocol_applyReputationSignal",
    # §pass70 Sprint 17 (Tier 2 — 8 new)
    "theprotocol_getMyMtlsStatus",
    "theprotocol_disableMyMtls",
    "theprotocol_acceptContract",
    "theprotocol_engageAgent",
    # §OURSTATE-1 — chat: TIER2 so the inline agent_jwt swap works; the chat
    # API is dual-auth, so a developer bridge token passes through unchanged.
    "theprotocol_listConversations",
    "theprotocol_readThread",
    "theprotocol_sendChatMessage",
    "theprotocol_respondChatRequest",
    "theprotocol_blockChatPrincipal",
    "theprotocol_unblockChatPrincipal",
    "theprotocol_getContractV2",
    "theprotocol_submitContractMilestone",
    "theprotocol_releaseContractMilestone",
    "theprotocol_instantiateContractTemplate",
    "theprotocol_submitContractWork",
    "theprotocol_createMalpracticeDispute",
    "theprotocol_federationVoteProposal",
    "theprotocol_tallyProposal",
    "theprotocol_submitTegAttestation",
    # §pass70 Sprint 18 (Tier 2 — 3 new)
    "theprotocol_getRegistryTreasury",
    "theprotocol_getUnitPayouts",
    "theprotocol_getUnitTransactions",
    # §pass70 Sprint 19 (Tier 2 — 10 new)
    "theprotocol_getRevokedIdentities",
    "theprotocol_crossRegistryContractProxy",
    "theprotocol_acceptContractFederated",
    "theprotocol_submitContractWorkFederated",
    "theprotocol_getMyEnforcementStatus",
    "theprotocol_tegLockDirect",
    "theprotocol_tegUnlockDirect",
    "theprotocol_tegCrossRegistryTransferDirect",
    # §pass70 Sprint 20 (Tier 2 — 3 new)
    "theprotocol_submitOnboardRegister",
    "theprotocol_tegReputationSignal",
    "theprotocol_federationSyncRequest",
}

# Tier 3 tools require auth context as first positional argument
TIER3_TOOLS = {
    "theprotocol_getMyAgents",
    "theprotocol_createArenaMatch",  # D6-634 (2026-10-16): its route admits only an administrator; the tool forwards the developer credential
    "theprotocol_claimTegPayouts",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates the agent's developer: it sent the agent's token)
    "theprotocol_relayAction",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates the agent's developer)
    "theprotocol_getRelayStatus",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates the agent's developer)
    "theprotocol_getCommunityAnnouncements",  # §MCPTEST30 V0538: the request survey's TIER class (its route authenticates a developer: it sent none, and read the 401 as an empty feed)
    "theprotocol_createAgent",
    # §pass70 Sprint 2 Wave 2
    "theprotocol_getMyDeveloperProfile",
    "theprotocol_getMyApiKeys",
    "theprotocol_createApiKey",
    "theprotocol_getMyOrganizations",
    "theprotocol_getMyAgentBundles",
    # §pass70 Sprint 3 Wave 4 (Tier 3)
    "theprotocol_submitSupportTicket",
    "theprotocol_getMySupportTickets",
    "theprotocol_revokeApiKey",
    "theprotocol_getMyDisputes",
    # §pass70 Sprint 4 (Tier 3 — 12 new)
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
    # §pass70 Sprint 5 (Tier 3 — 8 new)
    "theprotocol_getMyMcpAuditLog",
    "theprotocol_getMyDeletionStatus",
    "theprotocol_getMyAchievements",
    "theprotocol_getMyUnreadNotifications",
    "theprotocol_markNotificationRead",
    "theprotocol_getOrganization",
    "theprotocol_listOrganizationMembers",
    "theprotocol_getFeaturedBundles",
    # §pass70 Sprint 6 (Tier 3 — 7 new)
    "theprotocol_listMyAttestations",
    "theprotocol_getAttestationDetail",
    "theprotocol_getAttestationBundle",
    "theprotocol_getTrustScore",
    "theprotocol_getVolumeProfile",
    "theprotocol_getCrossFrameReputation",
    "theprotocol_getReputationComputationStatus",
    # §pass70 Sprint 7 (Tier 3 — 11 new; +getDisputeById moved from Tier 2)
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
    # §pass70 Sprint 9 (Tier 3 — 12 new)
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
    # §pass70 Sprint 10 (Tier 3 — 15 new: 13 CI/CD mutations + 2 re-tiered)
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
    # §pass70 Sprint 11 (Tier 3 — 7 new)
    "theprotocol_getTransactionsAnalytics",
    "theprotocol_getAgentPayoutHistory",
    "theprotocol_getAgentPendingPayouts",
    "theprotocol_getAgentLockedBalance",
    "theprotocol_getAgentLockHistory",
    "theprotocol_listTegPolicies",
    "theprotocol_getTegPoliciesComplianceDashboard",
    # §pass70 Sprint 12 (Tier 3 — 16 new)
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
    # §pass70 Sprint 13 (Tier 3 — 12 new)
    "theprotocol_getTegTransactionDetail",
    "theprotocol_getAgentTransactionHistory",
    "theprotocol_exportTegTransactions",
    "theprotocol_createTegPolicy",
    "theprotocol_updateTegPolicy",
    "theprotocol_deleteTegPolicy",
    "theprotocol_getTegPolicy",
    "theprotocol_createFrameInvitation",
    "theprotocol_finalizeFrameInvitation",
    # §pass70 Sprint 14 (Tier 3 — 15 new)
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
    # §pass70 Sprint 15 (Tier 3 — 12 new)
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
    # §pass70 Sprint 16 (Tier 3 — 10 new)
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
    # §pass70 Sprint 17 (Tier 3 — 12 new)
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
    # §pass70 Sprint 18 (Tier 3 — 7 new)
    "theprotocol_importAgent",
    "theprotocol_validateAgentImport",
    "theprotocol_agentBulkExport",
    "theprotocol_authRefresh",
    "theprotocol_regenerateBackupCodes",
    "theprotocol_operatorPortalSelfLogs",
    "theprotocol_operatorPortalSelfRestart",
    # §pass70 Sprint 19 (Tier 3 — 8 new)
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
    # §pass70 Sprint 20 (Tier 3 — 12 new)
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
    # §pass70 Sprint 21 (Tier 3 — 9 new)
    "theprotocol_listAgentBuilderTemplates",
    "theprotocol_agentBuilderGenerateTemplate",
    "theprotocol_updateMyDeveloperProfile",
    "theprotocol_listDeveloperWebhooksAlt",
    "theprotocol_getDeveloperWebhookDeliveriesAlt",
    "theprotocol_testDeveloperWebhookAlt",
    "theprotocol_downloadPipelineTemplate",
    "theprotocol_purchasePipelineTemplate",
    "theprotocol_createTegPoliciesBatch",
    # §pass70 Sprint 8 (Tier 3 — 13 new; getRegistryFederationProposals re-tiered to agent)
    "theprotocol_getFeeCurrentRate",
    "theprotocol_requestAccountDeletion",
    "theprotocol_cancelAccountDeletion",
    "theprotocol_claimPendingAchievements",
    "theprotocol_recordAchievement",
    "theprotocol_listOrganizationAgents",
    "theprotocol_getSupportReviewState",
    "theprotocol_grantSupportReview",
    "theprotocol_revokeSupportReview",
    "theprotocol_listOrganizationInvitations",
    "theprotocol_withdrawOrganizationInvitation",
    "theprotocol_getOrganizationCicdSummary",
    "theprotocol_removeOrganizationMember",
    "theprotocol_updateOrganizationTeam",
    "theprotocol_deleteOrganizationTeam",
    "theprotocol_removeTeamMember",
    "theprotocol_unassignAgentFromOrg",
    "theprotocol_getPayoutRelockForAgent",
    # §pass70 Sprint 1 — getGovernanceProposals moved OUT to Tier 1
}

AUTH_REQUIRED_TOOLS = TIER2_TOOLS | TIER3_TOOLS

# ---------------------------------------------------------------------------
# Pydantic models for JSON-RPC 2.0
# ---------------------------------------------------------------------------

class JsonRpcRequest(BaseModel):
    jsonrpc: str = Field(default="2.0")
    id: Optional[Union[str, int]] = None
    method: str
    params: Optional[Union[Dict[str, Any], List[Any]]] = None


def _jsonrpc_success(request_id: Any, result: Any) -> JSONResponse:
    return JSONResponse(content={
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    })


def _jsonrpc_error(request_id: Any, code: int, message: str, data: Any = None) -> JSONResponse:
    error_obj: Dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error_obj["data"] = str(data)

    http_status = 500
    if code in (-32700, -32600, -32602):
        http_status = 400
    elif code in (-32601, -32002):   # §MCPTEST30: -32002 resource not found is the client's miss, not a 500
        http_status = 404
    elif code == -32001:  # Custom: auth required
        http_status = 401
    elif code == -32003:  # §MCPTEST30 V0529: the credential could not be checked (the database did not answer)
        http_status = 503

    return JSONResponse(
        status_code=http_status,
        content={"jsonrpc": "2.0", "id": request_id, "error": error_obj},
        headers={"Retry-After": "5"} if http_status == 503 else None,
    )


# ---------------------------------------------------------------------------
# Helper: extract Bearer token from request
# ---------------------------------------------------------------------------

def _peer_address(request: Request) -> Optional[str]:
    """The address our own edge observed for this MCP request.

    LAST element of X-Forwarded-For: nginx appends the real peer to whatever the
    client sent, so the last entry is the only one a caller cannot forge.
    """
    xff = (request.headers.get("x-forwarded-for") or "").strip()
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    real = (request.headers.get("x-real-ip") or "").strip()
    if real:
        return real
    return request.client.host if request.client else None


def _extract_token(request: Request) -> Optional[str]:
    """Extract Bearer token from Authorization header.

    Also records the ORIGINATING client address for this request (§EXTMTLS,
    2026-08-09). MCP tools reach the registry by posting to REGISTRY_SELF_URL
    (loopback), so anything downstream that cares where the caller actually is
    would otherwise see 127.0.0.1 — which made IRONHAND report a genuinely
    off-site agent as on-host. A contextvar is used rather than threading the
    Request through the dispatch chain, matching the existing pattern for OPA
    decisions and the L3 act-principal.
    """
    set_mcp_client_ip(_peer_address(request))
    # B6 (RBAC plan) — a capability token presented at the MCP transport travels the
    # same contextvar road as the client IP: forwarded into every internal REST call
    # (mcp_forwarded_headers) and consulted by the per-tool caveat gate at dispatch.
    set_mcp_capability_token(request.headers.get("X-Capability-Token"))
    auth_header = request.headers.get("Authorization") or request.headers.get("authorization")
    if not auth_header:
        return None
    parts = auth_header.split()
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1]
    return None


# ---------------------------------------------------------------------------
# MCP method handlers
# ---------------------------------------------------------------------------

def _if_listed(bare: str, text: str = None) -> str:
    """W3: a name (or a text) for the initialize instructions, only where the switches list that tool."""
    return (text if text is not None else bare + ", ") if _tool_listed("theprotocol_" + bare) else ""


async def _handle_initialize(params: Any) -> Dict[str, Any]:
    """MCP initialize handshake."""
    return {
        "protocolVersion": negotiate_protocol_version(params),
        "capabilities": MCP_SERVER_INFO["capabilities"],
        "serverInfo": {
            "name": MCP_SERVER_INFO["name"],
            "version": MCP_SERVER_INFO["version"],
            "description": MCP_SERVER_INFO["description"],
            "icons": MCP_SERVER_INFO["icons"],
        },
        # D6-727: the count a client is told is the count tools/list gives it (the dispatch table holds two fewer:
        # enableToolset and disableToolset are answered before dispatch)
        "instructions": (
            f"TheProtocol MCP Server provides {len(filter_listed(ALL_TOOL_SCHEMAS))} tools across 4 authentication tiers:\n"
            "  Tier 0 (no auth, utility): getAgentToken\n"
            "  Tier 1 (no auth): discoverRegistries, discoverAgents, getAgentProfile, "
            f"getNetworkStats, {_if_listed('getLockPayoutTiers')}getGovernanceProposals, getRegistryCard, getFiatTiers, "
            "getFiatProviders, getFiatQuote, getLockStats, getNetworkHealth\n"
            f"  Tier 2 (agent JWT): balance/transfer/{_if_listed('lockUnits', 'lock/')}unlock/vote/bridge/dispute/proposal, "
            "getMyLocks, getMyVotingPower, getMyIncome, authorize/verify/settle/releasePayment, "
            "submitFundingRequest, getMyAgentInfo, agentHeartbeat, enableMtls"
            f"{_if_listed('getMyPayoutRelock', ', getMyPayoutRelock')}{_if_listed('getMyPayoutHistory', ', getMyPayoutHistory')}\n"
            "  Tier 3 (developer JWT): getMyAgents, createAgent, getMyDeveloperProfile, getMyApiKeys, "
            "createApiKey, revokeApiKey, getMyOrganizations, getMyAgentBundles, submitSupportTicket, "
            "getMySupportTickets, getMyDisputes\n"
            "All tool names are prefixed with 'theprotocol_' (e.g. theprotocol_discoverAgents).\n"
            "Pass your TheProtocol JWT as: Authorization: Bearer <token>\n"
            "CONTEXT-SAVING OPTIONS: append ?mode=gateway to the endpoint URL (or send "
            "X-MCP-Mode: gateway) to list only the core tools plus listToolsets/searchTools/"
            "describeTools/invokeTool/enableToolset/disableToolset and discover the rest on "
            "demand; or append ?toolsets=wallet,discovery (X-MCP-Toolsets) to list chosen "
            "buckets only. enableToolset persists a per-credential selection (24h). "
            "No parameters = the full catalog, unchanged.\n"
            "ALSO AVAILABLE: MCP resources (resources/list — registry card, solvency card, "
            "JWKS, OpenAPI, live network stats, agent cards by DID), prompts (prompts/list — "
            f"guided flows for onboarding, funding, transfers, {_if_listed('lockUnits', 'locks, ')}Guild, AGORA, "
            "diagnostics), and experimental async tasks on long-running tools "
            "(tools/call with params.task={ttl}; poll tasks/get, fetch tasks/result). "
            "Every tool carries title + behavior annotations (readOnly/destructive/idempotent)."
        ),
    }


def _resolve_tool_visibility(request: Request):
    """Resolve listing visibility from ?mode=/?toolsets= (query wins over the
    X-MCP-Mode / X-MCP-Toolsets headers). Returns (mode, selected, problems):
    selected=None means no bucket filtering; problems is a list of client-error
    strings (unknown mode / unknown bucket names — we fail loud on typos rather
    than silently mis-filter)."""
    q = request.query_params
    mode = (q.get("mode") or request.headers.get("x-mcp-mode") or "full").strip().lower()
    raw_toolsets = q.get("toolsets") or request.headers.get("x-mcp-toolsets")
    problems: List[str] = []
    if mode not in ("full", "gateway"):
        problems.append(f"unknown mode '{mode}' (valid: full, gateway)")
        mode = "full"
    selected, unknown = parse_toolsets(raw_toolsets, is_admin=False)
    if unknown:
        problems.append(f"unknown toolsets {unknown} (valid: {sorted(PUBLIC_BUCKETS.keys())})")
    return mode, selected, problems


async def _handle_tools_list(mode: str = "full", selected=None) -> Dict[str, Any]:
    """Return live tool schemas, optionally bucket-filtered and/or reduced to
    the gateway listing (core tools + meta-tools). Default = full catalog,
    byte-identical to the pre-2026-07-14 behavior for existing tools."""
    visible = filter_listed(filter_schemas(ALL_TOOL_SCHEMAS, selected))   # W3: the registry's switches decide the listing
    if mode == "gateway":
        visible = [
            s for s in visible
            if s.get("name") in tools_gateway.GATEWAY_TOOL_NAMES
            or bare_name(s.get("name", "")) in PUBLIC_CORE_TOOLS
        ]
    return {"tools": visible}


async def _handle_tools_call(
    tool_name: str,
    arguments: Dict[str, Any],
    token: Optional[str],
) -> Tuple[Dict[str, Any], Any]:
    """Dispatch a tool call to the appropriate handler.

    §pass68 — returns tuple (result, auth_ctx_or_None) so the dispatcher can
    emit per-tool audit log rows with full actor context. auth_ctx is None
    for Tier 1 tools (no auth required) and the authenticated MCPAuthContext
    for Tier 2/3.
    """
    tool_name = resolve_alias(tool_name)   # §AGORAWORDS: tasks re-enter here with the name they were given
    if tool_name not in TOOL_DISPATCH:
        raise ValueError(f"Unknown tool: {tool_name}")

    tool_fn = TOOL_DISPATCH[tool_name]

    # Tier 2: if caller passes agent_jwt directly in arguments, use it
    # instead of the bridge header token — eliminates bridge-swap workflow.
    if tool_name in TIER2_TOOLS:
        inline_jwt = arguments.pop("agent_jwt", None)
        effective_token = inline_jwt or token
    else:
        effective_token = token

    # ── B6 (RBAC plan): per-TOOL capability scoping at dispatch ────────────────────
    # A capability token may arrive as the X-Capability-Token transport header (already
    # in the contextvar) or as a per-call `capability_token` argument (works with every
    # bridge/client today); the argument wins and ALSO refreshes the contextvar so the
    # tool's internal REST call forwards the same token it was gated on.
    # When the token's caveats carry `tools: [...]`, the requested tool must be listed
    # (matched on the bare name — 'theprotocol_getMyBalance' and 'getMyBalance' are the
    # same tool). Deny-only, pre-dispatch, before ANY REST call: a scope violation never
    # reaches the endpoint. Denials count as capability misuse (the P0.5 breaker sees
    # per-tool abuse too). No token, or a token without a tools caveat → unchanged.
    inline_cap = arguments.pop("capability_token", None)
    if inline_cap:
        set_mcp_capability_token(str(inline_cap))
    _cap_plain = get_mcp_capability_token()
    if _cap_plain and tool_name in TOOL_DISPATCH:
        from agentvault_registry import agent_delegation as _capmod
        from .tool_categories import bare_name as _bare
        try:
            async with get_db_context() as _cdb:
                from sqlalchemy import text as _sqltext
                _row = (await _cdb.execute(_sqltext(
                    "SELECT id, status, caveats, holder_agent_did FROM agent_capability_tokens "
                    "WHERE token_hash = :h AND (expires_at IS NULL OR expires_at > now())"
                ), {"h": _capmod.hash_token(_cap_plain)})).first()
                _tools_cav = (_row.caveats or {}).get("tools") if _row else None
                if _row and isinstance(_tools_cav, list) and _tools_cav:
                    _want = _bare(tool_name)
                    _allowed = {_bare(str(t)) for t in _tools_cav}
                    if _want not in _allowed:
                        try:
                            await _capmod.note_capability_misuse(
                                _cdb, _row.id, f"tool_out_of_scope:{_want}", actor_did=None)
                        except Exception:  # noqa: BLE001 — the deny itself stands
                            pass
                        return (_tool_result_payload({
                            "error": f"capability token is scoped to tools {sorted(_allowed)} — "
                                     f"'{_want}' is outside its scope"
                        }), None)
        except Exception:  # noqa: BLE001 — the gate must never 500 the dispatcher;
            # an unreadable token falls through to the REST layer, which enforces
            # every other caveat (and rejects a bogus token outright).
            logger.warning("[B6-MCP] tools-caveat gate skipped for %s", tool_name, exc_info=True)

    auth_ctx: Any = None

    # Authenticate if tool requires it
    if tool_name in AUTH_REQUIRED_TOOLS:
        async with get_db_context() as db:
            auth_ctx = await authenticate_mcp_token(effective_token, db)

        # Call with auth context as first positional argument
        refuse_unbindable(tool_fn, (auth_ctx,), arguments, auth_ctx)
        try:
            result = await tool_fn(auth_ctx, **arguments)
        except Exception as e:
            # §MCPTEST30 (V0545): the audit names the caller of a call that failed, not "anonymous"
            e.mcp_auth_ctx = auth_ctx  # type: ignore[attr-defined]
            raise
    else:
        # Tier 1 — no auth context
        refuse_unbindable(tool_fn, (), arguments)
        result = await tool_fn(**arguments)

    return (_tool_result_payload(result), auth_ctx)


# §MCPTEST30 (V0524): every tool's inputSchema by name, built at first use: ALL_TOOL_SCHEMAS is extended in place after its
# definition (the Guild, the gateway), so a map taken at import would miss those tools.
_INPUT_SCHEMA_BY_NAME: Dict[str, Any] = {}


def _input_schema(name: str) -> Optional[Dict[str, Any]]:
    if not _INPUT_SCHEMA_BY_NAME:
        _INPUT_SCHEMA_BY_NAME.update({t["name"]: t.get("inputSchema") for t in ALL_TOOL_SCHEMAS if isinstance(t, dict) and "name" in t})
    return _INPUT_SCHEMA_BY_NAME.get(name)


def _tool_result_payload(result: Any) -> Dict[str, Any]:
    """Build the CallToolResult (2025-11-25): text content for every client,
    plus structuredContent (the raw JSON object) for typed consumers — the
    spec's dual-emit rule. Tool-level failures (wrapper returned an 'error'
    dict) now honestly set isError=true instead of hiding in the text."""
    is_err = is_failure(result)   # §MCPTEST30: an `error` VALUE, never the key alone (mcp/tool_result.py)
    payload: Dict[str, Any] = {
        "content": [{"type": "text", "text": _format_tool_result(result)}],
        "isError": bool(is_err),
    }
    if isinstance(result, dict) and not is_err:
        payload["structuredContent"] = result
    return payload


def _format_tool_result(result: Any) -> str:
    """Convert tool result dict to formatted string for MCP content block."""
    if is_failure(result):
        return f"Error: {result['error']}"
    try:
        return json.dumps(result, indent=2, default=str)
    except Exception:
        return str(result)


# ---------------------------------------------------------------------------
# Streamable HTTP endpoint (MCP spec 2025-03-26) — single URL transport
# ---------------------------------------------------------------------------

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


@router.post("", summary="MCP Streamable HTTP endpoint (POST — JSON-RPC requests)")
async def mcp_streamable_post(request: Request):
    """
    Streamable HTTP transport — MCP spec 2025-03-26.

    Single endpoint that handles JSON-RPC 2.0 requests.
    Returns 401 with WWW-Authenticate if no Bearer token is provided,
    triggering the OAuth discovery flow in Claude Desktop.
    """
    import json as _json

    # Check for auth token — if missing, return 401 to trigger OAuth flow
    token = _extract_token(request)
    if not token:
        # Parse the request to check if it's initialize (allow without auth)
        try:
            body = await request.json()
            method = body.get("method", "")
        except Exception:
            method = ""

        # Allow handshake + discovery without auth
        handshake = ("initialize", "ping", "tools/list", "resources/list",
                 "resources/templates/list", "resources/read", "prompts/list",
                 "prompts/get", "completion/complete")
        if method not in handshake and not method.startswith("notifications/"):
            proto = request.headers.get("x-forwarded-proto", "https")
            host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
            resource_url = f"{proto}://{host}/.well-known/oauth-protected-resource"
            return JSONResponse(
                status_code=401,
                content={"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Authentication required"}},
                headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_url}"'},
            )

    # §MCPTEST30: a notification is handled and accepted with 202, no body (the receiver never replies to one)
    if await _incoming_is_notification(request):
        from starlette.responses import Response as _Response
        await handle_rpc(request)
        return _Response(status_code=202)

    # Process the JSON-RPC request via the shared handler
    json_response = await handle_rpc(request)
    response_body = json_response.body.decode("utf-8")

    # Check if client wants SSE (mcp-remote, Claude Desktop)
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        # Notifications (no id) — return empty 200
        try:
            parsed = _json.loads(response_body)
            if parsed.get("id") is None and not parsed.get("error"):
                return StreamingResponse(iter([]), status_code=200, media_type="text/event-stream")
        except Exception:
            pass

        sse_payload = tools_gateway.sse_answer(await _request_json(request), response_body)   # D6-725
        async def _sse_stream():
            yield sse_payload
        return StreamingResponse(
            _sse_stream(), status_code=200, media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # Plain JSON response (standard HTTP clients, Claude Code --transport http)
    return json_response


@router.get("", summary="MCP Streamable HTTP endpoint (GET — server notifications SSE)")
async def mcp_streamable_get(request: Request) -> StreamingResponse:
    """
    Streamable HTTP transport — GET opens SSE stream for server-initiated notifications.
    Allows unauthenticated connections for discovery. Auth enforced on tool calls.
    """
    import json as _json
    import asyncio as _asyncio

    async def _notification_stream():
        # Send server info notification
        info = {
            "jsonrpc": "2.0",
            "method": "notifications/serverInfo",
            "params": MCP_SERVER_INFO,
        }
        yield f"event: message\ndata: {_json.dumps(info)}\n\n"
        # Keepalive
        try:
            while True:
                await _asyncio.sleep(30)
                yield f"event: ping\ndata: {{}}\n\n"
        except Exception:
            pass

    return StreamingResponse(
        _notification_stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.delete("", summary="MCP Streamable HTTP endpoint (DELETE — close session)")
async def mcp_streamable_delete():
    """Streamable HTTP session cleanup. Stateless server — always returns 200."""
    return JSONResponse(status_code=200, content={"status": "ok"})


# ---------------------------------------------------------------------------
# Legacy JSON-RPC endpoint (backward compatibility)
# ---------------------------------------------------------------------------

@router.post("/rpc", response_class=JSONResponse, summary="MCP JSON-RPC 2.0 endpoint (legacy)")
async def handle_rpc(request: Request) -> JSONResponse:
    """
    TheProtocol MCP Server — JSON-RPC 2.0 endpoint.

    Handles all MCP protocol methods:
    - initialize   : Client-server handshake
    - ping         : Keepalive check
    - tools/list   : List all available tools and their schemas
    - tools/call   : Execute a tool by name

    Authentication:
        Authorization: Bearer <developer_jwt | agent_jwt | api_key>
    """
    request_id = None

    try:
        raw_body = await request.json()
    except Exception:
        return _jsonrpc_error(None, -32700, "Parse error: invalid JSON")

    if not isinstance(raw_body, dict):
        return _jsonrpc_error(None, -32600, "Invalid Request: body must be a JSON object")

    try:
        payload = JsonRpcRequest(**raw_body)
        request_id = payload.id
    except Exception as e:
        return _jsonrpc_error(None, -32600, f"Invalid Request: {e}")

    method = payload.method
    params = payload.params or {}
    if isinstance(params, list):
        params = {}  # Normalize — our tools only use named params

    token = _extract_token(request)
    token_prefix = token[:15] + '...' if token and len(token) > 15 else token

    logger.info(f"MCP RPC: method={method} id={request_id} auth={'yes' if token else 'no'} token_prefix={token_prefix}")

    # Return 401 with WWW-Authenticate to trigger OAuth flow when no token.
    # Allow protocol handshake + discovery methods through without auth:
    # initialize, ping, tools/list, resources/list, prompts/list, notifications/*
    # Auth is enforced on tools/call (actual execution), not discovery.
    handshake_methods = ("initialize", "ping", "tools/list", "resources/list",
                 "resources/templates/list", "resources/read", "prompts/list",
                 "prompts/get", "completion/complete")
    is_handshake = method in handshake_methods or method.startswith("notifications/")
    if not token and not is_handshake:
        proto = request.headers.get("x-forwarded-proto", "https")
        host = request.headers.get("x-forwarded-host") or request.headers.get("host", "localhost")
        resource_url = f"{proto}://{host}/.well-known/oauth-protected-resource"
        return JSONResponse(
            status_code=401,
            content={"jsonrpc": "2.0", "id": request_id, "error": {"code": -32001, "message": "Authentication required. Use OAuth or pass Bearer token."}},
            headers={"WWW-Authenticate": f'Bearer resource_metadata="{resource_url}"'},
        )

    try:
        # --- Route to method handlers ---

        if method == "initialize":
            result = await _handle_initialize(params)
            return _jsonrpc_success(request_id, result)

        elif method == "ping":
            return _jsonrpc_success(request_id, {})

        elif method.startswith("notifications/"):
            # Client notifications — no response needed per MCP protocol
            # Return 200 OK with empty result if id present, else empty 200
            if request_id is not None:
                return _jsonrpc_success(request_id, {})
            return JSONResponse(status_code=200, content={})

        elif method == "resources/list":
            return _jsonrpc_success(request_id, resources.list_resources())

        elif method == "resources/templates/list":
            return _jsonrpc_success(request_id, resources.list_templates())

        elif method == "resources/read":
            uri = (params or {}).get("uri", "")
            contents, err = await resources.read_resource(uri)
            if err:
                return _jsonrpc_error(request_id, resources.error_code(err), err)
            return _jsonrpc_success(request_id, contents)

        elif method == "prompts/list":
            return _jsonrpc_success(request_id, prompts.list_prompts())

        elif method == "prompts/get":
            got = prompts.get_prompt((params or {}).get("name", ""), (params or {}).get("arguments"))
            if got is None:
                return _jsonrpc_error(request_id, -32602, f"Unknown prompt: {(params or {}).get('name')}")
            missing = prompts.missing_required((params or {}).get("name", ""), (params or {}).get("arguments"))
            if missing:   # §MCPTEST30: MCP answers a missing required argument with -32602, never a prompt with holes
                return _jsonrpc_error(request_id, -32602, f"Missing required argument(s): {', '.join(missing)}")
            return _jsonrpc_success(request_id, got)

        elif method == "completion/complete":
            comp = prompts.complete(
                (params or {}).get("ref") or {},
                (params or {}).get("argument") or {},
                sorted(PUBLIC_BUCKETS.keys()),
            )
            return _jsonrpc_success(request_id, comp)

        # --- Async tasks (2025-11-25 experimental; mcp_tasks.py) ---

        elif method == "tasks/get":
            rec = await mcp_tasks.get_task((params or {}).get("taskId", ""), mcp_tasks.ctx_hash(token))
            if rec is None:
                return _jsonrpc_error(request_id, -32602, "Failed to retrieve task: Task not found")
            return _jsonrpc_success(request_id, mcp_tasks.task_public(rec))

        elif method == "tasks/result":
            rec, err = await mcp_tasks.wait_result((params or {}).get("taskId", ""), mcp_tasks.ctx_hash(token))
            if err:
                return _jsonrpc_error(request_id, -32602 if "not found" in err else -32603, err)
            final = dict(rec.get("result") or {"content": [{"type": "text", "text": rec.get("statusMessage", "")}],
                                               "isError": rec["status"] != "completed"})
            final.setdefault("_meta", {})[mcp_tasks.RELATED_TASK_META] = {"taskId": rec["taskId"]}
            return _jsonrpc_success(request_id, final)

        elif method == "tasks/cancel":
            rec, err = await mcp_tasks.cancel_task((params or {}).get("taskId", ""), mcp_tasks.ctx_hash(token))
            if err:
                return _jsonrpc_error(request_id, -32602, err)
            return _jsonrpc_success(request_id, mcp_tasks.task_public(rec))

        elif method == "tasks/list":
            listing, err = await mcp_tasks.list_tasks(mcp_tasks.ctx_hash(token), (params or {}).get("cursor"))
            if err:
                return _jsonrpc_error(request_id, -32602, err)
            return _jsonrpc_success(request_id, listing)

        elif method == "tools/list":
            mode, selected, problems = _resolve_tool_visibility(request)
            if problems:
                return _jsonrpc_error(request_id, -32602, "Invalid params: " + "; ".join(problems))
            # L2: no explicit filter on the request → apply the session's
            # stored toolset selection (enableToolset/disableToolset).
            if selected is None and token:
                selected = await tools_gateway.get_session_selection(
                    mcp_tasks.ctx_hash(token), is_admin=False
                )
            result = await _handle_tools_list(mode, selected)
            # Spec cursor support: full list by default (client-compat), a
            # provided cursor pages at 100/page.
            cursor = (params or {}).get("cursor")
            if cursor is not None:
                try:
                    offset = int(cursor)
                    if offset < 0:
                        raise ValueError
                except (TypeError, ValueError):
                    return _jsonrpc_error(request_id, -32602, "Invalid params: bad cursor")
                full = result["tools"]
                result = {"tools": full[offset:offset + 100]}
                if offset + 100 < len(full):
                    result["nextCursor"] = str(offset + 100)
            return _jsonrpc_success(request_id, result)

        elif method == "tools/call":
            # §AGORAWORDS (V0419): a renamed tool still executes under its old name (mcp/tool_aliases.py).
            tool_name = resolve_alias(params.get("name", ""))
            arguments = params.get("arguments", {}) or {}

            if not tool_name:
                return _jsonrpc_error(request_id, -32602, "Invalid params: 'name' is required for tools/call")

            # Gateway invokeTool unwraps BEFORE dispatch: the inner tool then
            # flows through the normal tier-auth + audit path under its own
            # name (the audit row records the inner tool, which is the truth).
            if tool_name == tools_gateway.INVOKE_TOOL:
                try:
                    tool_name, arguments = tools_gateway.unwrap_invoke(arguments, TOOL_DISPATCH)
                except ValueError as ve:
                    return _jsonrpc_error(request_id, -32602, str(ve))

            # L2 dynamic toolsets — handled here (not via dispatch) because the
            # session key derives from the request credential. Listing
            # preference only; no data access, hence no audit row.
            if tool_name in (tools_gateway.ENABLE_TOOLSET_TOOL, tools_gateway.DISABLE_TOOLSET_TOOL):
                sel_result = await tools_gateway.modify_session_toolsets(
                    mcp_tasks.ctx_hash(token), arguments.get("toolsets"),
                    is_admin=False, enable=(tool_name == tools_gateway.ENABLE_TOOLSET_TOOL),
                )
                return _jsonrpc_success(request_id, _tool_result_payload(sel_result))

            if tool_name not in TOOL_DISPATCH:
                return _jsonrpc_error(
                    request_id, -32601,
                    f"Tool not found: '{tool_name}'. Use tools/list to see available tools."
                )

            # §MCPTEST30 (V0524): an argument its tool's inputSchema cannot take is the caller's -32602, before the tool
            # runs (mcp/arguments.py; 72 of 107 mistyped reads answered -32603 "Internal error" on sbx-alpha, V0521)
            _arg_problems = argument_problems(_input_schema(tool_name), arguments)
            if _arg_problems:
                return _jsonrpc_error(request_id, -32602, "Invalid params: " + "; ".join(_arg_problems))

            # §pass68 — per-tool audit hook. Captures actor (after auth), args
            # (sanitized), outcome, latency. Fire-and-forget via asyncio.create_task
            # in emit_mcp_audit; never blocks the response path.
            actor_ip = request.client.host if request.client else None
            ua = request.headers.get("user-agent")
            req_id = request.headers.get("x-request-id") or (str(request_id) if request_id else None)

            # --- Task-augmented execution (2025-11-25 experimental) ---------
            # params.task on a taskSupport-enabled tool → accept, return a
            # CreateTaskResult immediately, execute in the background (same
            # auth + audit path), deliver via tasks/result.
            task_params = params.get("task")
            if task_params is not None:
                if bare_name(tool_name) not in task_tools(is_admin=False):
                    return _jsonrpc_error(
                        request_id, -32601,
                        f"Tool '{tool_name}' does not support task-augmented execution "
                        "(execution.taskSupport is absent) — call it normally."
                    )
                ttl_ms = task_params.get("ttl") if isinstance(task_params, dict) else None
                rec = await mcp_tasks.create_task(mcp_tasks.ctx_hash(token), ttl_ms, tool_name)

                async def _bg_call(tool_name=tool_name, arguments=arguments, token=token,
                                   actor_ip=actor_ip, ua=ua, req_id=req_id):
                    bg_t0 = time.perf_counter()
                    bg_ctx: Any = None
                    try:
                        bg_result, bg_ctx = await _handle_tools_call(tool_name, arguments, token)
                        outcome, payload = "success", bg_result
                    except (MCPAuthError, MCPAuthUnavailable) as e:
                        outcome = "failure"
                        payload = {"content": [{"type": "text", "text": f"Error: {e}"}], "isError": True}
                    except ToolArgumentsRefused as e:   # §MCPTEST30 (V0545): the caller's arguments, not a failure
                        outcome, bg_ctx = "failure", e.auth_ctx
                        payload = {"content": [{"type": "text", "text": f"Error: Invalid params: {e}"}], "isError": True}
                    except Exception as e:  # noqa: BLE001 — task boundary
                        outcome = "error"
                        # §MCPTEST30 V0529: never a database driver's words (the repr carried them)
                        payload = {"content": [{"type": "text", "text": f"Error: {format_tool_exception(e)}"}], "isError": True}
                    await emit_mcp_audit(
                        tool_name=tool_name, arguments=arguments, auth_ctx=bg_ctx,
                        outcome=outcome, result_or_error=payload,
                        latency_ms=(time.perf_counter() - bg_t0) * 1000.0,
                        actor_ip=actor_ip, user_agent=ua, request_id=req_id,
                        is_admin_server=False,
                    )
                    return payload

                mcp_tasks.spawn(rec["taskId"], _bg_call)
                return _jsonrpc_success(request_id, {
                    "task": mcp_tasks.task_public(rec),
                    "_meta": {mcp_tasks.IMMEDIATE_RESPONSE_META: (
                        f"Task {rec['taskId']} accepted for {tool_name}; poll tasks/get, "
                        "then fetch the outcome with tasks/result."
                    )},
                })
            t0 = time.perf_counter()
            auth_ctx_for_audit: Any = None
            try:
                result, auth_ctx_for_audit = await _handle_tools_call(tool_name, arguments, token)
                latency_ms = (time.perf_counter() - t0) * 1000.0
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx_for_audit,
                    outcome="success",
                    result_or_error=result,
                    latency_ms=latency_ms,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=False,
                )
                return _jsonrpc_success(request_id, result)
            except MCPAuthError as auth_err:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx_for_audit,
                    outcome="failure",
                    result_or_error=str(auth_err),
                    latency_ms=latency_ms,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=False,
                )
                return _jsonrpc_error(request_id, -32001, str(auth_err))
            except MCPAuthUnavailable as unavailable:
                # §MCPTEST30 V0529: the database could not check the credential: "try again", never "authenticate"
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx_for_audit,
                    outcome="error",
                    result_or_error=str(unavailable),
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=False,
                )
                return _jsonrpc_error(request_id, -32003, str(unavailable))
            except ToolArgumentsRefused as bad:
                # §MCPTEST30 (V0545): arguments that do not bind to the tool are the caller's -32602, audited as a
                # refusal (warning) under the caller who sent them, never as an unhandled tool failure
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=bad.auth_ctx,
                    outcome="failure",
                    result_or_error=f"Invalid params: {bad}",
                    latency_ms=(time.perf_counter() - t0) * 1000.0,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=False,
                )
                return _jsonrpc_error(request_id, -32602, f"Invalid params: {bad}")
            except Exception as exc:
                latency_ms = (time.perf_counter() - t0) * 1000.0
                await emit_mcp_audit(
                    tool_name=tool_name,
                    arguments=arguments,
                    auth_ctx=auth_ctx_for_audit or getattr(exc, "mcp_auth_ctx", None),
                    outcome="error",
                    result_or_error=repr(exc),
                    latency_ms=latency_ms,
                    actor_ip=actor_ip,
                    user_agent=ua,
                    request_id=req_id,
                    is_admin_server=False,
                )
                raise

        else:
            return _jsonrpc_error(request_id, -32601, f"Method not found: '{method}'")

    except MCPAuthError as e:
        return _jsonrpc_error(request_id, -32001, str(e))
    except MCPAuthUnavailable as e:   # §MCPTEST30 V0529
        return _jsonrpc_error(request_id, -32003, str(e))
    except TypeError as e:
        logger.warning(f"MCP param error for {method}: {e}")
        return _jsonrpc_error(request_id, -32602, f"Invalid params: {e}")
    except Exception as e:
        logger.error(f"MCP RPC error for {method}: {e}", exc_info=True)
        # §MCPTEST30 V0529: the exception's text, never a database driver's words (V0525's class, on this envelope)
        return _jsonrpc_error(request_id, -32603, f"Internal error: {safe_exception_text(e)}")


# ---------------------------------------------------------------------------
# SSE endpoint (MCP Inspector + Claude Desktop compatibility)
# ---------------------------------------------------------------------------

@router.post("/sse", summary="MCP Streamable HTTP endpoint (MCP 2025-11-25 StreamableHTTP transport)")
async def mcp_streamable_http(request: Request) -> StreamingResponse:
    """
    Streamable HTTP transport endpoint — MCP protocol 2025-11-25.

    mcp-remote uses StreamableHTTPClientTransport which POSTs JSON-RPC requests
    with Accept: text/event-stream and expects the response wrapped as an SSE event:

        Content-Type: text/event-stream

        event: message
        data: {"jsonrpc":"2.0","id":0,"result":{...}}

    Returning plain application/json causes mcp-remote to ignore the response
    and wait on the SSE channel until the 60s timeout fires.
    """

    # Execute the JSON-RPC call and get the response content
    json_response = await handle_rpc(request)
    response_body = json_response.body.decode("utf-8")

    # Notifications (no id) don't need a response — return empty 200
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

    # Wrap the JSON-RPC response as a single SSE message event (after list_changed when the call changed the listing)
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


@router.get("/sse", summary="MCP SSE transport endpoint")
async def mcp_sse(request: Request) -> StreamingResponse:
    """
    Server-Sent Events endpoint for MCP Inspector / Claude Desktop.

    SSE endpoint allows unauthenticated connections for tool discovery.
    Auth is enforced on individual tool calls via POST to /mcp/rpc.
    """

    async def event_generator():
        # Send MCP endpoint event (SSE format)
        # Per MCP SSE spec: data must be the absolute POST URL as a plain string
        # IMPORTANT: Do NOT derive from request.base_url — inside Docker that
        # returns the internal container address, not the host-accessible URL.
        rpc_url = os.environ.get("MCP_PUBLIC_RPC_URL", "http://localhost:8000/mcp/rpc")
        yield f"event: endpoint\ndata: {rpc_url}\n\n"

        # Send server info
        info_event = {
            "jsonrpc": "2.0",
            "method": "notifications/serverInfo",
            "params": MCP_SERVER_INFO,
        }
        yield f"event: message\ndata: {json.dumps(info_event)}\n\n"

        # Keep connection alive with periodic pings
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


# ---------------------------------------------------------------------------
# Tools listing convenience endpoint (non-standard, for exploration)
# ---------------------------------------------------------------------------

@router.get("/tools", summary="List all MCP tools (convenience endpoint)")
async def list_tools_http(request: Request) -> Dict[str, Any]:
    """
    HTTP GET convenience endpoint to list all tools and schemas.

    Non-standard (use POST /mcp/rpc with tools/list for MCP compliance).
    Useful for exploration and debugging. Honors the same ?mode=/?toolsets=
    visibility params as tools/list and — being non-standard anyway — also
    annotates each tool with its category and lists the bucket taxonomy.
    """
    from .tool_categories import get_category

    mode, selected, problems = _resolve_tool_visibility(request)
    if problems:
        return {"error": "; ".join(problems)}
    listed = (await _handle_tools_list(mode, selected))["tools"]
    # D6-727: grouped by the credential each tool needs (the tier sets the dispatch checks), not by the module that
    # defines its schema: submitDispute is defined beside the developer tools and needs an agent token.
    tiers: Dict[str, List[str]] = {"tier0_utility": [], "tier1_public": [], "tier2_agent": [], "tier3_developer": [],
                                   "listing_preferences": []}
    catalog = filter_listed(ALL_TOOL_SCHEMAS)
    for t in catalog:
        tiers[_tier_key(t["name"])].append(t["name"])
    return {
        "server": MCP_SERVER_INFO["name"],
        "version": MCP_SERVER_INFO["version"],
        "total_tools": len(catalog),
        "not_listed_by_switches": len(ALL_TOOL_SCHEMAS) - len(catalog),
        "listed_tools": len(listed),
        "mode": mode,
        "toolsets": sorted(selected) if selected is not None else None,
        "buckets": PUBLIC_BUCKETS,
        "tiers": tiers,
        "tools": [dict(t, category=get_category(t.get("name", ""))) for t in listed],
    }


def _tier_key(name: str) -> str:
    """The tier a tool belongs to, as tools/call enforces it: getAgentToken needs no credential, the TIER2/TIER3 sets
    an agent's or a developer's, enableToolset/disableToolset any (they store a listing preference, no data), every
    other tool none."""
    if name == "theprotocol_getAgentToken":
        return "tier0_utility"
    if name in TIER2_TOOLS:
        return "tier2_agent"
    if name in TIER3_TOOLS:
        return "tier3_developer"
    if name in (tools_gateway.ENABLE_TOOLSET_TOOL, tools_gateway.DISABLE_TOOLSET_TOOL):
        return "listing_preferences"
    return "tier1_public"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@router.get("/health", summary="MCP server health check")
async def mcp_health() -> Dict[str, Any]:
    """Returns MCP server health status and available tool count."""
    return {
        "status": "ok",
        "server": MCP_SERVER_INFO["name"],
        "version": MCP_SERVER_INFO["version"],
        "tools_available": len(filter_listed(ALL_TOOL_SCHEMAS)),
        "endpoints": {
            "streamable_http": "POST /mcp (recommended)",
            "rpc": "POST /mcp/rpc (legacy)",
            "sse": "GET /mcp/sse (deprecated)",
            "tools": "GET /mcp/tools",
            "health": "GET /mcp/health",
        },
    }


# ═══════════════════════════════════════════════════════════════════════
# AGORA exchange — tool wiring (2026-06-12). Appended post-definitions:
# TOOL_DISPATCH/TIER sets are mutated before any request is served, and
# AUTH_REQUIRED_TOOLS (built above as a snapshot union) is updated in step.
# ═══════════════════════════════════════════════════════════════════════
from .tools_discovery import (  # noqa: E402
    get_exchange_listings as _agora_listings,
    get_exchange_listing as _agora_listing,
    get_exchange_order_book as _agora_book,
    get_exchange_trades as _agora_trades,
    get_exchange_candles as _agora_candles,
)
from .tools_agent import (  # noqa: E402
    place_exchange_order as _agora_place,
    cancel_exchange_order as _agora_cancel,
    get_my_exchange_orders as _agora_my_orders,
    get_my_exchange_portfolio as _agora_portfolio,
    buy_exchange_ipo as _agora_ipo,
)
from .tools_developer import (  # noqa: E402
    create_exchange_listing as _agora_create_listing,
    declare_exchange_dividend as _agora_dividend,
)

TOOL_DISPATCH.update({
    "theprotocol_getAgoraListings": _agora_listings,
    "theprotocol_getAgoraListing": _agora_listing,
    "theprotocol_getAgoraOrderBook": _agora_book,
    "theprotocol_getAgoraTrades": _agora_trades,
    "theprotocol_getAgoraCandles": _agora_candles,
    "theprotocol_placeAgoraOrder": _agora_place,
    "theprotocol_cancelAgoraOrder": _agora_cancel,
    "theprotocol_getMyAgoraOrders": _agora_my_orders,
    "theprotocol_getMyAgoraHoldings": _agora_portfolio,
    "theprotocol_buyAgoraLaunch": _agora_ipo,
    "theprotocol_createAgoraListing": _agora_create_listing,
    "theprotocol_declareAgoraDistribution": _agora_dividend,
})

_AGORA_T2 = {
    "theprotocol_placeAgoraOrder",
    "theprotocol_cancelAgoraOrder",
    "theprotocol_getMyAgoraOrders",
    "theprotocol_getMyAgoraHoldings",
    "theprotocol_buyAgoraLaunch",
}
_AGORA_T3 = {
    "theprotocol_createAgoraListing",
    "theprotocol_declareAgoraDistribution",
}
TIER2_TOOLS.update(_AGORA_T2)
TIER3_TOOLS.update(_AGORA_T3)

# ── GÖDEL FORGE (batch-3 FG2-6): public arena reads + agent-triggered eval run ──
from .tools_discovery import (  # noqa: E402
    get_forge_status as _forge_status,
    get_forge_lineage as _forge_lineage,
)
from .tools_agent import run_forge_eval as _forge_run_eval  # noqa: E402

TOOL_DISPATCH.update({
    "theprotocol_getForgeStatus": _forge_status,
    "theprotocol_getForgeLineage": _forge_lineage,
    "theprotocol_runForgeEval": _forge_run_eval,
})
TIER2_TOOLS.update({"theprotocol_runForgeEval"})
AUTH_REQUIRED_TOOLS.update({"theprotocol_runForgeEval"})
AUTH_REQUIRED_TOOLS.update(_AGORA_T2 | _AGORA_T3)

# ---------------------------------------------------------------------------
# THE GUILD tools (2026-07-08) — same late-wiring pattern as AGORA above.
# ---------------------------------------------------------------------------
from .tools_guild import (  # noqa: E402
    GUILD_TOOL_SCHEMAS,
    guild_list_orders as _guild_list,
    guild_get_order as _guild_get_order,
    guild_network_board as _guild_net_board,
    guild_post_order as _guild_post_order,
    guild_bid as _guild_bid,
    guild_award as _guild_award,
    guild_submit_work as _guild_submit,
    guild_verify as _guild_verify,
    guild_cancel_order as _guild_cancel,
    guild_my_work as _guild_mine,
    guild_cross_registry_bid as _guild_xreg,
)

TOOL_DISPATCH.update({
    "theprotocol_guildListOrders": _guild_list,
    "theprotocol_guildGetOrder": _guild_get_order,
    "theprotocol_guildNetworkBoard": _guild_net_board,
    "theprotocol_guildPostOrder": _guild_post_order,
    "theprotocol_guildBid": _guild_bid,
    "theprotocol_guildAward": _guild_award,
    "theprotocol_guildSubmitWork": _guild_submit,
    "theprotocol_guildVerify": _guild_verify,
    "theprotocol_guildCancelOrder": _guild_cancel,
    "theprotocol_guildMyWork": _guild_mine,
    "theprotocol_guildCrossRegistryBid": _guild_xreg,
})

_GUILD_T2 = {
    "theprotocol_guildPostOrder",
    "theprotocol_guildBid",
    "theprotocol_guildAward",
    "theprotocol_guildSubmitWork",
    "theprotocol_guildVerify",
    "theprotocol_guildCancelOrder",
    "theprotocol_guildMyWork",
    "theprotocol_guildCrossRegistryBid",
}
TIER2_TOOLS.update(_GUILD_T2)
AUTH_REQUIRED_TOOLS.update(_GUILD_T2)
# tools/list + tier listing (ALL_TOOL_SCHEMAS was concatenated before this block runs)
AGENT_TOOL_SCHEMAS.extend(GUILD_TOOL_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(GUILD_TOOL_SCHEMAS)

# ---------------------------------------------------------------------------
# V0650 (a) (2026-10-31): an agent's status line and its organization's presence (mcp/tools_presence.py), late-wired.
# Both tier 2 for the inline agent_jwt swap; the presence read forwards whatever token the context holds.
# ---------------------------------------------------------------------------
from .tools_presence import (  # noqa: E402
    PRESENCE_TOOL_SCHEMAS,
    get_organization_presence as _presence_org,
    set_my_agent_status as _presence_set,
)

# a literal dict: the CI tier gate (.forgejo/checks/mcp_audit_tier_coverage.py) reads the dispatch keys by AST
TOOL_DISPATCH.update({
    "theprotocol_setMyAgentStatus": _presence_set,
    "theprotocol_getOrganizationPresence": _presence_org,
})
_PRESENCE_T2 = {"theprotocol_setMyAgentStatus", "theprotocol_getOrganizationPresence"}
TIER2_TOOLS.update(_PRESENCE_T2)
AUTH_REQUIRED_TOOLS.update(_PRESENCE_T2)
AGENT_TOOL_SCHEMAS.extend(PRESENCE_TOOL_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(PRESENCE_TOOL_SCHEMAS)

# ---------------------------------------------------------------------------
# §MEMBERSHIP (2026-10-02): membership and the commons (mcp/tools_commons.py), the same late-wiring pattern. Tier 1 by
# absence: getMembershipStats, getCommonsSeasons, getCommonsSeason. The six admin tools are on the admin server.
# ---------------------------------------------------------------------------
from .tools_commons import (  # noqa: E402
    COMMONS_AGENT_TOOL_SCHEMAS,
    COMMONS_DEVELOPER_TOOL_SCHEMAS,
    COMMONS_PUBLIC_TOOL_SCHEMAS,
    cast_commons_ballot as _commons_ballot,
    get_commons_season as _commons_season,
    get_commons_seasons as _commons_seasons,
    get_membership_stats as _membership_stats,
    get_my_commons_season as _commons_mine,
    get_my_membership as _membership_me,
    submit_commons_work as _commons_submit,
)

# a literal dict: the CI tier gate (.forgejo/checks/mcp_audit_tier_coverage.py) reads the dispatch keys by AST
TOOL_DISPATCH.update({
    "theprotocol_getMembershipStats": _membership_stats,
    "theprotocol_getMyMembership": _membership_me,
    "theprotocol_getCommonsSeasons": _commons_seasons,
    "theprotocol_getCommonsSeason": _commons_season,
    "theprotocol_getMyCommonsSeason": _commons_mine,
    "theprotocol_submitCommonsWork": _commons_submit,
    "theprotocol_castCommonsBallot": _commons_ballot,
})
_COMMONS_T2 = {"theprotocol_submitCommonsWork", "theprotocol_castCommonsBallot"}
_COMMONS_T3 = {"theprotocol_getMyMembership", "theprotocol_getMyCommonsSeason"}
TIER2_TOOLS.update(_COMMONS_T2)
TIER3_TOOLS.update(_COMMONS_T3)
AUTH_REQUIRED_TOOLS.update(_COMMONS_T2 | _COMMONS_T3)
DISCOVERY_TOOL_SCHEMAS.extend(COMMONS_PUBLIC_TOOL_SCHEMAS)
AGENT_TOOL_SCHEMAS.extend(COMMONS_AGENT_TOOL_SCHEMAS)
DEVELOPER_TOOL_SCHEMAS.extend(COMMONS_DEVELOPER_TOOL_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(COMMONS_PUBLIC_TOOL_SCHEMAS + COMMONS_DEVELOPER_TOOL_SCHEMAS + COMMONS_AGENT_TOOL_SCHEMAS)

# ---------------------------------------------------------------------------
# V0650 (l) (2026-10-31): approvals in the chat (mcp/tools_chat_approvals.py), the same late-wiring pattern. The status
# tool is tier 2 for the inline agent_jwt swap and forwards whatever token the context holds (a member of the room
# reads it either way); deciding is tier 3, a developer credential (an agent context is refused).
# ---------------------------------------------------------------------------
from .tools_chat_approvals import (  # noqa: E402
    CHAT_APPROVAL_AGENT_TOOL_SCHEMAS,
    CHAT_APPROVAL_DEVELOPER_TOOL_SCHEMAS,
    decide_chat_approval as _approval_decide,
    get_chat_approval_status as _approval_status,
    request_chat_approval as _approval_request,
)

# a literal dict: the CI tier gate (.forgejo/checks/mcp_audit_tier_coverage.py) reads the dispatch keys by AST
TOOL_DISPATCH.update({
    "theprotocol_requestChatApproval": _approval_request,
    "theprotocol_getChatApprovalStatus": _approval_status,
    "theprotocol_decideChatApproval": _approval_decide,
})
_APPROVAL_T2 = {"theprotocol_requestChatApproval", "theprotocol_getChatApprovalStatus"}
_APPROVAL_T3 = {"theprotocol_decideChatApproval"}
TIER2_TOOLS.update(_APPROVAL_T2)
TIER3_TOOLS.update(_APPROVAL_T3)
AUTH_REQUIRED_TOOLS.update(_APPROVAL_T2 | _APPROVAL_T3)
AGENT_TOOL_SCHEMAS.extend(CHAT_APPROVAL_AGENT_TOOL_SCHEMAS)
DEVELOPER_TOOL_SCHEMAS.extend(CHAT_APPROVAL_DEVELOPER_TOOL_SCHEMAS)
ALL_TOOL_SCHEMAS.extend(CHAT_APPROVAL_AGENT_TOOL_SCHEMAS + CHAT_APPROVAL_DEVELOPER_TOOL_SCHEMAS)


# ---------------------------------------------------------------------------
# Gateway meta-tools (2026-07-14 L1) — registered LAST so their closures see
# the fully concatenated ALL_TOOL_SCHEMAS (list is mutated in place by the
# extends above, so late binding keeps them current). Tier 1 by absence from
# TIER2/TIER3 (search/describe/listToolsets expose the same data tools/list
# already serves unauthenticated); invokeTool never executes via dispatch —
# handle_rpc unwraps it first — the stub only catches unexpected paths.
# ---------------------------------------------------------------------------

async def _gateway_search_tools(query: str = "", toolsets: str = None, limit: int = 10) -> Dict[str, Any]:
    return await tools_gateway.search_tools(
        filter_listed(ALL_TOOL_SCHEMAS), is_admin=False, query=query, toolsets=toolsets, limit=limit
    )


async def _gateway_describe_tools(names: list = None) -> Dict[str, Any]:
    return await tools_gateway.describe_tools(filter_listed(ALL_TOOL_SCHEMAS), is_admin=False, names=names or [])


async def _gateway_list_toolsets() -> Dict[str, Any]:
    return await tools_gateway.list_toolsets(filter_listed(ALL_TOOL_SCHEMAS), is_admin=False)


TOOL_DISPATCH.update({
    tools_gateway.SEARCH_TOOL: _gateway_search_tools,
    tools_gateway.DESCRIBE_TOOL: _gateway_describe_tools,
    tools_gateway.LIST_TOOLSETS_TOOL: _gateway_list_toolsets,
    tools_gateway.INVOKE_TOOL: tools_gateway._invoke_stub,
})
ALL_TOOL_SCHEMAS.extend(tools_gateway.GATEWAY_TOOL_SCHEMAS)

# 2026-07-14 reference-grade pass — stamp title/annotations (+ curated
# outputSchema / execution.taskSupport) onto the FINAL catalog. Must run
# after every extend above; idempotent because the gateway schema objects
# are shared with server_admin.py (see tool_metadata.decorate_schemas).
decorate_schemas(ALL_TOOL_SCHEMAS, is_admin=False)
# §MCPTEST30 (V0548): each tool's inputSchema states what its route enforces (mcp/route_constraints.py, kept equal to
# the routes by test_mcp_schemas_state_route_constraints.py); a key the tool states itself is never changed
apply_route_constraints(ALL_TOOL_SCHEMAS)
