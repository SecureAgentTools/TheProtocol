"""§MCPTEST30 (V0550): the refusals round 15 passed under the DEFAULT contract are pinned, and the pins must hold.

Round 15's strict run (65962184c67f4e40, 2026-10-02) passed 99 tool rows as a 4xx that no written contract judged. The
87 that are the destructive-safe design working now carry a contract (mcp_contracts.py, the V0550 section). Three
properties are checked here, statically, from the answers round 15 RECORDED on the frame and on both cloud operators
(30b36e3d36d44fc4 sandboxalpha, 3193d421785d415f sandboxdelta):
- each pin's sentence is in every recorded answer, and the answer's status is in the pin's class;
- each pin's call aims where the lifecycle's does (the same arguments, read from mcp_admin_lifecycles.py by AST);
- each pin aims at something that does not exist (a nonexistent-target marker in its arguments) or at a deliberately
  invalid value that is named here with why it is harmless: the refusal-becomes-an-action hazard (§FANCLAIM).
"""
import ast
import json
import pathlib

import pytest

from agentvault_registry.api_tests.contracts.mcp_contracts import MCP_CONTRACTS

SRC = (pathlib.Path(__file__).resolve().parents[1] / "src" / "agentvault_registry" / "api_tests" / "contracts"
       / "mcp_admin_lifecycles.py")
NONEXISTENT = ("phase6", "PHASE6", "999999", "00000000-0000-4000-8000", "no-such")
SAFE_WITHOUT_MARKER = {"theprotocol_tegTreasuryIssue": "amount \"0\": the route refuses it as not positive, and a zero mint moves nothing", "theprotocol_uploadRegistryCardIcon": "bytes that are not an image: the route answers 415 before it writes anything"}

# tool: {node: (status, the answer's text)}, as round 15 recorded them (2026-10-02)
RECORDED = {
    "theprotocol_acknowledgeAgentFlag": {
        "frame": (404, "Error: HTTP 404: Flag not found for this agent"),
        "sandboxalpha": (404, "Error: HTTP 404: Flag not found for this agent"),
        "sandboxdelta": (404, "Error: HTTP 404: Flag not found for this agent"),
    },
    "theprotocol_adminDownloadOperatorBundle": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_approveFrameInvitation": {
        "frame": (404, "Error: HTTP 404: Invitation not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_approveFunding": {
        "frame": (404, "Error: HTTP 404: Funding request #999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Funding request #999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Funding request #999999 not found"),
    },
    "theprotocol_approveOperatorApplication": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_approvePeerRegistry": {
        "frame": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Peer registry not found"),
    },
    "theprotocol_approvePendingEnforcement": {
        "frame": (404, "Error: HTTP 404: Pending action phase6-no-such-enforce not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Pending action phase6-no-such-enforce not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Pending action phase6-no-such-enforce not found"),
    },
    "theprotocol_blacklistRegistry": {
        "frame": (404, "Error: HTTP 404: No compliance record for peer_id=999999"),
        "sandboxalpha": (404, "Error: HTTP 404: No compliance record for peer_id=999999"),
        "sandboxdelta": (404, "Error: HTTP 404: No compliance record for peer_id=999999"),
    },
    "theprotocol_deactivatePeerRegistry": {
        "frame": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Peer registry not found"),
    },
    "theprotocol_deleteAdminAgent": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_deleteFederationLicense": {
        "frame": (404, "Error: HTTP 404: Federation license not found: phase6-no-such-license"),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_deleteOauthFederationTrust": {
        "frame": (404, "Error: HTTP 404: Registry https://phase6-no-such-trust.invalid not found in trust config"),
        "sandboxalpha": (404, "Error: HTTP 404: Registry https://phase6-no-such-trust.invalid not found in trust config"),
        "sandboxdelta": (404, "Error: HTTP 404: Registry https://phase6-no-such-trust.invalid not found in trust config"),
    },
    "theprotocol_deleteSpireOrphan": {
        "frame": (400, "Error: HTTP 400: Can only delete agent entries"),
        "sandboxalpha": (400, "Error: HTTP 400: Can only delete agent entries"),
        "sandboxdelta": (400, "Error: HTTP 400: Can only delete agent entries"),
    },
    "theprotocol_disableDeveloper2FA": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_disableWebhookAdmin": {
        "frame": (404, "Error: HTTP 404: Webhook not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Webhook not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Webhook not found"),
    },
    "theprotocol_dismissBundleReport": {
        "frame": (404, "Error: HTTP 404: Report not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Report not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Report not found"),
    },
    "theprotocol_enableWebhookAdmin": {
        "frame": (404, "Error: HTTP 404: Webhook not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Webhook not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Webhook not found"),
    },
    "theprotocol_federationPolicyUpdateRequest": {
        "frame": (404, "Error: HTTP 404: No peer registry found for that DID"),
        "sandboxalpha": (404, "Error: HTTP 404: No peer registry found for that DID"),
        "sandboxdelta": (404, "Error: HTTP 404: No peer registry found for that DID"),
    },
    "theprotocol_finalizeRetryFrameInvitation": {
        "frame": (404, "Error: HTTP 404: Invitation not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_fireCanaryPath": {
        "frame": (404, "Error: HTTP 404: Canary path not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Canary path not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Canary path not found"),
    },
    "theprotocol_forceDeveloperPasswordReset": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_forceEmailVerify": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_forceMtlsEnroll": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_forceRegisterAgentCard": {
        "frame": (404, "Error: HTTP 404: No card for agent did:theprotocol:phase6-no-such-agent"),
        "sandboxalpha": (404, "Error: HTTP 404: No card for agent did:theprotocol:phase6-no-such-agent"),
        "sandboxdelta": (404, "Error: HTTP 404: No card for agent did:theprotocol:phase6-no-such-agent"),
    },
    "theprotocol_getAdminFiatPurchaseDetail": {
        "frame": (404, "{\"error\":{\"detail\":\"FiatPurchase phase6-no-such-purchase not found\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"FiatPurchase phase6-no-such-purchase not found\",\"ins"),
        "sandboxalpha": (404, "{\"error\":{\"detail\":\"FiatPurchase phase6-no-such-purchase not found\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"FiatPurchase phase6-no-such-purchase not found\",\"ins"),
        "sandboxdelta": (404, "{\"error\":{\"detail\":\"FiatPurchase phase6-no-such-purchase not found\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"FiatPurchase phase6-no-such-purchase not found\",\"ins"),
    },
    "theprotocol_getAdminFrameInvitation": {
        "frame": (404, "{\"error\":{\"detail\":\"Invitation not found.\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"Invitation not found.\",\"instance\":\"/api/v1/admin/federation/frame-invitations"),
        "sandboxalpha": (503, "{\"error\":{\"detail\":\"This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-fra"),
        "sandboxdelta": (503, "{\"error\":{\"detail\":\"This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-fra"),
    },
    "theprotocol_getBridgeStatus": {
        "frame": (404, "{\"error\":{\"detail\":\"Bridge transaction not found\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"Bridge transaction not found\",\"instance\":\"/api/v1/bridge/status/phase6"),
        "sandboxalpha": (503, "{\"error\":{\"detail\":\"This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-fra"),
        "sandboxdelta": (503, "{\"error\":{\"detail\":\"This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-fra"),
    },
    "theprotocol_getCloudOperatorLogs": {
        "frame": (404, "{\"error\":{\"detail\":\"Application not found\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"Application not found\",\"instance\":\"/api/v1/admin/cloud-operators/phase6-no-su"),
        "sandboxalpha": (503, "{\"error\":{\"detail\":\"This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-fra"),
        "sandboxdelta": (503, "{\"error\":{\"detail\":\"This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-fra"),
    },
    "theprotocol_giftProvisioning": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (503, "Error: HTTP 503: Gift provisioning is mainframe-only (cloud-ops cannot extend their own provisioning)."),
        "sandboxdelta": (503, "Error: HTTP 503: Gift provisioning is mainframe-only (cloud-ops cannot extend their own provisioning)."),
    },
    "theprotocol_grantFiatFlare": {
        "frame": (400, "Error: HTTP 400: Unknown flare tier 'phase6-not-a-tier'. Valid: ['architect', 'commander', 'founder', 'operator', 'sentinel', 'shadow_chancellor']"),
        "sandboxalpha": (400, "Error: HTTP 400: Unknown flare tier 'phase6-not-a-tier'. Valid: ['architect', 'commander', 'founder', 'operator', 'sentinel', 'shadow_chancellor']"),
        "sandboxdelta": (400, "Error: HTTP 400: Unknown flare tier 'phase6-not-a-tier'. Valid: ['architect', 'commander', 'founder', 'operator', 'sentinel', 'shadow_chancellor']"),
    },
    "theprotocol_hideBundle": {
        "frame": (404, "Error: HTTP 404: Bundle not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Bundle not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Bundle not found"),
    },
    "theprotocol_ironhandEnrollAgent": {
        "frame": (404, "Error: HTTP 404: Agent not found: did:theprotocol:phase6-no-such-agent"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent not found: did:theprotocol:phase6-no-such-agent"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent not found: did:theprotocol:phase6-no-such-agent"),
    },
    "theprotocol_ironhandRevokeAgent": {
        "frame": (404, "Error: HTTP 404: Agent not found: did:theprotocol:phase6-no-such-agent"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent not found: did:theprotocol:phase6-no-such-agent"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent not found: did:theprotocol:phase6-no-such-agent"),
    },
    "theprotocol_pauseAgentPayouts": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_previewSlash": {
        "frame": (404, "{\"error\":{\"detail\":\"Agent not found: did:theprotocol:phase6-no-such-agent\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"Agent not found: did:theprotocol:phase6-no-su"),
        "sandboxalpha": (404, "{\"error\":{\"detail\":\"Agent not found: did:theprotocol:phase6-no-such-agent\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"Agent not found: did:theprotocol:phase6-no-su"),
        "sandboxdelta": (404, "{\"error\":{\"detail\":\"Agent not found: did:theprotocol:phase6-no-such-agent\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"Agent not found: did:theprotocol:phase6-no-su"),
    },
    "theprotocol_reactivatePeerRegistry": {
        "frame": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Peer registry not found"),
    },
    "theprotocol_reconcileFiatProvisioning": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_recordAgentOffense": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_refreshAgentCardDrift": {
        "frame": (404, "Error: HTTP 404: No card for agent did:theprotocol:phase6-no-such-agent"),
        "sandboxalpha": (404, "Error: HTTP 404: No card for agent did:theprotocol:phase6-no-such-agent"),
        "sandboxdelta": (404, "Error: HTTP 404: No card for agent did:theprotocol:phase6-no-such-agent"),
    },
    "theprotocol_refundFiatPurchase": {
        "frame": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
        "sandboxalpha": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
        "sandboxdelta": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
    },
    "theprotocol_reinstateAgentEnforcement": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_reinstateBroadcast": {
        "frame": (404, "Error: HTTP 404: Broadcast not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Broadcast not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Broadcast not found"),
    },
    "theprotocol_reinstateDeveloper": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_reinstateFederationLicense": {
        "frame": (404, "Error: HTTP 404: Federation license not found: phase6-no-such-license"),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_reinstateOperator": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_rejectFrameInvitation": {
        "frame": (404, "Error: HTTP 404: Invitation not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_rejectFunding": {
        "frame": (404, "Error: HTTP 404: Funding request #999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Funding request #999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Funding request #999999 not found"),
    },
    "theprotocol_rejectOperatorApplication": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_rejectPeerRegistry": {
        "frame": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Peer registry not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Peer registry not found"),
    },
    "theprotocol_rejectPendingEnforcement": {
        "frame": (404, "Error: HTTP 404: Pending action phase6-no-such-enforce not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Pending action phase6-no-such-enforce not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Pending action phase6-no-such-enforce not found"),
    },
    "theprotocol_replayFiatPurchase": {
        "frame": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
        "sandboxalpha": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
        "sandboxdelta": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
    },
    "theprotocol_resendFiatMagicLink": {
        "frame": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
        "sandboxalpha": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
        "sandboxdelta": (404, "Error: HTTP 404: FiatPurchase phase6-no-such-purchase not found"),
    },
    "theprotocol_resumeAgentPayouts": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_resyncFrameEventStore": {
        "frame": (404, "Error: HTTP 404: Peer not found"),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_retractBroadcast": {
        "frame": (404, "Error: HTTP 404: Broadcast not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Broadcast not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Broadcast not found"),
    },
    "theprotocol_revokeDeveloperApiKeys": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_revokeFederationLicense": {
        "frame": (404, "Error: HTTP 404: Federation license not found: phase6-no-such-license"),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_revokeFiatFlare": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_revokeFrame": {
        "frame": (404, "Error: HTTP 404: Peer not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_revokeInviteCode": {
        "frame": (404, "Error: HTTP 404: Code not found or already used (cannot revoke used codes)"),
        "sandboxalpha": (404, "Error: HTTP 404: Code not found or already used (cannot revoke used codes)"),
        "sandboxdelta": (404, "Error: HTTP 404: Code not found or already used (cannot revoke used codes)"),
    },
    "theprotocol_revokeOperatorAccess": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_rotateAgentCredentials": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_rotateAgentSigningKey": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_rotateOperatorPullToken": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_runAllDiagnostics": {
        "frame": (404, "Error: HTTP 404: target 'phase6-no-such-target' not found"),
        "sandboxalpha": (404, "Error: HTTP 404: target 'phase6-no-such-target' not found"),
        "sandboxdelta": (404, "Error: HTTP 404: target 'phase6-no-such-target' not found"),
    },
    "theprotocol_runDiagnosticsSubset": {
        "frame": (404, "Error: HTTP 404: no matching targets"),
        "sandboxalpha": (404, "Error: HTTP 404: no matching targets"),
        "sandboxdelta": (404, "Error: HTTP 404: no matching targets"),
    },
    "theprotocol_setEventEmissionPolicy": {
        "frame": (404, "Error: setPolicy failed HTTP 404: {\"error\":{\"detail\":\"No policy for event type: phase6-no-such-event\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"No policy for even"),
        "sandboxalpha": (404, "Error: setPolicy failed HTTP 404: {\"error\":{\"detail\":\"No policy for event type: Phase6NoSuchEvent\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"No policy for event t"),
        "sandboxdelta": (404, "Error: setPolicy failed HTTP 404: {\"error\":{\"detail\":\"No policy for event type: Phase6NoSuchEvent\",\"type\":\"not_found\"},\"type\":\"https://docs.theprotocol.cloud/errors/not_found\",\"title\":\"Not Found\",\"status\":404,\"detail\":\"No policy for event t"),
    },
    "theprotocol_setFederationComplianceEnforcementMode": {
        "frame": (422, "Error: HTTP 422: Input should be 'off', 'dry_run' or 'enforcing'"),
        "sandboxalpha": (422, "Error: HTTP 422: Input should be 'off', 'dry_run' or 'enforcing'"),
        "sandboxdelta": (422, "Error: HTTP 422: Input should be 'off', 'dry_run' or 'enforcing'"),
    },
    "theprotocol_softDeleteDeveloper": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_supportCloseTicket": {
        "frame": (404, "Error: Failed to send reply before closing ticket #999999 (HTTP 404)"),
        "sandboxalpha": (404, "Error: Failed to send reply before closing ticket #999999 (HTTP 404)"),
        "sandboxdelta": (404, "Error: Failed to send reply before closing ticket #999999 (HTTP 404)"),
    },
    "theprotocol_supportReplyTicket": {
        "frame": (404, "Error: Failed to reply to ticket #999999 (HTTP 404)"),
        "sandboxalpha": (404, "Error: Failed to reply to ticket #999999 (HTTP 404)"),
        "sandboxdelta": (404, "Error: Failed to reply to ticket #999999 (HTTP 404)"),
    },
    "theprotocol_suspendAgent": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_suspendDeveloper": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_suspendFederationLicense": {
        "frame": (404, "Error: HTTP 404: Federation license not found: phase6-no-such"),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_suspendOperator": {
        "frame": (404, "Error: HTTP 404: Application not found."),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_tegTreasuryIssue": {
        "frame": (422, "Error: HTTP 422: Value error, Amount must be positive"),
        "sandboxalpha": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
        "sandboxdelta": (503, "Error: HTTP 503: This feature runs on sovereign mainframes only. Cloud-operators federate with the mainframe via the bilateral trust chain — they don't independently provision sub-operators, issue federation licenses, configure cross-frame "),
    },
    "theprotocol_testWebhookAdmin": {
        "frame": (404, "Error: HTTP 404: Webhook not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Webhook not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Webhook not found"),
    },
    "theprotocol_toggleCanaryPath": {
        "frame": (404, "Error: HTTP 404: Canary path not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Canary path not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Canary path not found"),
    },
    "theprotocol_transferAgentOwnership": {
        "frame": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Agent did:theprotocol:phase6-no-such-agent not found"),
    },
    "theprotocol_triggerDiagnosticAction": {
        "frame": (404, "Error: HTTP 404: target 'phase6-no-such-target' not found"),
        "sandboxalpha": (404, "Error: HTTP 404: target 'phase6-no-such-target' not found"),
        "sandboxdelta": (404, "Error: HTTP 404: target 'phase6-no-such-target' not found"),
    },
    "theprotocol_unhideBundle": {
        "frame": (404, "Error: HTTP 404: Bundle not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Bundle not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Bundle not found"),
    },
    "theprotocol_updateBroadcast": {
        "frame": (404, "Error: HTTP 404: Broadcast not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Broadcast not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Broadcast not found"),
    },
    "theprotocol_updateDeveloperAdminFlags": {
        "frame": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Developer 999999 not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Developer 999999 not found"),
    },
    "theprotocol_updateDisputeRuling": {
        "frame": (400, "Error: HTTP 400: Invalid ruling. Must be one of: IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED"),
        "sandboxalpha": (400, "Error: HTTP 400: Invalid ruling. Must be one of: IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED"),
        "sandboxdelta": (400, "Error: HTTP 400: Invalid ruling. Must be one of: IN_FAVOR_OF_COMPLAINANT, IN_FAVOR_OF_DEFENDANT, DISMISSED"),
    },
    "theprotocol_updateEnforcementPolicy": {
        "frame": (422, "Error: HTTP 422: policy refused: unknown policy key 'phase6'"),
        "sandboxalpha": (422, "Error: HTTP 422: policy refused: unknown policy key 'phase6'"),
        "sandboxdelta": (422, "Error: HTTP 422: policy refused: unknown policy key 'phase6'"),
    },
    "theprotocol_updateSupportTicketStatus": {
        "frame": (404, "Error: HTTP 404: Ticket not found"),
        "sandboxalpha": (404, "Error: HTTP 404: Ticket not found"),
        "sandboxdelta": (404, "Error: HTTP 404: Ticket not found"),
    },
    "theprotocol_uploadRegistryCardIcon": {
        "frame": (415, "Error: HTTP 415: Icon must be PNG or JPEG (detected: None). SVG rejected for XSS safety."),
        "sandboxalpha": (415, "Error: HTTP 415: Icon must be PNG or JPEG (detected: None). SVG rejected for XSS safety."),
        "sandboxdelta": (415, "Error: HTTP 415: Icon must be PNG or JPEG (detected: None). SVG rejected for XSS safety."),
    },
}


def _alternatives(tool):
    want = MCP_CONTRACTS[tool].expect_error_message_contains
    return list(want) if isinstance(want, (list, tuple)) else [want]


def _lifecycle_tables():
    """Every (tool, arguments) the admin lifecycles list in a probe table, with their module constants resolved."""
    tree = ast.parse(SRC.read_text())
    names = {"fake_did": "did:theprotocol:phase6-no-such-agent", "fake_dev": 999999}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) \
                and isinstance(n.value, ast.Constant):
            names[n.targets[0].id] = n.value.value

    def lit(node):
        if isinstance(node, ast.Name) and node.id in names:
            return names[node.id]
        if isinstance(node, ast.Dict):
            return {lit(k): lit(v) for k, v in zip(node.keys, node.values)}
        if isinstance(node, ast.List):
            return [lit(x) for x in node.elts]
        return ast.literal_eval(node)

    tables = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Tuple) and len(n.elts) == 2 and isinstance(n.elts[0], ast.Constant) \
                and isinstance(n.elts[1], ast.Dict) and str(n.elts[0].value).startswith("theprotocol_"):
            try:
                tables.setdefault(n.elts[0].value, []).append(lit(n.elts[1]))
            except (ValueError, TypeError, SyntaxError):
                pass
    return tables


def test_the_section_pins_all_87():
    assert len(RECORDED) == 87
    assert all(tool in MCP_CONTRACTS for tool in RECORDED)


@pytest.mark.parametrize("tool", sorted(RECORDED))
def test_the_pin_holds_where_round_15_recorded_the_refusal(tool):
    c = MCP_CONTRACTS[tool]
    assert c.expect_status in ("error_4xx", "error"), c.expect_status
    assert c.override_coverage_fan, "without it a lifecycle's any-status row decides and the pin is never asked"
    lo, hi = {"error_4xx": (400, 500)}.get(c.expect_status, (400, 600))
    for node, (status, text) in RECORDED[tool].items():
        assert lo <= status < hi, (node, status, c.expect_status)
        assert any(a in text for a in _alternatives(tool)), (node, text)


@pytest.mark.parametrize("tool", sorted(RECORDED))
def test_the_pin_aims_where_the_lifecycle_aims(tool):
    tables = _lifecycle_tables()
    assert tool in tables, "the lifecycle no longer lists this tool: the pin aims at nothing it measured"
    assert MCP_CONTRACTS[tool].arguments in tables[tool]


@pytest.mark.parametrize("tool", sorted(RECORDED))
def test_the_pin_aims_at_nothing_that_exists(tool):
    args = json.dumps(MCP_CONTRACTS[tool].arguments)
    assert "${" not in args, "a fixture can resolve to a real entity: the refusal would become an action"
    if tool in SAFE_WITHOUT_MARKER:
        return
    assert any(m in args for m in NONEXISTENT), args
