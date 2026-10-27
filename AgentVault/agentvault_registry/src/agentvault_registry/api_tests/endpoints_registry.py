"""
Endpoints Registry for API Testing

Central repository of all API endpoints with their metadata.
Extracted from admin_api_test.py for modular access.
"""

import logging
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


class EndpointsRegistry:
    """Registry of all API endpoints organized by category"""
    
    def __init__(self):
        self._endpoints = self._initialize_endpoints()
        self._endpoint_lookup = self._build_lookup()
        
    def _initialize_endpoints(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Initialize the complete endpoints registry.
        
        This is the complete ALL_ENDPOINTS from admin_api_test.py
        """
        return {
            "admin": [
                {"method": "GET", "path": "/admin/dashboard", "auth": "developer", "description": "Get admin dashboard"},
                {"method": "GET", "path": "/admin/system-health", "auth": "developer", "description": "Get system health"},
                {"method": "PUT", "path": "/admin/disputes/{dispute_id}/ruling", "auth": "developer", "description": "Update dispute ruling"},
                {"method": "GET", "path": "/admin/test-tokens", "auth": "developer", "description": "generate_test_tokens"},
                {"method": "GET", "path": "/admin/docker-stats", "auth": "developer", "description": "get_docker_stats"},
                {"method": "GET", "path": "/admin/combined-health", "auth": "developer", "description": "get_combined_health"},
                {"method": "GET", "path": "/admin/system-resources", "auth": "developer", "description": "get_system_resources"},
                {"method": "GET", "path": "/admin/system-activity", "auth": "developer", "description": "get_system_activity"},
                {"method": "GET", "path": "/admin/eventstore-stats", "auth": "developer", "description": "get_eventstore_stats"},
                {"method": "GET", "path": "/admin/eventstore-recent", "auth": "developer", "description": "get_recent_events"},
                {"method": "GET", "path": "/admin/eventstore-balances", "auth": "developer", "description": "get_eventstore_balances"},
                {"method": "GET", "path": "/admin/prometheus-metrics", "auth": "developer", "description": "get_prometheus_metrics"},
                {"method": "POST", "path": "/admin/projection-snapshot", "auth": "developer", "description": "take_projection_snapshot"},
                {"method": "GET", "path": "/admin/event-emission-policies", "auth": "developer", "description": "get_event_emission_policies"},
                {"method": "PUT", "path": "/admin/event-emission-policies/{event_type}", "auth": "developer", "description": "update_event_emission_policy"},
                {"method": "POST", "path": "/admin/tutorial/execute", "auth": "developer", "description": "execute_tutorial_call"},
                {"method": "POST", "path": "/admin/tutorial/generate-proof", "auth": "developer", "description": "generate_zkp_proof"},
                {"method": "GET", "path": "/admin/tutorial/health", "auth": "developer", "description": "tutorial_sandbox_health"},
                {"method": "POST", "path": "/admin/invite-codes/generate", "auth": "developer", "description": "generate_codes"},
                {"method": "GET", "path": "/admin/invite-codes", "auth": "developer", "description": "list_codes"},
                {"method": "DELETE", "path": "/admin/invite-codes/{code}", "auth": "developer", "description": "revoke_code"},
                {"method": "GET", "path": "/admin/invite-codes/validate/{code}", "auth": "developer", "description": "validate_code_public"},
                {"method": "GET", "path": "/admin/simulation/status", "auth": "developer", "description": "get_simulation_status"},
                {"method": "POST", "path": "/admin/simulation/start", "auth": "developer", "description": "start_simulation"},
                {"method": "POST", "path": "/admin/simulation/stop", "auth": "developer", "description": "stop_simulation"},
                {"method": "GET", "path": "/admin/simulation/logs", "auth": "developer", "description": "get_simulation_logs"},
                {"method": "GET", "path": "/admin/simulation/agents", "auth": "developer", "description": "get_simulation_agents"},
                {"method": "POST", "path": "/admin/simulation/fund", "auth": "developer", "description": "fund_simulation_agents"},
                {"method": "POST", "path": "/admin/simulation/funding-preview", "auth": "developer", "description": "funding_preview"},
                {"method": "POST", "path": "/admin/simulation/mint-frame-b", "auth": "developer", "description": "mint_frame_b"},
                {"method": "GET", "path": "/admin/simulation/fund-status", "auth": "developer", "description": "get_fund_status"},
                {"method": "GET", "path": "/admin/simulation/topology", "auth": "developer", "description": "get_federation_topology"},
                {"method": "GET", "path": "/admin/simulation/supply-audit", "auth": "developer", "description": "get_supply_audit"},
                {"method": "POST", "path": "/admin/broadcasts", "auth": "developer", "description": "create_broadcast"},
                {"method": "GET", "path": "/admin/broadcasts", "auth": "developer", "description": "list_broadcasts"},
                {"method": "DELETE", "path": "/admin/broadcasts/{broadcast_id}", "auth": "developer", "description": "retract_broadcast"},
                {"method": "GET", "path": "/admin/support/tickets", "auth": "developer", "description": "admin_list_tickets"},
                {"method": "POST", "path": "/admin/support/tickets/{ticket_id}/reply", "auth": "developer", "description": "admin_reply_to_ticket"},
                {"method": "POST", "path": "/admin/support/tickets/{ticket_id}/status", "auth": "developer", "description": "admin_change_ticket_status"},
                {"method": "GET", "path": "/admin/enforcement/agents/{agent_did}/slash-preview", "auth": "developer", "description": "slash_stake_preview"},
                {"method": "GET", "path": "/admin/enforcement/registries/quarantined", "auth": "developer", "description": "list_quarantined_registries"},
                {"method": "POST", "path": "/admin/enforcement/registries/{peer_id}/quarantine", "auth": "developer", "description": "quarantine_registry"},
                {"method": "POST", "path": "/admin/enforcement/registries/{peer_id}/lift-quarantine", "auth": "developer", "description": "lift_registry_quarantine"},
                {"method": "POST", "path": "/admin/enforcement/registries/{peer_id}/blacklist", "auth": "developer", "description": "blacklist_registry"},
                {"method": "POST", "path": "/admin/cloud-operators/{application_id}/provision", "auth": "developer", "description": "provision_cloud"},
                {"method": "POST", "path": "/admin/cloud-operators/{application_id}/teardown", "auth": "developer", "description": "teardown_cloud"},
                {"method": "GET", "path": "/admin/cloud-operators", "auth": "developer", "description": "list_cloud_operators"},
                {"method": "GET", "path": "/admin/cloud-operators/{application_id}/health", "auth": "developer", "description": "cloud_operator_health"},
                {"method": "GET", "path": "/admin/ironhand/identities", "auth": "developer", "description": "ironhand_identities"},
                {"method": "POST", "path": "/admin/ironhand/revoke/{agent_did}", "auth": "developer", "description": "admin_revoke_agent"},
                {"method": "POST", "path": "/admin/ironhand/enroll/{agent_did}", "auth": "developer", "description": "admin_enroll_agent"},
                {"method": "DELETE", "path": "/admin/ironhand/spire-entry", "auth": "developer", "description": "admin_delete_spire_entry"},
                {"method": "POST", "path": "/admin/ironhand/register-agent-proxy", "auth": "developer", "description": "register_agent_spire_proxy"},
                {"method": "POST", "path": "/admin/ironhand/delete-agent-proxy", "auth": "developer", "description": "delete_agent_spire_proxy"},
                {"method": "GET", "path": "/docker-registry/token", "auth": "developer", "description": "docker_registry_token"},
            ],
            "admin_api_test": [
                {"method": "GET", "path": "/admin/api-test/endpoints", "auth": "developer", "description": "Get all endpoints"},
                {"method": "POST", "path": "/admin/api-test/test-endpoint", "auth": "developer", "description": "Test single endpoint"},
                {"method": "POST", "path": "/admin/api-test/test-category", "auth": "developer", "description": "Test category"},
                {"method": "GET", "path": "/admin/api-test/run-all", "auth": "developer", "description": "run_all_tests"},
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "test_flow"},
                {"method": "GET", "path": "/admin/api-test/flow-values", "auth": "developer", "description": "get_flow_values"},
                {"method": "POST", "path": "/admin/api-test/reset-flow-values", "auth": "developer", "description": "reset_flow_values"},
                {"method": "GET", "path": "/admin/api-test/sandbox-credentials", "auth": "developer", "description": "get_sandbox_credentials"},
                {"method": "POST", "path": "/admin/api-test/reset-sandbox", "auth": "developer", "description": "reset_sandbox"},
                {"method": "POST", "path": "/admin/api-test/test-federation", "auth": "developer", "description": "test_federation"},
                {"method": "POST", "path": "/admin/api-test/self-reset", "auth": "developer", "description": "self_reset"},
            ],
            "admin_federation": [  # Fully working - verified by tests
                {"method": "GET", "path": "/admin/federation/peers/pending", "auth": "developer", "description": "List pending peers"},
                {"method": "GET", "path": "/admin/federation/peers/all", "auth": "developer", "description": "List all peers"},
                {"method": "POST", "path": "/admin/federation/peers/{peer_id}/approve", "auth": "developer", "description": "Approve peer"},
                {"method": "POST", "path": "/admin/federation/peers/{peer_id}/deactivate", "auth": "developer", "description": "Deactivate peer"},
                {"method": "POST", "path": "/admin/federation/peers/{peer_id}/reject", "auth": "developer", "description": "reject_peer_registry"},
                {"method": "POST", "path": "/admin/federation/peers/{peer_id}/reactivate", "auth": "developer", "description": "reactivate_peer_registry"},
                {"method": "POST", "path": "/admin/federation/validate-policy", "auth": "developer", "description": "validate_policy"},
                {"method": "POST", "path": "/admin/federation/request-admission", "auth": "developer", "description": "request_admission"},
                {"method": "POST", "path": "/admin/federation/complete-admission/{admission_id}", "auth": "developer", "description": "complete_admission"},
                {"method": "GET", "path": "/admin/federation/admission-status/{admission_id}", "auth": "developer", "description": "get_admission_status"},
                {"method": "POST", "path": "/admin/federation/policy-update-request", "auth": "developer", "description": "policy_update_request"},
                {"method": "POST", "path": "/admin/federation/drift-scan", "auth": "developer", "description": "trigger_drift_scan"},
                {"method": "GET", "path": "/admin/federation/self-health", "auth": "developer", "description": "get_self_health"},
                {"method": "GET", "path": "/admin/federation/policy-compliance", "auth": "developer", "description": "get_own_policy_compliance"},
                {"method": "GET", "path": "/admin/federation/compliance/peers/by-operator/{operator_id}", "auth": "developer", "description": "get_peer_detail_by_operator"},
                {"method": "GET", "path": "/admin/federation/compliance/peers/{peer_id}", "auth": "developer", "description": "get_peer_detail"},
                {"method": "POST", "path": "/admin/federation/licenses/generate", "auth": "developer", "description": "generate_federation_license"},
                {"method": "GET", "path": "/admin/federation/licenses", "auth": "developer", "description": "list_federation_licenses"},
                {"method": "GET", "path": "/admin/federation/licenses/{license_id}", "auth": "developer", "description": "get_federation_license"},
                {"method": "POST", "path": "/admin/federation/licenses/{license_id}/revoke", "auth": "developer", "description": "revoke_federation_license"},
                {"method": "POST", "path": "/admin/federation/licenses/{license_id}/suspend", "auth": "developer", "description": "suspend_federation_license"},
                {"method": "POST", "path": "/admin/federation/licenses/{license_id}/reinstate", "auth": "developer", "description": "reinstate_federation_license"},
                {"method": "DELETE", "path": "/admin/federation/licenses/{license_id}", "auth": "developer", "description": "delete_federation_license"},
            ],
            "admin_health": [
                {"method": "GET", "path": "/admin/health-check", "auth": "developer", "description": "Simple health check"},
                {"method": "GET", "path": "/admin/health-check/simple", "auth": "developer", "description": "Simple health check alt"},
                {"method": "POST", "path": "/admin/health-check", "auth": "developer", "description": "Comprehensive health check"},
                {"method": "POST", "path": "/admin/health-check/composite", "auth": "developer", "description": "composite_health_check"},
                {"method": "GET", "path": "/admin/health-check/authenticated", "auth": "developer", "description": "authenticated_health_check"},
                {"method": "GET", "path": "/admin/health-check/public-only", "auth": "developer", "description": "public_health_check"},
                {"method": "GET", "path": "/admin/health-check/with-agent-auth", "auth": "developer", "description": "health_check_with_agent_auth"},
                # #3 (2026-05-08): admin-tier webhook bulk action endpoints (cluster-scope).
                # GET aggregate + recent-deliveries already covered by Webhook Watchtower
                # surface; these three POSTs let cluster admins act on ANY webhook.
                {"method": "POST", "path": "/admin/webhooks/{webhook_id}/test", "auth": "developer", "description": "admin_test_webhook"},
                {"method": "POST", "path": "/admin/webhooks/{webhook_id}/disable", "auth": "developer", "description": "admin_disable_webhook"},
                {"method": "POST", "path": "/admin/webhooks/{webhook_id}/enable", "auth": "developer", "description": "admin_enable_webhook"},
            ],
            "agents": [
                {"method": "GET", "path": "/agents/me", "auth": "agent", "description": "Get current agent"},
                {"method": "GET", "path": "/agents/health", "auth": "agent", "description": "Get agent health"},
                {"method": "POST", "path": "/agents/heartbeat", "auth": "agent", "description": "Agent heartbeat"},
                # DANGEROUS - REMOVED TO PREVENT ACCIDENTAL AGENT DELETION!
                # {"method": "DELETE", "path": "/agents/me", "auth": "agent", "description": "Delete current agent"},
                {"method": "DELETE", "path": "/agents/me", "auth": "developer", "description": "delete_current_agent"},
                {"method": "DELETE", "path": "/agents/{agent_did}/logs", "auth": "developer", "description": "delete_agent_logs"},
                {"method": "GET", "path": "/agents/locations/", "auth": "developer", "description": "get_agent_locations"},
                {"method": "GET", "path": "/agents/locations/operator", "auth": "developer", "description": "get_operator_location"},
                {"method": "GET", "path": "/agents/locations/emission-policies", "auth": "developer", "description": "get_emission_policies_internal"},
                {"method": "GET", "path": "/agents/locations/trusted-registries", "auth": "developer", "description": "get_trusted_registries"},
                {"method": "PUT", "path": "/agents/locations/me", "auth": "developer", "description": "update_my_location"},
                {"method": "GET", "path": "/agents/{agent_did}/did.json", "auth": "developer", "description": "get_did_document"},
                {"method": "GET", "path": "/agents/{agent_did}/ad.json", "auth": "developer", "description": "get_agent_description"},
                {"method": "POST", "path": "/anp/register", "auth": "agent", "description": "anp_register"},
                {"method": "POST", "path": "/agent/enable-mtls", "auth": "agent", "description": "enable_mtls"},
                {"method": "POST", "path": "/agent/disable-mtls", "auth": "agent", "description": "disable_mtls"},
                {"method": "GET", "path": "/agent/mtls-status", "auth": "agent", "description": "mtls_status"},
                {"method": "GET", "path": "/agent/revoked-identities", "auth": "developer", "description": "revoked_identities"},
            ],
            "agent_builder": [
                {"method": "POST", "path": "/agent-builder/generate", "auth": "developer", "description": "Generate agent package"},
                {"method": "POST", "path": "/agent-builder/generate-template", "auth": "developer", "description": "generate_template_bundle"},
                {"method": "GET", "path": "/agent-builder/templates", "auth": "developer", "description": "list_templates"},
            ],
            "agent_cards": [
                {"method": "GET", "path": "/agent-cards/", "auth": "none", "description": "List agent cards"},
                {"method": "GET", "path": "/agent-cards/{card_id}", "auth": "none", "description": "Get agent card"},
                # REMOVED - Endpoint not implemented in current codebase
                # {"method": "GET", "path": "/agent-cards/by-hri", "auth": "none", "description": "Get by human readable ID"},
                {"method": "GET", "path": "/agent-cards/id/{human_readable_id:path}", "auth": "none", "description": "Get by HRI path"},
                {"method": "POST", "path": "/agent-cards/", "auth": "developer", "description": "Create agent card"},
                {"method": "PUT", "path": "/agent-cards/{card_id}", "auth": "developer", "description": "Update agent card"},
                # REMOVED - Can cause issues if card is linked to important agents
                # {"method": "DELETE", "path": "/agent-cards/{card_id}", "auth": "developer", "description": "Delete agent card"},
                {"method": "GET", "path": "/agent-cards/by-hri", "auth": "developer", "description": "get_agent_card_by_hri_query"},
                {"method": "DELETE", "path": "/agent-cards/{card_id}", "auth": "developer", "description": "delete_agent_card"},
            ],
            "agent_discovery": [  # Actually implemented in batch_implementation folder!
                {"method": "GET", "path": "/agents/by-did/{did}", "auth": "developer", "description": "Get agent by DID"},  # Returns 401, needs auth
                {"method": "GET", "path": "/agents/did/{did}", "auth": "none", "description": "Get agent by DID alt"},  # This one works!,
                {"method": "GET", "path": "/discover", "auth": "developer", "description": "discover_agents"},
            ],
            "agents_export_import": [  # Agent Export/Import/Clone - Working!
                {"method": "GET", "path": "/agents/{agent_did}/export", "auth": "developer", "description": "Export Agent Configuration"},
                {"method": "POST", "path": "/agents/export/bulk", "auth": "developer", "description": "Bulk Export Agents"},
                {"method": "POST", "path": "/agents/import", "auth": "developer", "description": "Import Agent Configuration"},
                {"method": "POST", "path": "/agents/import/validate", "auth": "developer", "description": "Validate Agent Import"},
                {"method": "POST", "path": "/agents/{agent_did}/clone", "auth": "developer", "description": "Clone Agent"},
                {"method": "GET", "path": "/agents/templates/{template_id}", "auth": "developer", "description": "Get Agent Template"},
                {"method": "GET", "path": "/agents/templates", "auth": "developer", "description": "List Agent Templates"},
            ],
            "agent_cicd": [  # CI/CD Pipeline Management - Working!
                {"method": "POST", "path": "/agents/{agent_did}/pipelines", "auth": "developer", "description": "Create Pipeline"},
                {"method": "GET", "path": "/agents/{agent_did}/pipelines", "auth": "developer", "description": "List Pipelines"},
                {"method": "PUT", "path": "/agents/{agent_did}/pipelines/{pipeline_id}", "auth": "developer", "description": "Update Pipeline"},
                {"method": "DELETE", "path": "/agents/{agent_did}/pipelines/{pipeline_id}", "auth": "developer", "description": "Delete Pipeline"},
                {"method": "POST", "path": "/agents/{agent_did}/versions", "auth": "developer", "description": "Create Version"},
                {"method": "GET", "path": "/agents/{agent_did}/versions", "auth": "developer", "description": "List Versions"},
                {"method": "POST", "path": "/agents/{agent_did}/versions/{version_id}/activate", "auth": "developer", "description": "Activate Version"},
                {"method": "POST", "path": "/agents/{agent_did}/versions/{version_id}/rollback", "auth": "developer", "description": "Rollback Version"},
                {"method": "POST", "path": "/agents/{agent_did}/deployments", "auth": "developer", "description": "Trigger Deployment"},
                {"method": "GET", "path": "/agents/{agent_did}/deployments", "auth": "developer", "description": "List Deployments"},
                {"method": "GET", "path": "/agents/{agent_did}/deployments/{deployment_id}", "auth": "developer", "description": "Get Deployment"},
                {"method": "POST", "path": "/agents/{agent_did}/deployments/{deployment_id}/status", "auth": "developer", "description": "Update Deployment Status"},
                {"method": "POST", "path": "/agents/{agent_did}/deployments/{deployment_id}/logs", "auth": "developer", "description": "Append Deployment Logs"},
                {"method": "GET", "path": "/pipeline-templates", "auth": "developer", "description": "List Templates"},
                {"method": "POST", "path": "/pipeline-templates", "auth": "developer", "description": "Create Template"},
                {"method": "POST", "path": "/pipeline-templates/{template_id}/purchase", "auth": "developer", "description": "Purchase Template"},
                {"method": "GET", "path": "/pipeline-templates/{template_id}/download", "auth": "developer", "description": "Download Template"},
                {"method": "GET", "path": "/agents/{agent_did}/cicd-stats", "auth": "developer", "description": "Get Cicd Stats"},
            ],
            "agent_logs": [  # Exists and working - FIXED paths
                {"method": "GET", "path": "/agents/{agent_did}/logs", "auth": "developer", "description": "Get agent logs"},
                {"method": "POST", "path": "/agents/{agent_did}/logs", "auth": "developer", "description": "Create agent log"},
                # DANGEROUS - REMOVED TO PREVENT DATABASE ISSUES
                # {"method": "DELETE", "path": "/agents/{agent_did}/logs", "auth": "developer", "description": "Delete agent logs"},
                {"method": "GET", "path": "/agent-metrics/{agent_id}", "auth": "developer", "description": "get_agent_metrics"},
            ],
            "attestations": [
                {"method": "GET", "path": "/attestations/health", "auth": "none", "description": "Attestation health check"},
                {"method": "POST", "path": "/attestations/submit", "auth": "agent", "description": "Submit attestation"},
            ],
            "auth": [
                {"method": "GET", "path": "/auth/profile", "auth": "developer", "description": "Get current user profile"},
                {"method": "GET", "path": "/auth/verify-email", "auth": "none", "description": "Verify email address"},
                {"method": "POST", "path": "/auth/login", "auth": "none", "description": "Developer login"},
                {"method": "POST", "path": "/auth/register", "auth": "none", "description": "Register new developer"},
                {"method": "POST", "path": "/auth/logout", "auth": "developer", "description": "Logout"},
                {"method": "POST", "path": "/auth/agent/token", "auth": "none", "description": "Agent OAuth2 token"},
                {"method": "POST", "path": "/auth/recover-account", "auth": "none", "description": "Recover account"},
                {"method": "POST", "path": "/auth/set-new-password", "auth": "developer", "description": "Set new password"},
                # {"method": "POST", "path": "/auth/request-password-reset", "auth": "none", "description": "Request password reset"},  # Not in auth router
                # {"method": "POST", "path": "/auth/reset-password", "auth": "none", "description": "Reset password"},  # Not in auth router,
                {"method": "GET", "path": "/auth/registration-config", "auth": "developer", "description": "get_registration_config"},
                {"method": "POST", "path": "/auth/change-password", "auth": "developer", "description": "change_password"},
                {"method": "POST", "path": "/auth/resend-verification", "auth": "developer", "description": "resend_verification_email"},
                {"method": "POST", "path": "/auth/forgot-password", "auth": "developer", "description": "forgot_password"},
                {"method": "POST", "path": "/auth/reset-password", "auth": "developer", "description": "reset_password_via_email"},
            ],
            "auth_2fa": [  # Two-Factor Authentication - Working!
                {"method": "POST", "path": "/auth/2fa/setup", "auth": "developer", "description": "Initialize 2FA Setup"},
                {"method": "POST", "path": "/auth/2fa/verify", "auth": "developer", "description": "Complete 2FA Setup"},
                {"method": "POST", "path": "/auth/2fa/disable", "auth": "developer", "description": "Disable 2FA"},
                {"method": "POST", "path": "/auth/2fa/validate", "auth": "none", "description": "Validate 2FA Code During Login"},
                {"method": "POST", "path": "/auth/2fa/recover", "auth": "none", "description": "Use Backup Code"},  # Fixed auth type!
                {"method": "POST", "path": "/auth/2fa/backup-codes", "auth": "developer", "description": "Regenerate Backup Codes"},
                {"method": "GET", "path": "/auth/2fa/status", "auth": "developer", "description": "Get 2FA Status"},
            ],
            "auth_secure": [  # OWL32 Phase 8.20: 8 dupes of auth removed, keeping 4 unique
                {"method": "GET", "path": "/auth/api-keys", "auth": "developer", "description": "List API keys"},
                {"method": "POST", "path": "/auth/refresh", "auth": "none", "description": "Refresh token"},
                {"method": "POST", "path": "/auth/api-keys", "auth": "developer", "description": "Generate API key"},
                # REMOVED: POST /auth/generate-api-key — legacy endpoint deleted (404)
                # DANGEROUS - REMOVED TO PREVENT DATABASE ISSUES
                # {"method": "DELETE", "path": "/auth/api-keys/{key_id}", "auth": "developer", "description": "Revoke API key"},
                {"method": "DELETE", "path": "/auth/api-keys/{key_id}", "auth": "developer", "description": "revoke_api_key"},
            ],
            "contracts": [
                {"method": "GET", "path": "/contracts/", "auth": "developer", "description": "List contracts"},
                {"method": "GET", "path": "/contracts/{contract_id}", "auth": "developer", "description": "Get contract"},
                {"method": "GET", "path": "/contracts/agent/{agent_did}", "auth": "developer", "description": "Get agent contracts"},
                {"method": "POST", "path": "/contracts/", "auth": "agent", "description": "Create contract"},
                {"method": "POST", "path": "/contracts/{contract_id}/accept", "auth": "agent", "description": "Accept contract"},
                {"method": "POST", "path": "/contracts/{contract_id}/submit", "auth": "agent", "description": "Submit contract"},
                {"method": "POST", "path": "/contracts/{contract_id}/approve-completion", "auth": "agent", "description": "Approve completion"},
                {"method": "POST", "path": "/contracts/malpractice", "auth": "agent", "description": "Report malpractice"},
                # §TWOAGENT (V0437): /contracts/{contract_id}/{accept,submit}-federated rows deleted: both are 410 GONE
                # (a peer no longer acts in an agent's name; the provider acts on its own registry via contracts v2)
                {"method": "POST", "path": "/contracts/cross-registry/proxy", "auth": "agent", "description": "proxy_contract_action"},
            ],
            "developers": [
                {"method": "GET", "path": "/developers/me", "auth": "developer", "description": "Get current developer"},
                {"method": "GET", "path": "/developers/me/agents", "auth": "developer", "description": "Get my agents"},
                {"method": "GET", "path": "/developers/me/apikeys", "auth": "developer", "description": "Get my API keys"},
                {"method": "GET", "path": "/developers/me/teg-summary", "auth": "developer", "description": "Get TEG summary"},
                {"method": "GET", "path": "/developers/me/agents/{agent_did}/balance", "auth": "developer", "description": "Get agent balance"},
                {"method": "GET", "path": "/developers/stats", "auth": "developer", "description": "Get developer stats"},
                {"method": "GET", "path": "/developers/webhooks", "auth": "developer", "description": "List webhooks"},
                {"method": "GET", "path": "/developers/activity", "auth": "developer", "description": "Get activity"},
                {"method": "POST", "path": "/developers/me/apikeys", "auth": "developer", "description": "Create API key"},
                {"method": "POST", "path": "/developers/me/agents/balances", "auth": "developer", "description": "Get agent balances"},
                {"method": "POST", "path": "/developers/webhooks", "auth": "developer", "description": "Create webhook"},
                {"method": "PUT", "path": "/developers/webhooks/{webhook_id}", "auth": "developer", "description": "Update webhook"},
                # DANGEROUS - REMOVED TO PREVENT DATABASE ISSUES
                # {"method": "DELETE", "path": "/developers/me/apikeys/{key_id}", "auth": "developer", "description": "Delete API key"},
                # DANGEROUS - REMOVED TO PREVENT ACCIDENTAL AGENT DELETION!
                # {"method": "DELETE", "path": "/developers/me/agents/{agent_did}", "auth": "developer", "description": "Delete agent"},
                # DANGEROUS - REMOVED TO PREVENT DATABASE ISSUES
                {"method": "DELETE", "path": "/developers/webhooks/{webhook_id}", "auth": "developer", "description": "Delete webhook"},
                {"method": "PUT", "path": "/developers/me", "auth": "developer", "description": "update_developer_profile"},
                {"method": "GET", "path": "/developers/me/activity", "auth": "developer", "description": "get_developer_activity_events"},
                {"method": "DELETE", "path": "/developers/me/apikeys/{key_id}", "auth": "developer", "description": "delete_api_key"},
                {"method": "DELETE", "path": "/developers/me/agents/{agent_did}", "auth": "developer", "description": "delete_developer_agent"},
                {"method": "POST", "path": "/developers/webhooks/{webhook_id}/test", "auth": "developer", "description": "test_developer_webhook"},
                {"method": "GET", "path": "/developers/webhooks/{webhook_id}/deliveries", "auth": "developer", "description": "list_webhook_deliveries"},
            ],
            "disputes": [
                {"method": "GET", "path": "/disputes/", "auth": "developer", "description": "List all disputes"},
                {"method": "GET", "path": "/disputes/{dispute_id}", "auth": "developer", "description": "Get dispute"},
                {"method": "GET", "path": "/disputes/agent/{agent_did}", "auth": "agent", "description": "Get agent disputes"},
                {"method": "POST", "path": "/disputes/", "auth": "agent", "description": "Create dispute"},
                {"method": "POST", "path": "/disputes/{dispute_id}/evidence", "auth": "agent", "description": "Submit evidence"},
            ],
            "disputes_enhanced": [  # Fully implemented Beta Strike system
                {"method": "POST", "path": "/disputes/enhanced/log", "auth": "agent", "description": "File Beta Strike dispute"},
            ],
            "federation_peers": [
                {"method": "GET", "path": "/federation/peers/", "auth": "none", "description": "List public peers"},
                # REMOVED - Endpoint not working properly in test environment
                # {"method": "GET", "path": "/federation/peers/{peer_id}", "auth": "none", "description": "Get peer details"},
                {"method": "GET", "path": "/federation/peers/my/registrations", "auth": "developer", "description": "My registrations"},
                {"method": "POST", "path": "/federation/peers/", "auth": "developer", "description": "Register peer"},
                {"method": "PUT", "path": "/federation/peers/{peer_id}", "auth": "developer", "description": "Update peer"},
                # DANGEROUS - REMOVED TO PREVENT DATABASE ISSUES
                # {"method": "DELETE", "path": "/federation/peers/{peer_id}", "auth": "developer", "description": "Deactivate peer"},
            ],
            "federation_public": [
                {"method": "GET", "path": "/federation/health-check", "auth": "none", "description": "Federation health"},
                {"method": "GET", "path": "/federation/info", "auth": "none", "description": "Federation info"},
                {"method": "GET", "path": "/federation/network-stats", "auth": "none", "description": "Network stats"},
            ],
            "federation_query": [  # Fully working - internal endpoint
                {"method": "POST", "path": "/internal/federation/query", "auth": "token", "description": "Execute federation query"},
            ],
            "federation_disputes": [  # OWL25: Cross-registry dispute settlement
                {"method": "POST", "path": "/federation/disputes/slash-request", "auth": "mtls", "description": "Receive slash request from origin registry"},
                {"method": "POST", "path": "/federation/disputes/slash-confirmation", "auth": "mtls", "description": "Receive slash confirmation from defendant registry"},
                {"method": "GET", "path": "/federation/disputes/settlements", "auth": "developer", "description": "List cross-registry settlements"},
                {"method": "GET", "path": "/federation/disputes/settlements/{settlement_id}", "auth": "developer", "description": "Get settlement details"},
                {"method": "POST", "path": "/federation/disputes/settlements/{settlement_id}/approve", "auth": "developer", "description": "Admin approve pending settlement"},
                {"method": "POST", "path": "/federation/disputes/settlements/{settlement_id}/reject", "auth": "developer", "description": "Admin reject pending settlement"},
                {"method": "GET", "path": "/federation/disputes/peer-slash-config", "auth": "developer", "description": "List peer auto-slash configurations"},
                {"method": "PUT", "path": "/federation/disputes/peer-slash-config/{peer_id}", "auth": "developer", "description": "Update peer auto-slash configuration"},
            ],
            "federation_sync": [  # Fully working - requires mTLS auth
                {"method": "GET", "path": "/federation/peers", "auth": "mtls", "description": "Get sync peers"},
                {"method": "GET", "path": "/federation/agent-cards", "auth": "mtls", "description": "Get agent cards"},
                {"method": "GET", "path": "/federation/sync-status", "auth": "mtls", "description": "Get sync status"},
                {"method": "POST", "path": "/federation/sync-request", "auth": "mtls", "description": "Request sync"},
            ],
            "governance": [
                {"method": "GET", "path": "/governance/proposals", "auth": "none", "description": "List proposals"},
                {"method": "GET", "path": "/governance/proposals/{proposal_id}", "auth": "none", "description": "Get proposal"},
                {"method": "GET", "path": "/governance/voting-power", "auth": "agent", "description": "Get voting power"},
                {"method": "GET", "path": "/governance/stats", "auth": "none", "description": "Get governance stats"},
                {"method": "POST", "path": "/governance/proposals", "auth": "agent", "description": "Create proposal"},
                {"method": "POST", "path": "/governance/proposals/{proposal_id}/vote", "auth": "agent", "description": "Vote on proposal"},
                {"method": "POST", "path": "/governance/proposals/{proposal_id}/tally", "auth": "agent", "description": "Tally votes"},
                {"method": "GET", "path": "/governance/proposals/{proposal_id}/votes", "auth": "developer", "description": "get_proposal_votes"},
                {"method": "GET", "path": "/governance/proposals/{proposal_id}/my-vote", "auth": "agent", "description": "get_my_vote_on_proposal"},
                {"method": "GET", "path": "/governance/lock-options", "auth": "developer", "description": "get_lock_options"},
                {"method": "GET", "path": "/governance/auto-tally/config", "auth": "developer", "description": "get_auto_tally_config"},
                {"method": "PUT", "path": "/governance/auto-tally/config", "auth": "developer", "description": "update_auto_tally_config"},
                {"method": "POST", "path": "/governance/federation/propose", "auth": "developer", "description": "federation_propose"},
                {"method": "GET", "path": "/governance/federation/proposals", "auth": "agent", "description": "federation_list_proposals"},
                {"method": "POST", "path": "/governance/federation/proposals/{proposal_id}/vote", "auth": "developer", "description": "federation_vote"},
                {"method": "POST", "path": "/governance/federation/proposals/{proposal_id}/veto", "auth": "developer", "description": "federation_veto"},
            ],
            "metrics": [
                {"method": "GET", "path": "/metrics/agent-metrics/{agent_id}", "auth": "developer", "description": "Get agent metrics"},  # Exists
                {"method": "GET", "path": "/metrics/agent-activity", "auth": "developer", "description": "Agent activity metrics"},
                {"method": "GET", "path": "/metrics/network-health", "auth": "none", "description": "Network health metrics"},
            ],
            "organizations": [  # Organizations & Teams Management - Working!
                {"method": "GET", "path": "/organizations", "auth": "developer", "description": "List Organizations"},
                {"method": "POST", "path": "/organizations", "auth": "developer", "description": "Create Organization"},
                {"method": "GET", "path": "/organizations/{org_id}", "auth": "developer", "description": "Get Organization"},
                {"method": "PUT", "path": "/organizations/{org_id}", "auth": "developer", "description": "Update Organization"},
                {"method": "GET", "path": "/organizations/slug/{slug}", "auth": "developer", "description": "Get Organization By Slug"},
                {"method": "POST", "path": "/organizations/{org_id}/teams", "auth": "developer", "description": "Create Team"},
                {"method": "GET", "path": "/organizations/{org_id}/teams", "auth": "developer", "description": "List Teams"},
                {"method": "GET", "path": "/organizations/{org_id}/teams/{team_id}", "auth": "developer", "description": "Get Team"},
                {"method": "PUT", "path": "/organizations/{org_id}/teams/{team_id}", "auth": "developer", "description": "Update Team"},
                {"method": "GET", "path": "/organizations/{org_id}/members", "auth": "developer", "description": "List Organization Members"},
                {"method": "DELETE", "path": "/organizations/{org_id}/members/{developer_id}", "auth": "developer", "description": "Remove Organization Member"},
                {"method": "POST", "path": "/organizations/{org_id}/invite", "auth": "developer", "description": "Invite Member"},
                {"method": "POST", "path": "/organizations/invitations/{token}/accept", "auth": "developer", "description": "Accept Invitation"},
                {"method": "POST", "path": "/organizations/{org_id}/teams/{team_id}/members", "auth": "developer", "description": "Add Team Member"},
                {"method": "DELETE", "path": "/organizations/{org_id}/teams/{team_id}/members/{developer_id}", "auth": "developer", "description": "Remove Team Member"},
                {"method": "DELETE", "path": "/organizations/{org_id}", "auth": "developer", "description": "Delete Organization"},
                {"method": "DELETE", "path": "/organizations/{org_id}/teams/{team_id}", "auth": "developer", "description": "delete_team"},
                {"method": "GET", "path": "/organizations/{org_id}/agents", "auth": "developer", "description": "list_organization_agents"},
                {"method": "POST", "path": "/organizations/{org_id}/agents/{agent_did}/assign", "auth": "developer", "description": "assign_agent_to_org"},
                {"method": "POST", "path": "/organizations/{org_id}/agents/{agent_did}/unassign", "auth": "developer", "description": "unassign_agent_from_org"},
            ],
            "oauth_federation": [  # RFC 8693 Token Exchange / RFC 7662 Introspection
                {"method": "POST", "path": "/oauth/token/exchange", "auth": "oauth_basic", "description": "RFC 8693 Token Exchange"},
                {"method": "POST", "path": "/oauth/introspect", "auth": "oauth_basic", "description": "RFC 7662 Token Introspection"},
                {"method": "GET", "path": "/oauth/.well-known/jwks.json", "auth": "none", "description": "JSON Web Key Set"},
                {"method": "GET", "path": "/oauth/federation/status", "auth": "developer", "description": "Get federation OAuth status"},
                {"method": "POST", "path": "/oauth/federation/trust", "auth": "developer", "description": "Add trusted registry"},
                {"method": "DELETE", "path": "/oauth/federation/trust/{registry_url}", "auth": "developer", "description": "Remove trusted registry"},
                {"method": "DELETE", "path": "/oauth/federation/trust/{registry_url:path}", "auth": "developer", "description": "remove_trusted_registry"},
            ],
            "onboarding": [  # Exists and working - FIXED paths
                {"method": "POST", "path": "/onboard/bootstrap/request-token", "auth": "developer", "description": "Request bootstrap token"},
                # REMOVED: POST /onboard/register — permanently disabled (410 GONE), use /onboard/create_agent
                {"method": "POST", "path": "/onboard/create_agent", "auth": "none", "description": "Create agent with bootstrap token"},
                # 2026-07-15: /onboard/register row deleted — endpoint is 410 GONE
                # by design (superseded by /onboard/create_agent); listing it
                # guaranteed a red row every run. reset-credentials is destructive
                # (skipped by the destructive classifier in base.py).
                {"method": "POST", "path": "/onboard/agents/{agent_did}/reset-credentials", "auth": "developer", "description": "reset_agent_credentials"},
                {"method": "POST", "path": "/onboard/download-bundle", "auth": "developer", "description": "download_bundle"},
            ],
            "reputation_signal": [  # Exists and working - correct paths
                {"method": "GET", "path": "/token/{transaction_id}/reputation-signal", "auth": "agent", "description": "Check reputation signal"},
                {"method": "POST", "path": "/token/{transaction_id}/reputation-signal", "auth": "agent", "description": "Submit reputation signal"},
            ],
            # OWL32 Phase 8.20: staking removed (all 7 endpoints are dupes of staking_enhanced)
            "staking_enhanced": [
                {"method": "GET", "path": "/staking/balance", "auth": "agent", "description": "Get balance (enhanced)"},
                {"method": "GET", "path": "/staking/status", "auth": "agent", "description": "Get status (enhanced)"},
                {"method": "GET", "path": "/staking/my-stats", "auth": "agent", "description": "Get my stats"},
                {"method": "GET", "path": "/staking/global-stats", "auth": "agent", "description": "Get global stats"},
                {"method": "GET", "path": "/staking/apy-tiers", "auth": "none", "description": "Get lock payout tiers (enhanced)"},
                {"method": "GET", "path": "/staking/my-positions", "auth": "agent", "description": "Get positions (enhanced)"},
                {"method": "GET", "path": "/staking/history", "auth": "agent", "description": "Get history (enhanced)"},
                {"method": "POST", "path": "/staking/stake", "auth": "agent", "description": "Lock units (enhanced)"},
                {"method": "POST", "path": "/staking/unstake", "auth": "agent", "description": "Unlock units (enhanced)"},
                {"method": "POST", "path": "/staking/claim-rewards", "auth": "agent", "description": "Claim lock payouts"},
            ],
            "staking_rewards": [  # Staking Rewards Auto-Distribution System
                {"method": "GET", "path": "/staking/rewards/apy-tiers", "auth": "none", "description": "Get lock payout tier configurations"},
                {"method": "GET", "path": "/staking/rewards/estimate/{agent_did}", "auth": "none", "description": "Estimate lock payouts for agent"},
                {"method": "POST", "path": "/staking/rewards/distribute/manual", "auth": "developer", "description": "Trigger manual distribution (admin)"},
                {"method": "GET", "path": "/staking/rewards/distributions", "auth": "none", "description": "Get distribution run history"},
                {"method": "GET", "path": "/staking/rewards/distributions/{distribution_id}/records", "auth": "none", "description": "Get distribution records"},
                {"method": "GET", "path": "/staking/rewards/agents/{agent_did}/history", "auth": "none", "description": "Get agent payout history"},
                {"method": "GET", "path": "/staking/rewards/agents/{agent_did}/auto-compound", "auth": "none", "description": "Get auto-compound settings"},
                {"method": "PUT", "path": "/staking/rewards/agents/{agent_did}/auto-compound", "auth": "developer", "description": "Update auto-compound settings"},
                {"method": "GET", "path": "/staking/rewards/stats/summary", "auth": "none", "description": "Get distribution stats summary"},
            ],
            "enhanced_tokenomics": [  # NEW - Enhanced tokenomics endpoints from TEG Layer
                {"method": "GET", "path": "/tokenomics/rewards/{agent_did}", "auth": "agent", "description": "Get pending lock payouts"},
                {"method": "GET", "path": "/tokenomics/transactions/{agent_did}", "auth": "agent", "description": "Get transaction history"},
                {"method": "GET", "path": "/tokenomics/treasury", "auth": "agent", "description": "Get treasury information"},
            ],
            "system": [
                {"method": "GET", "path": "/system/activity-feed", "auth": "developer", "description": "Get activity feed"},
                {"method": "GET", "path": "/system/activity-feed/by-type/{event_type}", "auth": "developer", "description": "Get activity by type"},
                {"method": "GET", "path": "/stack-health", "auth": "developer", "description": "stack_health"},
            ],
            "teg_integration": [
                {"method": "GET", "path": "/teg/balance", "auth": "agent", "description": "Get TEG balance"},
                {"method": "GET", "path": "/teg/treasury/balance", "auth": "developer", "description": "Get treasury balance"},
                # OWL32: /teg/transactions moved to teg_transactions (dupe removed)
                {"method": "GET", "path": "/teg/agents/{agent_id}/reputation", "auth": "agent", "description": "Get agent reputation"},
                {"method": "GET", "path": "/teg/fees/config", "auth": "none", "description": "Get fee config"},
                {"method": "GET", "path": "/teg/policies", "auth": "developer", "description": "Get policies"},
                {"method": "GET", "path": "/teg/policies/{policy_id}", "auth": "developer", "description": "Get policy"},
                {"method": "GET", "path": "/teg/policies/compliance/dashboard", "auth": "developer", "description": "Compliance dashboard"},
                {"method": "GET", "path": "/teg/disputes", "auth": "agent", "description": "Get disputes"},
                {"method": "GET", "path": "/teg/disputes/{dispute_log_id}", "auth": "agent", "description": "Get dispute log"},
                {"method": "GET", "path": "/teg/attestations", "auth": "agent", "description": "Get attestations"},
                {"method": "POST", "path": "/teg/transfer", "auth": "agent", "description": "Transfer TEG"},
                {"method": "POST", "path": "/teg/system-transfer", "auth": "agent", "description": "System transfer"},
                {"method": "POST", "path": "/teg/transactions/{transaction_id}/reputation-signal", "auth": "agent", "description": "Add reputation signal"},
                {"method": "POST", "path": "/teg/policies", "auth": "developer", "description": "Create policy"},
                {"method": "POST", "path": "/teg/policies/batch", "auth": "developer", "description": "Batch create policies"},
                {"method": "POST", "path": "/teg/disputes/log", "auth": "agent", "description": "Log dispute"},
                {"method": "POST", "path": "/teg/attestations/submit", "auth": "agent", "description": "Submit attestation"},
                {"method": "PUT", "path": "/teg/policies/{policy_id}", "auth": "developer", "description": "Update policy"},
                # DANGEROUS - REMOVED TO PREVENT DATABASE ISSUES
                # {"method": "DELETE", "path": "/teg/policies/{policy_id}", "auth": "developer", "description": "Delete policy"},
                {"method": "DELETE", "path": "/teg/policies/{policy_id}", "auth": "developer", "description": "delete_teg_policy"},
                {"method": "POST", "path": "/teg/staking/stake", "auth": "agent", "description": "stake_tokens_proxy"},
                {"method": "POST", "path": "/teg/staking/unstake", "auth": "agent", "description": "unstake_tokens_proxy"},
                {"method": "GET", "path": "/teg/staking/balance/{agent_did}", "auth": "developer", "description": "get_staking_balance_proxy"},
                {"method": "GET", "path": "/teg/staking/history/{agent_did}", "auth": "developer", "description": "get_staking_history_proxy"},
                {"method": "GET", "path": "/teg/staking/apy-tiers", "auth": "developer", "description": "get_apy_tiers_proxy"},
                {"method": "POST", "path": "/teg/rewards/claim", "auth": "developer", "description": "claim_rewards_proxy"},
                {"method": "GET", "path": "/teg/rewards/pending/{agent_did}", "auth": "developer", "description": "get_pending_rewards_proxy"},
                {"method": "GET", "path": "/teg/rewards/history/{agent_did}", "auth": "developer", "description": "get_rewards_history_proxy"},
                {"method": "POST", "path": "/teg/disputes/{dispute_id}/resolve", "auth": "agent", "description": "resolve_dispute_proxy"},
                {"method": "GET", "path": "/teg/reputation/rankings", "auth": "developer", "description": "get_reputation_rankings_proxy"},
                {"method": "POST", "path": "/teg/cross-teg-balance-sync", "auth": "developer", "description": "cross_teg_balance_sync"},
                {"method": "POST", "path": "/teg/cross-registry-transfer", "auth": "developer", "description": "cross_registry_transfer"},
                {"method": "POST", "path": "/teg/treasury/mint", "auth": "developer", "description": "mint_tokens"},
                {"method": "POST", "path": "/teg/treasury/fund-agent", "auth": "developer", "description": "fund_agent_from_treasury"},
                {"method": "POST", "path": "/teg/treasury/receive", "auth": "developer", "description": "return_to_treasury"},
                {"method": "POST", "path": "/teg/treasury/cross-teg-fund", "auth": "developer", "description": "cross_teg_treasury_fund"},
                {"method": "POST", "path": "/teg/transactions/batch", "auth": "developer", "description": "batch_transactions"},
            ],
            "teg_integration_jwt_svid": [  # Implemented - requires SPIRE/TEG services
                {"method": "GET", "path": "/teg-jwt-svid/teg/balance", "auth": "agent", "description": "Get balance (JWT-SVID)"},
                {"method": "GET", "path": "/teg-jwt-svid/teg/history", "auth": "agent", "description": "Get history (JWT-SVID)"},
                {"method": "GET", "path": "/teg-jwt-svid/teg/fee-config", "auth": "none", "description": "Get fee config (JWT-SVID)"},
                {"method": "POST", "path": "/teg-jwt-svid/teg/transfer", "auth": "agent", "description": "Transfer (JWT-SVID)"},
            ],
            "teg_integration_mtls": [  # Implemented - requires mTLS/TEG services
                {"method": "GET", "path": "/teg-mtls/teg/balance", "auth": "agent", "description": "Get balance (mTLS)"},
                {"method": "GET", "path": "/teg-mtls/teg/history", "auth": "agent", "description": "Get history (mTLS)"},
                {"method": "GET", "path": "/teg-mtls/teg/fee-config", "auth": "none", "description": "Get fee config (mTLS)"},
                {"method": "POST", "path": "/teg-mtls/teg/transfer", "auth": "agent", "description": "Transfer (mTLS)"},
            ],
            "teg_integration_oauth": [  # Implemented - requires OAuth/TEG services
                {"method": "GET", "path": "/teg-oauth/teg/balance", "auth": "agent", "description": "Get balance (OAuth)"},
                {"method": "GET", "path": "/teg-oauth/teg/history", "auth": "agent", "description": "Get history (OAuth)"},
                {"method": "GET", "path": "/teg-oauth/teg/fee-config", "auth": "none", "description": "Get fee config (OAuth)"},
                {"method": "POST", "path": "/teg-oauth/teg/transfer", "auth": "agent", "description": "Transfer (OAuth)"},
                # Note: /teg-oauth/teg/system-transfer does NOT exist (404)
            ],
            "teg_summary_enhanced": [  # OWL32: /developers/me/teg-summary dupe removed (kept in developers)
                {"method": "GET", "path": "/developers/me/teg-summary/treasury", "auth": "developer", "description": "Get treasury summary"},
            ],
            # OWL32 Phase 8.20: tokenomics removed (all 3 endpoints are dupes of enhanced_tokenomics)
            "teg_transactions": [  # FIXED paths - correct structure
                {"method": "GET", "path": "/teg/transactions", "auth": "agent", "description": "List transactions"},
                {"method": "GET", "path": "/teg/transaction/{transaction_id}", "auth": "developer", "description": "Get transaction"},
                {"method": "GET", "path": "/teg/fees", "auth": "none", "description": "Get fee structure"},
                {"method": "GET", "path": "/teg/price", "auth": "none", "description": "Get TEG price"},
                {"method": "GET", "path": "/teg/transactions/advanced", "auth": "agent", "description": "Advanced transaction list"},
                {"method": "GET", "path": "/teg/transactions/analytics", "auth": "developer", "description": "Transaction analytics"},
                {"method": "GET", "path": "/teg/transactions/history/{agent_id}", "auth": "agent", "description": "Agent transaction history"},
                {"method": "GET", "path": "/teg/transactions/export", "auth": "developer", "description": "Export transactions"},
                {"method": "POST", "path": "/teg/batch-transfer", "auth": "developer", "description": "Batch transfer"},
                # REMOVED - Endpoint not implemented
                # {"method": "POST", "path": "/teg/transactions/batch", "auth": "agent", "description": "Batch transactions"},
            ],
            "utils": [
                {"method": "POST", "path": "/utils/validate-card", "auth": "developer", "description": "Validate agent card"},
            ],
            "websocket": [
                {"method": "WS", "path": "/ws/agent/{agent_id}", "auth": "agent", "description": "Agent WebSocket"},
                {"method": "WS", "path": "/ws/developer", "auth": "developer", "description": "Developer WebSocket"},
                {"method": "WS", "path": "/ws/events", "auth": "developer", "description": "Events WebSocket"},
                {"method": "WS", "path": "/ws/logs", "auth": "developer", "description": "Logs WebSocket"},
                {"method": "WS", "path": "/ws/metrics", "auth": "developer", "description": "Metrics WebSocket"},
                {"method": "WS", "path": "/ws/notifications", "auth": "developer", "description": "Notifications WebSocket"},
            ],
            # OWL32 Phase 8.20: batch_implementation removed (all 8 endpoints are dupes of developers + staking_enhanced)

            # ── NEW CATEGORIES (OWL Autonomous Testing Campaign 2026-03-08) ──────

            "enforcement_admin": [  # TITANIUM VAULT D2: §4.9 — admin enforcement lifecycle
                # Reads first (safe)
                {"method": "GET",  "path": "/admin/enforcement/policy/defaults",                          "auth": "developer", "description": "Get factory default enforcement policy"},
                {"method": "GET",  "path": "/admin/enforcement/policy",                                   "auth": "developer", "description": "Get active enforcement policy"},
                {"method": "PUT",  "path": "/admin/enforcement/policy",                                   "auth": "developer", "description": "Update enforcement policy (admin override)"},
                {"method": "GET",  "path": "/admin/enforcement/agents/{agent_did}/status",               "auth": "developer", "description": "Full enforcement status summary for agent"},
                # Reversible reward operations
                {"method": "POST", "path": "/admin/enforcement/agents/{agent_did}/pause-rewards",        "auth": "developer", "description": "Manually pause lock payouts"},
                {"method": "POST", "path": "/admin/enforcement/agents/{agent_did}/resume-rewards",       "auth": "developer", "description": "Resume paused lock payouts"},
                # Offense + pending actions (action_id captured if available)
                {"method": "POST", "path": "/admin/enforcement/agents/{agent_did}/record-offense",       "auth": "developer", "description": "Manually record an offense and trigger escalation"},
                {"method": "GET",  "path": "/admin/enforcement/pending",                                  "auth": "developer", "description": "List pending enforcement actions requiring approval"},
                {"method": "POST", "path": "/admin/enforcement/pending/{action_id}/reject",              "auth": "developer", "description": "Reject a pending enforcement action"},
                {"method": "POST", "path": "/admin/enforcement/pending/{action_id}/approve",             "auth": "developer", "description": "Approve and execute a pending enforcement action"},
                # Slash (dry-run safe; execute uses minimal 10 AVT)
                {"method": "GET",  "path": "/admin/enforcement/agents/{agent_did}/slash-preview?amount=10", "auth": "developer", "description": "Preview force-unlock impact (dry run)"},
                {"method": "POST", "path": "/admin/enforcement/agents/{agent_did}/slash-stake",          "auth": "developer", "description": "Execute force-unlock slash on agent"},
                # Suspend then immediately reinstate (keeps sandbox agent healthy)
                {"method": "POST", "path": "/admin/enforcement/agents/{agent_did}/suspend",              "auth": "developer", "description": "Suspend agent (freeze all operations)"},
                {"method": "POST", "path": "/admin/enforcement/agents/{agent_did}/reinstate",            "auth": "developer", "description": "Reinstate suspended agent"},
            ],

            "enforcement_agent": [  # TITANIUM VAULT D2: §4.10 — agent self-service enforcement
                # Reads first
                {"method": "GET",  "path": "/enforcement/my-status",             "auth": "agent",     "description": "Agent views own enforcement status"},
                {"method": "GET",  "path": "/fees/current-rate",                 "auth": "developer", "description": "Current transaction fee rate (public)"},
                # Bond deposit then status (deposit is prereq for status)
                {"method": "POST", "path": "/agents/reputation-bond/deposit",    "auth": "agent",     "description": "Deposit reputation bond (locks AVT as commitment signal)"},
                {"method": "GET",  "path": "/agents/reputation-bond/status",     "auth": "agent",     "description": "Check bond maturity progress"},
            ],

            "reputation": [  # EigenTrust++ Phase 2 — trust computation pipeline
                # Trigger first (seeds GlobalTrustVector rows for subsequent reads)
                {"method": "POST", "path": "/reputation/admin/trigger-computation", "auth": "developer", "description": "Force immediate EigenTrust++ epoch (admin)"},
                {"method": "GET",  "path": "/reputation/computation-status",        "auth": "developer", "description": "EigenTrust++ computation status"},
                # Per-agent reads (trust-score may 404 if epoch not yet complete — transient)
                {"method": "GET",  "path": "/reputation/{agent_did}/trust-score",   "auth": "developer", "description": "EigenTrust++ score for agent"},
                {"method": "GET",  "path": "/reputation/{agent_did}/trust-graph",   "auth": "developer", "description": "Local trust relationships for agent"},
                {"method": "GET",  "path": "/reputation/{agent_did}/volume-profile", "auth": "developer", "description": "Transaction volume profile for agent"},
                {"method": "GET", "path": "/reputation/{did}/trust-score", "auth": "developer", "description": "get_trust_score"},
                {"method": "GET", "path": "/reputation/{did}/trust-graph", "auth": "developer", "description": "get_trust_graph"},
                {"method": "GET", "path": "/reputation/{did}/volume-profile", "auth": "developer", "description": "get_volume_profile"},
                {"method": "GET", "path": "/reputation/cross-frame", "auth": "developer", "description": "get_cross_frame_reputation"},
            ],

            "mcp_health": [  # MCP server health — no auth, always reachable
                {"method": "GET", "path": "/mcp/health",       "auth": "none", "description": "MCP server health check"},
                {"method": "GET", "path": "/mcp/admin/health", "auth": "none", "description": "Admin MCP server health check"},
            ],

            # ─────────────────────────────────────────────────────────────────
            # Phase A (2026-04-22) — Read-only diagnostics coverage
            # Added after Appendix J API-tester repair proved the cascade works.
            # These 4 categories were shipped 2026-04-18/21 without tester entries.
            # ─────────────────────────────────────────────────────────────────

            "admin_diagnostics": [  # Command Center (2026-04-18, f050)
                {"method": "GET",  "path": "/admin/diagnostics/targets",                     "auth": "developer", "description": "List all diagnostic targets (env-filtered)"},
                {"method": "GET",  "path": "/admin/diagnostics/checks",                      "auth": "developer", "description": "List all available diagnostic checks"},
                {"method": "POST", "path": "/admin/diagnostics/run",                         "auth": "developer", "description": "Run a subset of (checks × targets)"},
                {"method": "POST", "path": "/admin/diagnostics/run-all",                     "auth": "developer", "description": "Run all applicable checks against one target"},
                {"method": "GET",  "path": "/admin/diagnostics/config/{target_id}",          "auth": "developer", "description": "Read masked config slices for a target"},
                {"method": "GET",  "path": "/admin/diagnostics/actions",                     "auth": "developer", "description": "List available remediation actions"},
                {"method": "POST", "path": "/admin/diagnostics/actions/{action_id}",         "auth": "developer", "description": "Invoke a remediation action against a target"},
            ],

            "federation_topology": [  # WS1 + WS2 (2026-04-21)
                {"method": "GET",  "path": "/admin/federation/topology-overview",            "auth": "developer", "description": "Tier-bucketed peer topology (mainframes + operators + chain)"},
                {"method": "GET",  "path": "/admin/federation/topology/peers/{peer_id}/events", "auth": "developer", "description": "Peer event log from EventStore"},
                {"method": "POST", "path": "/admin/federation/topology/peers/{peer_id}/probe", "auth": "developer", "description": "Probe peer health (HTTP + SPIRE)"},
            ],

            "operator_lifecycle": [  # D5a+D5b (2026-04-21)
                {"method": "GET",  "path": "/operators/me/lifecycle",                        "auth": "developer", "description": "Operator self-view: lifecycle state stack"},
                {"method": "GET",  "path": "/admin/operators/lifecycle-overview",            "auth": "developer", "description": "Admin view: lifecycle + drift for every operator"},
            ],

            "consul_admin": [  # CONSUL — federation compliance (2026-04-19, f049)
                {"method": "GET",  "path": "/admin/federation/compliance/enforcement-mode",      "auth": "developer", "description": "Read current enforcement mode"},
                {"method": "GET",  "path": "/admin/federation/compliance/overview",              "auth": "developer", "description": "Compliance overview: all peers × operators"},
                {"method": "GET",  "path": "/admin/federation/compliance/events",                "auth": "developer", "description": "Compliance event log"},
                {"method": "GET",  "path": "/admin/federation/compliance/preview-quarantine",    "auth": "developer", "description": "Preview quarantine decisions (dry-run)"},
            ],

            # ─────────────────────────────────────────────────────────────────
            # Phase B (2026-04-22) — Admin management plane
            # M1+M2 shipped 2026-04-20 without tester entries.
            # ─────────────────────────────────────────────────────────────────

            "admin_developers": [  # M1 (2026-04-20)
                {"method": "GET",    "path": "/admin/developers",                                    "auth": "developer", "description": "List developers (filter/page)"},
                {"method": "GET",    "path": "/admin/developers/{developer_id}",                     "auth": "developer", "description": "Developer detail"},
                {"method": "POST",   "path": "/admin/developers/{developer_id}/suspend",             "auth": "developer", "description": "Suspend developer (admin_enforcement)"},
                {"method": "POST",   "path": "/admin/developers/{developer_id}/reinstate",           "auth": "developer", "description": "Reinstate suspended developer"},
                {"method": "POST",   "path": "/admin/developers/{developer_id}/force-password-reset","auth": "developer", "description": "Force password reset (admin_support)"},
                {"method": "POST",   "path": "/admin/developers/{developer_id}/disable-2fa",         "auth": "developer", "description": "Disable 2FA for dev (admin_support)"},
                {"method": "POST",   "path": "/admin/developers/{developer_id}/force-email-verify",  "auth": "developer", "description": "Force email verified (admin_support)"},
                {"method": "POST",   "path": "/admin/developers/{developer_id}/revoke-api-keys",     "auth": "developer", "description": "Revoke all API keys (admin_support)"},
                {"method": "DELETE", "path": "/admin/developers/{developer_id}",                     "auth": "developer", "description": "Hard-delete developer (admin_platform)"},
                {"method": "PUT",    "path": "/admin/developers/{developer_id}/admin-flags",         "auth": "developer", "description": "Update granular admin flags (admin_platform)"},
                {"method": "GET",    "path": "/admin/developers/{developer_id}/activity",            "auth": "developer", "description": "Recent EventStore audit activity"},
            ],

            "admin_agents": [  # M2 (2026-04-20)
                {"method": "GET",    "path": "/admin/agents",                              "auth": "developer", "description": "List agents (filter/page)"},
                {"method": "GET",    "path": "/admin/agents/orphans",                      "auth": "developer", "description": "List orphaned agents"},
                {"method": "GET",    "path": "/admin/agents/{agent_did}",                  "auth": "developer", "description": "Agent detail"},
                {"method": "POST",   "path": "/admin/agents/{target_agent_did}/transfer-ownership","auth": "developer", "description": "Transfer agent to another developer (targets counterparty)"},
                {"method": "POST",   "path": "/admin/agents/{target_agent_did}/rotate-credentials","auth": "developer", "description": "Rotate agent client secret (admin_enforcement, targets counterparty)"},
                {"method": "POST",   "path": "/admin/agents/{target_agent_did}/force-mtls-enrol", "auth": "developer", "description": "Force mTLS enrollment (targets counterparty)"},
                {"method": "DELETE", "path": "/admin/agents/{target_agent_did}",                  "auth": "developer", "description": "Hard-delete agent (admin_enforcement, targets counterparty)"},
                {"method": "POST",   "path": "/admin/agents/bulk/suspend",                 "auth": "developer", "description": "Bulk suspend agents"},
                {"method": "POST", "path": "/admin/agents/{agent_did}/transfer-ownership", "auth": "developer", "description": "transfer_ownership"},
                {"method": "POST", "path": "/admin/agents/{agent_did}/rotate-credentials", "auth": "developer", "description": "rotate_credentials"},
                {"method": "POST", "path": "/admin/agents/{agent_did}/force-mtls-enrol", "auth": "developer", "description": "force_mtls_enrol"},
                {"method": "DELETE", "path": "/admin/agents/{agent_did}", "auth": "developer", "description": "hard_delete_agent"},
            ],

            # ─────────────────────────────────────────────────────────────────
            # Phase C (2026-04-22) — Federation state changes
            # frame_invitations (WS3, 2026-04-21) + consul mutating endpoints.
            # ─────────────────────────────────────────────────────────────────

            "frame_invitations": [  # WS3 + WS3.5 (2026-04-21)
                # Public (no auth, rate-limited) — remote frame POSTs these
                {"method": "POST",   "path": "/federation/frame-invitations",                              "auth": "none",      "description": "Public: create inbound frame invitation (5/hour)"},
                {"method": "POST",   "path": "/federation/frame-invitations/{invitation_id}/finalize",     "auth": "none",      "description": "Public: bilateral finalize callback (single-use)"},
                # Admin (admin_federation)
                {"method": "GET",    "path": "/admin/federation/frame-invitations",                       "auth": "developer", "description": "List all frame invitations (filter by status)"},
                {"method": "GET",    "path": "/admin/federation/frame-invitations/{invitation_id}",        "auth": "developer", "description": "Frame invitation detail"},
                {"method": "POST",   "path": "/admin/federation/frame-invitations/{invitation_id}/approve","auth": "developer", "description": "Approve invitation + import bundle + finalize"},
                {"method": "POST",   "path": "/admin/federation/frame-invitations/{invitation_id}/reject", "auth": "developer", "description": "Reject invitation with reason"},
                {"method": "POST",   "path": "/admin/federation/frame-invitations/{invitation_id}/finalize-retry","auth": "developer", "description": "Retry finalize POST to remote (approved+pending finalize)"},
                {"method": "POST",   "path": "/admin/federation/frames/{peer_id}/revoke",                 "auth": "developer", "description": "Revoke an established frame federation"},
                {"method": "POST",   "path": "/admin/federation/frames/{peer_id}/resync-eventstore",      "auth": "developer", "description": "SF-4 EventStore cross-frame peer resync"},
                {"method": "GET",    "path": "/admin/federation/frames/spire-status",                    "auth": "developer", "description": "SPIRE trust-bundle + federation-list status"},
                {"method": "GET",    "path": "/admin/eventstore/cross-frame-peers",                      "auth": "developer", "description": "Proxy: list cross_frame_peers rows on this frame's ES"},
                {"method": "GET",    "path": "/admin/eventstore/federation-operators",                   "auth": "developer", "description": "Proxy: list federation_operators on this frame's ES"},
            ],

            # Extra consul_admin mutating endpoints (Phase C half of f049)
            "consul_admin_mutations": [
                {"method": "POST",   "path": "/admin/federation/compliance/enforcement-mode",              "auth": "developer", "description": "Set enforcement mode (off/dry_run/enforcing)"},
                {"method": "POST",   "path": "/admin/federation/compliance/peers/{peer_id}/poll-now",      "auth": "developer", "description": "Trigger on-demand compliance poll (dry-run default)"},
            ],

            # ─────────────────────────────────────────────────────────────────
            # Phase D (2026-04-22) — Financial flows
            # funding_requests (f038/f042) + token_bridge (SF-3).
            # Bridge mint/unlock fails until Phase 12 (operators) — expected.
            # ─────────────────────────────────────────────────────────────────

            "funding_requests": [  # f038/f042 funding workflow
                {"method": "POST", "path": "/funding/request",                             "auth": "agent",     "description": "Developer/agent creates funding request"},
                {"method": "GET",  "path": "/funding/my-requests",                         "auth": "agent",     "description": "Agent's own funding requests"},
                {"method": "GET",  "path": "/admin/funding/pending",                       "auth": "developer", "description": "Admin: list pending requests (admin_treasury)"},
                {"method": "GET",  "path": "/admin/funding/all",                           "auth": "developer", "description": "Admin: list all requests"},
                {"method": "POST", "path": "/admin/funding/{request_id}/approve",          "auth": "developer", "description": "Admin: approve + fund from treasury"},
                {"method": "POST", "path": "/admin/funding/{request_id}/reject",           "auth": "developer", "description": "Admin: reject funding request"},
            ],

            "token_bridge": [  # SF-3 cross-frame wrapped token (f040)
                {"method": "POST", "path": "/bridge/transfer",                             "auth": "agent",     "description": "Cross-frame AVT transfer (source side locks, target mints wrapped)"},
                {"method": "POST", "path": "/bridge/mint-wrapped",                         "auth": "developer", "description": "Admin: mint wrapped units (admin_treasury, needs operator)"},
                {"method": "POST", "path": "/bridge/redeem",                               "auth": "agent",     "description": "Redeem wrapped units for the original units on the source frame"},
                {"method": "POST", "path": "/bridge/unlock",                               "auth": "developer", "description": "Admin: unlock an escrowed transfer (admin_treasury)"},
                {"method": "GET",  "path": "/bridge/status/{bridge_tx_id}",                "auth": "developer", "description": "Check bridge transfer status"},
            ],

            "a2a_payment": [
                {"method": "POST", "path": "/a2a-payment/authorize", "auth": "agent", "description": "authorize_payment"},
                {"method": "POST", "path": "/a2a-payment/verify", "auth": "agent", "description": "verify_payment"},
                {"method": "POST", "path": "/a2a-payment/settle", "auth": "agent", "description": "settle_payment"},
                {"method": "POST", "path": "/a2a-payment/release", "auth": "agent", "description": "release_payment"},
                {"method": "GET", "path": "/a2a-payment/my-tokens", "auth": "agent", "description": "list_my_tokens"},
            ],
            "achievements": [
                {"method": "POST", "path": "/achievements/record", "auth": "developer", "description": "record_achievement"},
                {"method": "GET", "path": "/achievements/me", "auth": "developer", "description": "get_my_achievements"},
                {"method": "POST", "path": "/achievements/claim-pending", "auth": "developer", "description": "claim_pending_payouts"},
                {"method": "GET", "path": "/achievements/catalog", "auth": "developer", "description": "get_achievement_catalog"},
            ],
            "arena": [
                {"method": "GET", "path": "/arena/matches", "auth": "developer", "description": "list_matches"},
                {"method": "POST", "path": "/arena/matches", "auth": "admin", "description": "create_match (D6-634: administrators only)"},
                {"method": "GET", "path": "/arena/matches/{match_id}", "auth": "developer", "description": "get_match"},
                {"method": "GET", "path": "/arena/matches/{match_id}/map", "auth": "developer", "description": "get_map"},
                {"method": "GET", "path": "/arena/matches/{match_id}/bets", "auth": "developer", "description": "get_bets"},
                {"method": "GET", "path": "/arena/leaderboard/{game_type}", "auth": "developer", "description": "game_leaderboard"},
                {"method": "GET", "path": "/arena/agent-stats/{agent_did:path}", "auth": "developer", "description": "agent_game_stats"},
            ],
            # ── astraeus category REMOVED 2026-05-21 ──
            # Commander directive 2026-05-21: games marked for removal. The 50
            # astraeus endpoints lived only in this hand-maintained catalog (not in
            # live OpenAPI); they had no test prereqs and were wholesale-EF-stamped.
            # New catalog_sync.py excludes /astraeus/** via overrides.yaml glob.
            "circuits": [
                {"method": "GET", "path": "/circuits/{circuit_id:path}/acir", "auth": "developer", "description": "get_circuit_acir"},
                {"method": "GET", "path": "/circuits/{circuit_id:path}/source", "auth": "developer", "description": "get_circuit_source"},
                {"method": "GET", "path": "/circuits/{circuit_id:path}/nargo-toml", "auth": "developer", "description": "get_circuit_nargo_toml"},
                {"method": "GET", "path": "/circuits/", "auth": "developer", "description": "list_circuits"},
            ],
            "federation": [
                {"method": "GET", "path": "/federation/peers/{peer_id}", "auth": "developer", "description": "get_public_peer_registry"},
                {"method": "DELETE", "path": "/federation/peers/{peer_id}", "auth": "developer", "description": "deactivate_owned_peer_registry"},
                {"method": "POST", "path": "/federation/sync/trigger", "auth": "developer", "description": "trigger_sync"},
                {"method": "GET", "path": "/federation/registries", "auth": "developer", "description": "list_federated_registries"},
                {"method": "GET", "path": "/federation/registry/{peer_id_or_name}/health-profile", "auth": "developer", "description": "get_registry_health_profile"},
            ],
            "notifications": [
                {"method": "GET", "path": "/notifications/unread", "auth": "developer", "description": "get_unread_notifications"},
                {"method": "POST", "path": "/notifications/{broadcast_id}/read", "auth": "developer", "description": "mark_notification_read"},
            ],
            "operators": [
                {"method": "POST", "path": "/operator-applications", "auth": "developer", "description": "submit_operator_application"},
                {"method": "GET", "path": "/operators/my-bundle", "auth": "agent", "description": "download_operator_bundle"},
                {"method": "POST", "path": "/operators/activate", "auth": "developer", "description": "activate_operator"},
                {"method": "GET", "path": "/operators/my-status", "auth": "developer", "description": "get_operator_status"},
                {"method": "POST", "path": "/operators/request-revocation", "auth": "developer", "description": "request_self_revocation"},
            ],
            "operators_admin": [
                {"method": "GET", "path": "/admin/operator-applications", "auth": "developer", "description": "list_operator_applications"},
                {"method": "GET", "path": "/admin/operator-applications/{application_id}", "auth": "developer", "description": "get_operator_application"},
                {"method": "POST", "path": "/admin/operator-applications/{application_id}/approve", "auth": "developer", "description": "approve_operator_application"},
                {"method": "POST", "path": "/admin/operator-applications/{application_id}/reject", "auth": "developer", "description": "reject_operator_application"},
                {"method": "GET", "path": "/admin/operator-applications/{application_id}/bundle", "auth": "developer", "description": "admin_download_bundle"},
                {"method": "POST", "path": "/admin/operator-applications/{application_id}/revoke-operator", "auth": "developer", "description": "revoke_operator_access"},
                {"method": "POST", "path": "/admin/operator-applications/{application_id}/suspend-operator", "auth": "developer", "description": "suspend_operator"},
                {"method": "POST", "path": "/admin/operator-applications/{application_id}/reinstate-operator", "auth": "developer", "description": "reinstate_operator"},
                {"method": "POST", "path": "/admin/operator-applications/{application_id}/rotate-pull-token", "auth": "developer", "description": "rotate_operator_pull_token"},
                {"method": "POST", "path": "/admin/operator-applications/backfill-pull-tokens", "auth": "developer", "description": "backfill_pull_tokens"},
            ],
            "other": [
                {"method": "GET", "path": "/openapi.json", "auth": "developer", "description": "openapi"},
                {"method": "GET", "path": "/{agent_did}/relay/status", "auth": "developer", "description": "relay_status"},
                {"method": "POST", "path": "/{agent_did}/relay/action", "auth": "developer", "description": "relay_action"},
            ],
            "public": [
                {"method": "GET", "path": "/community/announcements", "auth": "developer", "description": "list_community_announcements"},
                {"method": "GET", "path": "/public/eventstore-stats", "auth": "developer", "description": "public_eventstore_stats"},
                {"method": "GET", "path": "/public/eventstore-recent", "auth": "developer", "description": "public_eventstore_recent"},
                {"method": "GET", "path": "/public/topology", "auth": "developer", "description": "public_topology"},
                {"method": "GET", "path": "/public/showcase/agents", "auth": "developer", "description": "showcase_list_agents"},
                {"method": "POST", "path": "/public/showcase/call", "auth": "developer", "description": "showcase_call"},
                {"method": "GET", "path": "/public/registry-config", "auth": "developer", "description": "public_registry_config"},
            ],
            "sandbox": [
                {"method": "DELETE", "path": "/sandbox/a/{path:path}", "auth": "developer", "description": "proxy_sandbox_a"},
                {"method": "PUT", "path": "/sandbox/a/{path:path}", "auth": "developer", "description": "proxy_sandbox_a"},
                {"method": "POST", "path": "/sandbox/a/{path:path}", "auth": "developer", "description": "proxy_sandbox_a"},
                {"method": "GET", "path": "/sandbox/a/{path:path}", "auth": "developer", "description": "proxy_sandbox_a"},
                {"method": "PATCH", "path": "/sandbox/a/{path:path}", "auth": "developer", "description": "proxy_sandbox_a"},
                {"method": "DELETE", "path": "/sandbox/b/{path:path}", "auth": "developer", "description": "proxy_sandbox_b"},
                {"method": "PUT", "path": "/sandbox/b/{path:path}", "auth": "developer", "description": "proxy_sandbox_b"},
                {"method": "POST", "path": "/sandbox/b/{path:path}", "auth": "developer", "description": "proxy_sandbox_b"},
                {"method": "GET", "path": "/sandbox/b/{path:path}", "auth": "developer", "description": "proxy_sandbox_b"},
                {"method": "PATCH", "path": "/sandbox/b/{path:path}", "auth": "developer", "description": "proxy_sandbox_b"},
                {"method": "GET", "path": "/sandbox/es/{path:path}", "auth": "developer", "description": "proxy_sandbox_es"},
            ],
            "support": [
                {"method": "POST", "path": "/support/tickets", "auth": "developer", "description": "create_ticket"},
                {"method": "GET", "path": "/support/tickets", "auth": "developer", "description": "list_my_tickets"},
                {"method": "GET", "path": "/support/tickets/{ticket_id}", "auth": "developer", "description": "get_ticket"},
                {"method": "POST", "path": "/support/tickets/{ticket_id}/reply", "auth": "developer", "description": "reply_to_ticket"},
            ],
            "webhooks": [
                {"method": "POST", "path": "/webhooks", "auth": "developer", "description": "create_webhook"},
                {"method": "GET", "path": "/webhooks", "auth": "developer", "description": "list_webhooks"},
                {"method": "GET", "path": "/webhooks/{webhook_id}", "auth": "developer", "description": "get_webhook"},
                {"method": "PUT", "path": "/webhooks/{webhook_id}", "auth": "developer", "description": "update_webhook"},
                {"method": "DELETE", "path": "/webhooks/{webhook_id}", "auth": "developer", "description": "delete_webhook"},
                {"method": "GET", "path": "/webhooks/{webhook_id}/deliveries", "auth": "developer", "description": "list_deliveries"},
                {"method": "POST", "path": "/webhooks/{webhook_id}/test", "auth": "developer", "description": "test_webhook"},
                {"method": "GET", "path": "/webhooks/events/supported", "auth": "developer", "description": "list_supported_events"},
            ],
            # 2026-04-25 — Multi-frame scenario flow categories.
            # Each maps to an APITestBase subclass exposed via the flow framework
            # (FLOW_CATEGORIES → POST /admin/api-test/test-flow). The endpoints
            # listed are the ones the flow exercises end-to-end. Most of these
            # endpoints exist in other categories too (governance, staking,
            # teg_integration, agent_locations, federation_sync, admin) — the
            # listings here are the convention required by the flow framework
            # so "Run All Tests" lights up the right cards in the UI grid.
            "multiframe_bfs": [
                {"method": "GET", "path": "/agents/locations/trusted-registries", "auth": "developer", "description": "BFS topology probe (multi-frame flow)"},
                {"method": "POST", "path": "/federation/sync/trigger", "auth": "developer", "description": "Trigger federation sync (multi-frame flow)"},
                {"method": "POST", "path": "/teg/cross-registry-transfer", "auth": "agent", "description": "Cross-registry AVT transfer (multi-frame flow)"},
                {"method": "GET", "path": "/teg/balance", "auth": "agent", "description": "Sender balance check (multi-frame flow)"},
            ],
            "multiframe_eigentrust": [
                {"method": "GET", "path": "/admin/simulation/status", "auth": "developer", "description": "Simulation status (multi-frame flow)"},
                {"method": "POST", "path": "/admin/simulation/start", "auth": "developer", "description": "Start simulation (multi-frame flow)"},
                {"method": "GET", "path": "/admin/simulation/logs", "auth": "developer", "description": "Simulation logs (multi-frame flow)"},
                {"method": "POST", "path": "/admin/simulation/stop", "auth": "developer", "description": "Stop simulation (multi-frame flow)"},
            ],
            "multiframe_governance": [
                {"method": "POST", "path": "/staking/stake", "auth": "agent", "description": "Lock units for voting weight (multi-frame flow)"},
                {"method": "POST", "path": "/governance/proposals", "auth": "agent", "description": "Create local proposal (multi-frame flow)"},
                {"method": "POST", "path": "/governance/proposals/{proposal_id}/vote", "auth": "agent", "description": "Vote on local proposal (multi-frame flow)"},
                {"method": "POST", "path": "/governance/proposals/{proposal_id}/tally", "auth": "agent", "description": "Tally local proposal (multi-frame flow)"},
                {"method": "GET", "path": "/governance/proposals/{proposal_id}", "auth": "agent", "description": "Get proposal status (multi-frame flow)"},
                {"method": "POST", "path": "/governance/federation/propose", "auth": "developer", "description": "Elevate to federation proposal (multi-frame flow)"},
                {"method": "POST", "path": "/governance/federation/proposals/{proposal_id}/vote", "auth": "agent", "description": "Vote on federation proposal (multi-frame flow)"},
                {"method": "POST", "path": "/governance/federation/proposals/{proposal_id}/veto", "auth": "developer", "description": "Commander veto federation proposal (multi-frame flow)"},
            ],
            # 2026-04-25 — Transaction Storm. Generates real financial activity on
            # sandbox-A (and optionally sandbox-B) so the suite produces meaningful
            # event traffic during a full-suite run. ~20 intra-A transfers + 3
            # cross-registry transfers per default invocation. Configurable up to
            # 100 transfers via flow body.
            "multiframe_txstorm": [
                {"method": "POST", "path": "/onboard/create_agent", "auth": "none", "description": "Onboard sandbox agents (multi-frame flow)"},
                {"method": "POST", "path": "/teg/transfer", "auth": "agent", "description": "Round-robin AVT transfers (multi-frame flow)"},
                {"method": "GET", "path": "/teg/balance", "auth": "agent", "description": "Balance check during storm (multi-frame flow)"},
                {"method": "POST", "path": "/teg/cross-registry-transfer", "auth": "agent", "description": "Cross-registry AVT transfer (multi-frame flow)"},
            ],
            # 2026-04-25 — Quality Gate flow categories. Each gates assertions:
            # invariant + boundary + consistency probes against sandbox-A.
            # All endpoints listed are exercised end-to-end by their flow class.
            "flow_supply_audit": [
                {"method": "POST", "path": "/onboard/create_agent", "auth": "none", "description": "Onboard probe agent (quality gate)"},
                {"method": "POST", "path": "/teg/transfer", "auth": "agent", "description": "Trigger transfer for audit (quality gate)"},
            ],
            "flow_idempotency": [
                {"method": "POST", "path": "/onboard/bootstrap/request-token", "auth": "developer", "description": "Bootstrap token (quality gate)"},
                {"method": "POST", "path": "/onboard/create_agent", "auth": "none", "description": "Bootstrap-token replay probe (quality gate)"},
            ],
            "flow_auth_boundary": [
                {"method": "GET", "path": "/developers/me/agents", "auth": "developer", "description": "Wrong-tier probe (quality gate)"},
                {"method": "POST", "path": "/governance/proposals", "auth": "agent", "description": "Wrong-tier probe (quality gate)"},
                {"method": "GET", "path": "/admin/system-resources", "auth": "developer", "description": "Admin-gate probe (quality gate)"},
                {"method": "GET", "path": "/teg/balance", "auth": "agent", "description": "Tampered-JWT probe (quality gate)"},
                {"method": "POST", "path": "/onboard/agents/{agent_did}/reset-credentials", "auth": "developer", "description": "Cross-owner probe (quality gate)"},
            ],
            # §REPBOND 2026-09-05 — the six gate sites are exercised by the
            # federation suite; this flow walks ONE agent's bond lifecycle and
            # asserts each refusal by its SENTENCE, because a 403 on these paths
            # is also what a permission check and an absent route answer.
            "flow_reputation_bond": [
                {"method": "GET", "path": "/reputation-bond/config", "auth": "none", "description": "Bond posture this registry asks for (repbond flow)"},
                {"method": "GET", "path": "/agents/{agent_did}/reputation", "auth": "none", "description": "One agent's bond block (repbond flow)"},
                {"method": "GET", "path": "/agents/reputation-bond/status", "auth": "agent", "description": "404 contract when never bonded (repbond flow)"},
                {"method": "POST", "path": "/agents/reputation-bond/deposit", "auth": "agent", "description": "Self-funded escrow deposit (repbond flow)"},
                {"method": "POST", "path": "/agents/reputation-bond/release", "auth": "agent", "description": "409 until matured + cooldown (repbond flow)"},
                {"method": "PATCH", "path": "/agent-cards/{agent_did}/listing", "auth": "developer", "description": "Gate site: listing, refused then admitted (repbond flow)"},
                {"method": "GET", "path": "/admin/reputation-bond/overview", "auth": "admin", "description": "Bond population by status (repbond flow)"},
            ],
            "flow_concurrency_safety": [
                {"method": "POST", "path": "/teg/transfer", "auth": "agent", "description": "Parallel-transfer race probe (quality gate)"},
                {"method": "GET", "path": "/teg/balance", "auth": "agent", "description": "Post-race balance check (quality gate)"},
            ],
            "flow_mcp_smoke": [
                # MCP server is mounted at /mcp (NO /api/v1 prefix). The api-tester
                # runner prepends /api/v1 to every path, so listing /mcp/* directly
                # produces 404s on individual endpoint tests. The flow runs MCP
                # endpoint exercises internally via exec_in_container at the
                # correct path. Listing /admin/api-test/test-flow here as a
                # placeholder so the category isn't empty.
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "MCP smoke runs via flow framework (quality gate)"},
            ],
            "flow_mcp_lifecycle": [
                # Phase-1 MCP tester — walks live /mcp/rpc tools/list and applies
                # contracts from contracts/mcp_contracts.py. All actual MCP calls
                # happen inside the registry container; this row is the flow
                # framework hook (mirrors flow_mcp_smoke pattern).
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "MCP lifecycle full-sweep runs via flow framework (2026-05-25 phase 1)"},
                # 2 new admin endpoints surfaced by phase 1 — listed so the api
                # tester walks them too (proves they exist + return 2xx).
                {"method": "GET", "path": "/admin/api-test/mcp-tool-catalog", "auth": "developer", "description": "Live MCP tools/list classified by tier"},
                {"method": "POST", "path": "/admin/api-test/test-mcp-tool", "auth": "developer", "description": "Single-tool MCP invocation harness"},
                # §pass73.3.3 — Option M cloud-op MCP sweep flows (Phase 1 lite).
                # Each runs against one sandbox cloud-op's MCP surface (380 public
                # + 302 admin tools), using the cloud-op admin's developer JWT.
                # Tier-2 contracts skip in Phase 1 (no sentinel agent on cloud-op).
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "MCP cloud-op sweep (sandboxalpha) — flow_mcp_lifecycle_cloudop_sandboxalpha_complete"},
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "MCP cloud-op sweep (sandboxdelta) — flow_mcp_lifecycle_cloudop_sandboxdelta_complete"},
            ],
            "flow_federation_suite": [
                # §pass73.3.4 — Federation Test Suite (AAA+). Multi-registry MCP
                # orchestration of distributed-system claims (event propagation,
                # reactor convergence, supply invariant, trust scores, operator
                # lifecycle, failure modes). Sandbox-only. See plan doc.
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Federation suite — full run (flow_federation_suite_complete)"},
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Federation suite — smoke only (flow_federation_suite_smoke_complete)"},
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Federation suite — critical severity only (flow_federation_suite_critical_complete)"},
            ],
            "flow_webhook_delivery": [
                {"method": "POST", "path": "/webhooks", "auth": "developer", "description": "Register test webhook (quality gate)"},
                {"method": "GET", "path": "/webhooks/{webhook_id}/deliveries", "auth": "developer", "description": "Verify retry attempts (quality gate)"},
                {"method": "GET", "path": "/webhooks/{webhook_id}", "auth": "developer", "description": "Verify failure_count (quality gate)"},
                {"method": "DELETE", "path": "/webhooks/{webhook_id}", "auth": "developer", "description": "Cleanup (quality gate)"},
            ],
            "flow_funding_request": [
                {"method": "POST", "path": "/funding/request", "auth": "agent", "description": "Agent submits funding request (quality gate)"},
                {"method": "GET", "path": "/admin/funding/pending", "auth": "developer", "description": "Admin lists pending (quality gate)"},
                {"method": "POST", "path": "/admin/funding/{request_id}/approve", "auth": "developer", "description": "Admin approves (quality gate)"},
                {"method": "GET", "path": "/funding/my-requests", "auth": "agent", "description": "Verify status FUNDED (quality gate)"},
            ],
            "flow_coordinated_suspension": [
                {"method": "POST", "path": "/agent/enable-mtls", "auth": "agent", "description": "mTLS enrollment for pre-state (quality gate)"},
                {"method": "POST", "path": "/admin/agents/bulk/suspend", "auth": "developer", "description": "3-lever atomic suspend (quality gate)"},
                {"method": "POST", "path": "/admin/agents/bulk/reinstate", "auth": "developer", "description": "Symmetric reinstate (quality gate)"},
                {"method": "GET", "path": "/admin/agents/{agent_did}", "auth": "developer", "description": "Lever-state probe (quality gate)"},
            ],
            "flow_drift_detection": [
                {"method": "GET", "path": "/admin/federation/compliance/drifts", "auth": "developer", "description": "Recent drift inventory (quality gate)"},
                {"method": "POST", "path": "/admin/federation/drift-scan", "auth": "developer", "description": "On-demand drift scan (quality gate)"},
                {"method": "GET", "path": "/admin/reactor/status", "auth": "developer", "description": "Reactor dispatch counter probe (quality gate)"},
            ],
            "flow_blocklist_enforcement": [
                # Endpoints proxied via docker exec; listed for visibility in api-tester UI
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Flow runs Phase 8 blocklist enforcement E2E (quality gate)"},
            ],
            "flow_reactor_batch_2": [
                # Endpoints proxied via docker exec; listed for visibility in api-tester UI
                {"method": "GET", "path": "/admin/reactor/status", "auth": "developer", "description": "Reactor inventory probe — must include all 19 (quality gate)"},
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Flow emits 7 synthetic events covering 6 new reactors (quality gate)"},
            ],
            "flow_reactor_batch_2_operator": [
                # Sister flow targeting the sandboxalpha operator canary by default
                # (post-§pass73.3 topology — sandboxbeta/gamma torn down). The
                # `_all_flow` variant covers both sandboxalpha + sandboxdelta.
                # Mints admin JWT directly inside the operator container.
                {"method": "GET", "path": "/admin/reactor/status", "auth": "developer", "description": "Operator-side reactor inventory probe (quality gate)"},
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Flow emits 7 events on sandboxalpha (default) or all surviving sandbox cloud-ops (quality gate)"},
            ],
            # 2026-04-28 — Phase 12.2: cross-frame blocklist propagation E2E.
            # Block on mainframe, verify each operator's TEG independently has the
            # DID via its own /admin/agents/blocklist (decentralized — no
            # hub-and-spoke shortcut), then unblock and verify each clears.
            "flow_cross_frame_blocklist_propagation": [
                {"method": "POST", "path": "/admin/api-test/test-flow", "auth": "developer", "description": "Flow propagates blocks across all surviving sandbox cloud-ops independently (quality gate)"},
            ],
            # 2026-04-28 — Phase 12.3: provisioning-aware reactor coverage.
        }
    
    def _build_lookup(self) -> Dict[str, Dict[str, Any]]:
        """Build a lookup table for quick endpoint access"""
        lookup = {}
        for category, endpoints in self._endpoints.items():
            for endpoint in endpoints:
                key = f"{endpoint['method']}:{endpoint['path']}"
                lookup[key] = {
                    **endpoint,
                    "category": category
                }
        return lookup
    
    def get_all_endpoints(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get all endpoints organized by category"""
        return self._endpoints.copy()
    
    def get_category_endpoints(self, category: str) -> List[Dict[str, Any]]:
        """Get all endpoints for a specific category"""
        return self._endpoints.get(category, []).copy()
    
    def get_endpoint(self, method: str, path: str) -> Optional[Dict[str, Any]]:
        """Get specific endpoint details"""
        key = f"{method}:{path}"
        return self._endpoint_lookup.get(key)
    
    def get_categories(self) -> List[str]:
        """Get list of all categories"""
        return list(self._endpoints.keys())
    
    def get_endpoint_count(self) -> Dict[str, int]:
        """Get endpoint count by category"""
        return {
            category: len(endpoints)
            for category, endpoints in self._endpoints.items()
        }
    
    def get_total_endpoint_count(self) -> int:
        """Get total number of endpoints"""
        return sum(len(endpoints) for endpoints in self._endpoints.values())
    
    def find_endpoints_by_auth_type(self, auth_type: str) -> List[Dict[str, Any]]:
        """Find all endpoints requiring specific auth type"""
        results = []
        for category, endpoints in self._endpoints.items():
            for endpoint in endpoints:
                if endpoint["auth"] == auth_type:
                    results.append({
                        **endpoint,
                        "category": category
                    })
        return results
    
    def search_endpoints(self, query: str) -> List[Dict[str, Any]]:
        """Search endpoints by path or description"""
        query = query.lower()
        results = []
        
        for category, endpoints in self._endpoints.items():
            for endpoint in endpoints:
                if (query in endpoint["path"].lower() or 
                    query in endpoint.get("description", "").lower()):
                    results.append({
                        **endpoint,
                        "category": category
                    })
        
        return results


# Create singleton instance
endpoints_registry = EndpointsRegistry()
