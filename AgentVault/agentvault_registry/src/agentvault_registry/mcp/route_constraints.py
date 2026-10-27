"""§MCPTEST30 (V0548): a tool's advertised inputSchema states what its route enforces.

An MCP caller reads a tool's inputSchema and nothing else. 168 arguments of 85 tools (measured on V0546) carried a
constraint their route enforces and their schema did not state: placeAgoraOrder's side buy|sell, bulkSuspendAgents'
reason of at least 10 characters, pauseAgentPayouts' duration_days up to 365; a caller that followed the schema met a 422
the schema never warned about. The route is the source of truth: ROUTE_CONSTRAINTS is what the routes state for the
arguments each tool sends under the same name, rendered by `tests/mcp_schema_census.py --write`, and
test_mcp_schemas_state_route_constraints.py keeps it equal to what the routes state (a constraint missing from it, one
the route no longer states, or one that contradicts the tool's own schema fails the build). apply_route_constraints()
adds a key only where the tool's own schema says nothing; it never changes a key the tool states. A pattern of plain
alternatives is stated as an enum. The MCP argument gate (mcp/arguments.py) checks JSON types only: these keys inform a
caller, the route still decides.
"""
from __future__ import annotations

from typing import Any, Dict, List

ROUTE_CONSTRAINTS: Dict[str, Dict[str, Dict[str, Any]]] = {
    'theprotocol_acceptComplianceBaseline': {
        'expected_hash': {"maxLength": 64, "minLength": 64, "pattern": "^[0-9a-f]{64}$"},
        'reason': {"maxLength": 500, "minLength": 5},
    },
    'theprotocol_acceptContract': {
        'upgrader_agent_did': {"maxLength": 120},
    },
    'theprotocol_addTeamMember': {
        'role': {"enum": ["lead", "member"]},
    },
    'theprotocol_adminAgoraParticipants': {
        'status': {"enum": ["verified", "pending", "blocked"]},
    },
    'theprotocol_adminCommonsCancelSeason': {
        'reason': {"maxLength": 240, "minLength": 5},
    },
    'theprotocol_adminCommonsStrikeSubmission': {
        'reason': {"maxLength": 240, "minLength": 5},
        'submission_id': {"exclusiveMinimum": 0},
    },
    'theprotocol_adminCommonsWriteOffAward': {
        'reason': {"maxLength": 240, "minLength": 5},
    },
    'theprotocol_authRecoverAccount': {
        'email': {"format": "email"},
    },
    'theprotocol_authRegister': {
        'email': {"format": "email"},
        'invite_code': {"maxLength": 30},
        'name': {"maxLength": 100, "minLength": 3},
        'password': {"minLength": 12},
    },
    'theprotocol_authSetNewPassword': {
        'new_password': {"minLength": 12},
    },
    'theprotocol_blockChatPrincipal': {
        'agent_did': {"maxLength": 255},
        'remote_key': {"maxLength": 320},
    },
    'theprotocol_blockFederationAgent': {
        'reason': {"maxLength": 500},
    },
    'theprotocol_bulkRefreshAgentCards': {
        'reason': {"maxLength": 500},
    },
    'theprotocol_bulkReinstateAgents': {
        'reason': {"maxLength": 500},
    },
    'theprotocol_bulkSuspendAgents': {
        'reason': {"maxLength": 500, "minLength": 10},
    },
    'theprotocol_buyAgoraLaunch': {
        'qty': {"exclusiveMinimum": 0},
    },
    'theprotocol_castCommonsBallot': {
        'challenge_id': {"maxLength": 44},
        'totp_code': {"maxLength": 16},
    },
    'theprotocol_castVote': {
        'challenge_id': {"maxLength": 44},
        'reason': {"maxLength": 1000},
        'totp_code': {"maxLength": 16},
    },
    'theprotocol_composeBroadcast': {
        'body': {"minLength": 1},
        'broadcast_type': {"enum": ["info", "warning", "maintenance", "critical"]},
        'cta_label': {"maxLength": 50},
        'cta_url': {"maxLength": 500},
        'target_org_id': {"maxLength": 255},
        'title': {"maxLength": 200},
    },
    'theprotocol_createAgoraListing': {
        'display_name': {"maxLength": 255},
        'funding_agent_did': {"maxLength": 120},
        'organization_id': {"maxLength": 255},
        'symbol': {"maxLength": 6, "minLength": 2, "pattern": "^[A-Z0-9]{2,6}$"},
        'total_shares': {"exclusiveMinimum": 0, "maximum": 1000000000000},
    },
    'theprotocol_createFrameInvitation': {
        'bundle_endpoint_url': {"maxLength": 500, "minLength": 8, "pattern": "^https://[a-zA-Z0-9][a-zA-Z0-9.\\-]*(:\\d+)?(/[^\\s]*)?$"},
        'contact_email': {"maxLength": 255, "minLength": 3},
        'description': {"maxLength": 2000},
        'event_store_url': {"maxLength": 500, "pattern": "^https://[a-zA-Z0-9][a-zA-Z0-9.\\-]*(:\\d+)?(/[^\\s]*)?$"},
        'federation_endpoint_url': {"maxLength": 500, "minLength": 8, "pattern": "^https://[a-zA-Z0-9][a-zA-Z0-9.\\-]*(:\\d+)?(/[^\\s]*)?$"},
        'initiator_nonce': {"maxLength": 64, "minLength": 16, "pattern": "^[a-fA-F0-9]{16,64}$"},
        'name': {"maxLength": 255, "minLength": 1},
        'trust_domain': {"maxLength": 255, "minLength": 3, "pattern": "^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$"},
    },
    'theprotocol_createOrganization': {
        'description': {"maxLength": 1000},
        'logo_url': {"maxLength": 500},
        'name': {"maxLength": 255, "minLength": 3},
        'website': {"maxLength": 500},
    },
    'theprotocol_createPipeline': {
        'pipeline_name': {"maxLength": 255, "minLength": 1},
    },
    'theprotocol_createProposal': {
        'description': {"maxLength": 5000, "minLength": 1},
        'proposal_type': {"maxLength": 50},
        'title': {"maxLength": 200, "minLength": 1},
    },
    'theprotocol_createVersion': {
        'version': {"maxLength": 64, "minLength": 1},
    },
    'theprotocol_createWebhook': {
        'description': {"maxLength": 500},
        'url': {"maxLength": 500},
    },
    'theprotocol_depositReputationBond': {
        'amount': {"exclusiveMinimum": 0},
    },
    'theprotocol_engageAgent': {
        'deadline_seconds': {"maximum": 31622400, "minimum": 60},
        'message': {"maxLength": 2000},
    },
    'theprotocol_federationSlashRequest': {
        'amount': {"exclusiveMinimum": 0},
        'callback_url': {"maxLength": 500},
        'complainant_did': {"maxLength": 120},
        'defendant_did': {"maxLength": 120},
        'origin_registry_url': {"maxLength": 500},
        'ruling': {"maxLength": 100},
        'settlement_id': {"maxLength": 200},
    },
    'theprotocol_federationVetoProposal': {
        'reason': {"maxLength": 1000, "minLength": 1},
    },
    'theprotocol_finalizeFrameInvitation': {
        'approver_bundle_endpoint_url': {"pattern": "^https://[a-zA-Z0-9][a-zA-Z0-9.\\-]*(:\\d+)?(/[^\\s]*)?$"},
        'approver_bundle_pem': {"maxLength": 100000},
        'approver_federation_endpoint_url': {"pattern": "^https://[a-zA-Z0-9][a-zA-Z0-9.\\-]*(:\\d+)?(/[^\\s]*)?$"},
        'approver_trust_domain': {"pattern": "^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?(\\.[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?)+$"},
        'nonce_echo': {"maxLength": 64, "minLength": 16},
    },
    'theprotocol_generateInviteCodes': {
        'note': {"maxLength": 255},
    },
    'theprotocol_getAdminAgents': {
        'offset': {"minimum": 0},
    },
    'theprotocol_getAdminDevelopers': {
        'offset': {"minimum": 0},
    },
    'theprotocol_getCanaryResults': {
        'limit': {"maximum": 500, "minimum": 1},
    },
    'theprotocol_getGovernanceProposals': {
        'limit': {"maximum": 200, "minimum": 1},
    },
    'theprotocol_getMyAgentBundles': {
        'limit': {"maximum": 200, "minimum": 1},
        'offset': {"minimum": 0},
    },
    'theprotocol_getMyIncome': {
        'limit': {"maximum": 500, "minimum": 1},
        'offset': {"minimum": 0},
    },
    'theprotocol_getMyLockHistory': {
        'limit': {"maximum": 1000, "minimum": 1},
        'offset': {"minimum": 0},
    },
    'theprotocol_getMySupportTickets': {
        'limit': {"maximum": 200},
        'offset': {"minimum": 0},
    },
    'theprotocol_getOrgPublicFeed': {
        'before_seq': {"minimum": 1},
        'limit': {"maximum": 100, "minimum": 1},
    },
    'theprotocol_guildBid': {
        'eta_seconds': {"maximum": 2592000, "minimum": 60},
        'on_behalf_of_org_id': {"maxLength": 64},
        'pitch': {"maxLength": 2000},
    },
    'theprotocol_guildCrossRegistryBid': {
        'eta_seconds': {"maximum": 2592000, "minimum": 60},
        'on_behalf_of_org_id': {"maxLength": 64},
        'order_id': {"maxLength": 40},
        'pitch': {"maxLength": 2000},
    },
    'theprotocol_guildVerify': {
        'feedback': {"maxLength": 2000},
        'stars': {"maximum": 5, "minimum": 1},
    },
    'theprotocol_instantiateContractTemplate': {
        'provider_did': {"maxLength": 120},
    },
    'theprotocol_inviteOrganizationMember': {
        'email': {"format": "email"},
        'role': {"enum": ["admin", "member", "guest"]},
    },
    'theprotocol_liftQuarantine': {
        'new_policy_hash': {"maxLength": 64, "minLength": 64},
    },
    'theprotocol_listFederationAgentCards': {
        'since': {"format": "date-time"},
    },
    'theprotocol_listTransparentOrganizations': {
        'limit': {"maximum": 50, "minimum": 1},
    },
    'theprotocol_logEnhancedDispute': {
        'avtp_transaction_id': {"maxLength": 200},
        'brief_description': {"maxLength": 1000},
        'defendant_agent_id': {"maxLength": 120},
        'evidence_pointer': {"maxLength": 500},
        'reason_code': {"maxLength": 50},
    },
    'theprotocol_logTegDispute': {
        'brief_description': {"maxLength": 1000},
    },
    'theprotocol_markContractFailed': {
        'reason': {"maxLength": 500},
    },
    'theprotocol_pauseAgentPayouts': {
        'duration_days': {"exclusiveMinimum": 0, "maximum": 365},
        'reason': {"maxLength": 500, "minLength": 1},
    },
    'theprotocol_placeAgoraOrder': {
        'client_order_id': {"maxLength": 64},
        'qty': {"exclusiveMinimum": 0},
        'ttl_seconds': {"maximum": 604800, "minimum": 10},
    },
    'theprotocol_previewSlash': {
        'amount': {"exclusiveMinimum": 0},
    },
    'theprotocol_purchasePipelineTemplate': {
        'buyer_did': {"minLength": 1},
    },
    'theprotocol_quarantineRegistry': {
        'grace_hours': {"maximum": 336, "minimum": 0},
        'reason': {"maxLength": 500, "minLength": 5},
    },
    'theprotocol_recordAgentOffense': {
        'disputed_amount': {"minimum": 0},
        'severity': {"maximum": 4, "minimum": 1},
    },
    'theprotocol_reinstateAgentEnforcement': {
        'reason': {"maxLength": 500, "minLength": 1},
    },
    'theprotocol_rejectFunding': {
        'reason': {"maxLength": 1000, "minLength": 1},
    },
    'theprotocol_replySupportTicket': {
        'message': {"minLength": 1},
    },
    'theprotocol_requestAccountDeletion': {
        'confirmation': {"maxLength": 64},
        'password': {"maxLength": 512, "minLength": 1},
        'reason': {"maxLength": 500},
    },
    'theprotocol_rotateFederationLicenseSelf': {
        'reason': {"maxLength": 64, "minLength": 1},
    },
    'theprotocol_sendChatMessage': {
        'body': {"maxLength": 8192},
        'client_ref': {"maxLength": 64, "minLength": 8},
    },
    'theprotocol_slashAgent': {
        'amount': {"exclusiveMinimum": 0},
        'reason': {"maxLength": 500, "minLength": 1},
    },
    'theprotocol_smartSend': {
        'message': {"maxLength": 500},
        'receiver_did': {"minLength": 8},
    },
    'theprotocol_softDeleteDeveloper': {
        'confirm_email': {"maxLength": 320, "minLength": 3},
    },
    'theprotocol_startSimulation': {
        'rate_tps': {"exclusiveMinimum": 0},
        'spawn_frames': {"pattern": "^[ABCabc](,[ABCabc])*$"},
    },
    'theprotocol_submitCommonsWork': {
        'description': {"maxLength": 4000},
        'kind': {"maxLength": 24},
        'title': {"maxLength": 200, "minLength": 3},
    },
    'theprotocol_submitContractWork': {
        'pr_url': {"maxLength": 500},
    },
    'theprotocol_submitDispute': {
        'defendant_did': {"maxLength": 120},
    },
    'theprotocol_submitSupportTicket': {
        'message': {"minLength": 1},
        'subject': {"maxLength": 200, "minLength": 1},
    },
    'theprotocol_supportCloseTicket': {
        'message': {"minLength": 1},
    },
    'theprotocol_supportReplyTicket': {
        'message': {"minLength": 1},
    },
    'theprotocol_suspendAgent': {
        'reason': {"maxLength": 500, "minLength": 1},
    },
    'theprotocol_suspendFederationLicense': {
        'reason': {"maxLength": 500},
    },
    'theprotocol_tegCrossRegistryTransferDirect': {
        'receiver_did': {"maxLength": 120},
    },
    'theprotocol_tegReputationSignal': {
        'signal_value': {"maximum": 1, "minimum": -1},
    },
    'theprotocol_tegTreasuryIssue': {
        'reason': {"maxLength": 256},
        'target_agent_did': {"maxLength": 120},
    },
    'theprotocol_transferAgentOwnership': {
        'new_creator_developer_id': {"minimum": 1},
        'reason': {"maxLength": 500, "minLength": 10},
    },
    'theprotocol_transferUnits': {
        'message': {"maxLength": 256},
    },
    'theprotocol_unblockChatPrincipal': {
        'agent_did': {"maxLength": 255},
        'remote_key': {"maxLength": 320},
    },
    'theprotocol_unblockFederationAgent': {
        'reason': {"maxLength": 500},
    },
    'theprotocol_updateBroadcast': {
        'body': {"minLength": 1},
        'broadcast_type': {"enum": ["info", "warning", "maintenance", "critical"]},
        'title': {"maxLength": 200},
    },
    'theprotocol_updateDeploymentStatus': {
        'status': {"maxLength": 32, "minLength": 1},
    },
    'theprotocol_updateEnforcementPolicy': {
        'reason': {"maxLength": 500, "minLength": 1},
    },
    'theprotocol_updateOrganization': {
        'description': {"maxLength": 1000},
        'logo_url': {"maxLength": 500},
        'name': {"maxLength": 255, "minLength": 3},
        'website': {"maxLength": 500},
    },
    'theprotocol_updateWebhook': {
        'description': {"maxLength": 500},
        'url': {"maxLength": 500},
    },
    'theprotocol_verify2FA': {
        'code': {"pattern": "^[0-9]{6}$"},
    },
}

# what apply_route_constraints() added, by tool and argument: the census reads a schema's own keys without them
APPLIED: Dict[str, Dict[str, List[str]]] = {}


def apply_route_constraints(schemas: List[Dict[str, Any]]) -> int:
    """Add each tool's route constraints to its advertised inputSchema where the tool states nothing. Idempotent (the
    gateway's schema objects are shared by both surfaces). Returns the number of keys added."""
    added = 0
    for sc in schemas:
        if not isinstance(sc, dict):
            continue
        name = sc.get("name")
        table = ROUTE_CONSTRAINTS.get(name)
        if not table:
            continue
        props = (sc.get("inputSchema") or {}).get("properties") or {}
        for field, cons in table.items():
            prop = props.get(field)
            if not isinstance(prop, dict):
                continue
            for key, value in cons.items():
                if key == "items":
                    items = prop.get("items")
                    if items is None:
                        prop["items"] = dict(value)
                    elif isinstance(items, dict) and "type" not in items:
                        items.update(value)
                    else:
                        continue
                elif key in prop:
                    continue
                else:
                    prop[key] = list(value) if isinstance(value, list) else value
                done = APPLIED.setdefault(name, {}).setdefault(field, [])
                if key not in done:
                    done.append(key)
                    added += 1
    return added
