"""§MCPTEST30 V0643 (agentvault2-aa, 2026-10-25): the by-design reason of each tool that passes only on a refusal.

The router counts a row that passed on a refusal, with no 2xx for its tool anywhere in the run, as not measured (V0635:
"refusal only"), under one generic sentence. For the frame's 41 such rows of V0641's pair nt261025x3 (run
2a89a516f8d94077; scratchpad/mcpgaps/nt261025x3_frame_refusal_only.json) the reason is known and by design: the tool acts
on a real frame, operator, licence or credential, moves value, leaves a record no route removes, is peer-only or not
wired on a sandbox frame, or is an operator's own (sessionlogs2026/BACKLOG_2026-10-19_MCP_REFUSAL_ONLY_PASSES.md, "Still
NOT MEASURED after V0636" and the V0642 candidate section). The flow puts the reason on the tool's row
(`declared_unmeasured`) and the router says it in place of the generic sentence; the refusal stays measured as it was
(each tool's pinned contract or its lifecycle's refusal step). A tool earned anywhere in the run (a 2xx) never shows it.
His rule (2026-10-19): no softened failure class; a row that tested only a refusal says so, and why.
V0644 (agentvault2-66): the operators' own three join them (V0641's read of both sandbox operators, outside the 41).
"""
from __future__ import annotations

from typing import Dict, Optional

BY_DESIGN_REFUSAL: Dict[str, str] = {
    'theprotocol_approveFrameInvitation':
        'approving a frame invitation federates a real frame with this one, which no tester run does',
    'theprotocol_finalizeRetryFrameInvitation':
        'finalizing an invitation federates two frames, which no tester run does',
    'theprotocol_revokeFrame': 'revoking a frame retires a real federated frame, which no tester run does',
    'theprotocol_resyncFrameEventStore':
        "a resync rebuilds a frame's ledger projection, frame-wide, which no tester run does",
    'theprotocol_quarantineRegistry':
        "a quarantine holds a real registry (every roll driver refuses while one is held, and it sends the registry's "
        "operators a critical notice, registry.quarantined); a run quarantines a peer row of its own only on a target "
        'torn down after the run, the nightly and proof pairs (MCP_TESTER_EPHEMERAL_TARGET, earned_ad_ephemeral)',
    'theprotocol_liftQuarantine':
        'a lift needs a registry in quarantine, which a run makes of its own only on the nightly and proof pairs '
        '(earned_ad_ephemeral)',
    'theprotocol_blacklistRegistry':
        'a blacklist cuts a peer registry off the federation and no route removes the row; a run blacklists a peer row '
        'of its own only on the nightly and proof pairs (earned_ad_ephemeral)',
    'theprotocol_approveOperatorApplication':
        'approving an operator application provisions a real operator, which no tester run does',
    'theprotocol_rejectOperatorApplication':
        "a rejection needs an application of the run's own, and one stays in Operator Management for good (no route "
        "removes it), so a run makes and rejects one only on the nightly and proof pairs, last (earned_ad_pair_last, Phase 8)",
    'theprotocol_adminDownloadOperatorBundle':
        "an operator's bundle carries its credentials and exists only for an approved application, so a run downloads "
        "one (its status, type and size, never a byte of it) only from the pair's own operator on the nightly and proof "
        "pairs, last (earned_ad_pair_last, Phase 8)",
    'theprotocol_suspendOperator':
        "suspending an operator stops a real operator's federation, so a run suspends and reinstates only the pair's "
        "own operator on the nightly and proof pairs, last (earned_ad_pair_last, Phase 8)",
    'theprotocol_reinstateOperator':
        "a reinstatement needs a suspended operator, which a run makes only of the pair's own operator on the nightly "
        "and proof pairs, last (earned_ad_pair_last, Phase 8)",
    'theprotocol_revokeOperatorAccess':
        "revoking an operator's access ends a real operator, so a run revokes only the pair's own operator, as its very "
        "last step on the nightly and proof pairs (earned_ad_pair_last, Phase 8)",
    'theprotocol_rotateOperatorPullToken':
        "rotating an operator's image pull token breaks that real operator's next pull until it takes the new one, so "
        "a run rotates only the pair's own operator's, on the nightly and proof pairs, last (earned_ad_pair_last, Phase 8)",
    'theprotocol_suspendFederationLicense':
        'a run mints a federation licence of its own (a real credential) only on a target torn down after the run, the '
        'nightly and proof pairs (MCP_TESTER_EPHEMERAL_TARGET, earned_ad_ephemeral), so on a standing frame it has none '
        'to suspend',
    'theprotocol_reinstateFederationLicense':
        'a run mints a federation licence of its own only on the nightly and proof pairs (earned_ad_ephemeral), so on a '
        'standing frame it has none to reinstate',
    'theprotocol_revokeFederationLicense':
        'a run mints a federation licence of its own only on the nightly and proof pairs (earned_ad_ephemeral), so on a '
        'standing frame it has none to revoke',
    'theprotocol_deleteFederationLicense':
        'a run mints a federation licence of its own only on the nightly and proof pairs (earned_ad_ephemeral), so on a '
        'standing frame it has none to delete',
    # §MCPTEST30 (tester batch 2 item 2): the two bridge routes only the bridge's other registry calls; refusal-only on
    # sbx-alpha, the one frame running the bridge (the switch table holds them elsewhere)
    'theprotocol_bridgeIssueWrapped':
        "a route only the bridge's other registry calls (a federation peer's identity), so no MCP caller has a success "
        "path; the Token Bridge is on the D8 retire list, his decision, and runs only where TOKEN_BRIDGE_ENABLED is on",
    'theprotocol_bridgeUnlock':
        "a route only the bridge's other registry calls (a federation peer's identity), so no MCP caller has a success "
        "path; the Token Bridge is on the D8 retire list, his decision, and runs only where TOKEN_BRIDGE_ENABLED is on",
    # §MCPTEST30 (tester batch 2 item 3): the commons season's money steps
    'theprotocol_adminCommonsPaySeason':
        "paying a season moves units from the payout waterfall to its winners, so a run pays only a season of its own, "
        "on the nightly and proof pairs (the commons season lifecycle); elsewhere it is held to its refusal on the "
        "open season",
    'theprotocol_adminCommonsWriteOffAward':
        "a write-off settles only an award whose payment failed or never answered, which a healthy target never gives "
        "a run; its refusal is measured on the open season and, on the pairs, on the award that was never sent",
    'theprotocol_uploadRegistryCardIcon':
        "the icon is the registry's own, on its signed registry card, so a run replaces it and puts it back only on "
        "the nightly and proof pairs, last (earned_ad_pair_last, Phase 8)",
    # keyed by the tool's live name since V0650: under its old name (tegTreasuryMint, mcp/tool_aliases.py) the reason
    # reached no row, and the pair's tegTreasuryIssue row read the generic sentence (agentvault2-d3, 2026-10-31)
    'theprotocol_tegTreasuryIssue': 'minting is never automated (his decision D9: no automated mint)',
    'theprotocol_refundFiatPurchase':
        'a fiat purchase exists only after a card payment through the euro on-ramp, which no tester run makes (an '
        "operator has no on-ramp: the fiat rail is a mainframe's, FIAT_GENESIS_REGISTRY)",
    'theprotocol_replayFiatPurchase':
        'a fiat purchase exists only after a card payment through the euro on-ramp, which no tester run makes (an '
        "operator has no on-ramp: the fiat rail is a mainframe's, FIAT_GENESIS_REGISTRY)",
    'theprotocol_resendFiatMagicLink':
        'a fiat purchase exists only after a card payment through the euro on-ramp, which no tester run makes (an '
        "operator has no on-ramp: the fiat rail is a mainframe's, FIAT_GENESIS_REGISTRY)",
    'theprotocol_fireCanaryPath':
        'a canary fire moves real units between registries, and only a master runner fires a path by hand: an '
        "operator's runner is a follower, which answers a manual fire 409 (earned_ad_platform's own row says so), and "
        'a registry with no active path has none to fire',
    'theprotocol_toggleCanaryPath':
        "a toggle changes a real canary path's schedule, so the run toggles one only where the registry holds an "
        'active path, off and on again (earned_ad_platform); where none is held there is none to toggle',
    'theprotocol_requestFrame':
        "a frame request stays in Frame Management for good (no route removes it) and is mailed to the network's "
        "commander address, so a run makes one only on the nightly and proof pairs, which mail nobody (earned_ad_pair_last, Phase 8)",
    'theprotocol_updateEnforcementPolicy':
        "a policy write records an amendment to the registry's enforcement policy, for every agent",
    'theprotocol_acknowledgeAgentFlag':
        'a flag exists only where a card-drift or collusion check raised one against an agent, which no tester run '
        'makes',
    'theprotocol_triggerDiagnosticAction':
        "a diagnostic action acts on a real component (restart, resync); the command centre's read on the frame itself "
        'is measured (earned: rows) where it answers',
    'theprotocol_completeAdmission':
        'an admission completes only for a registry the federation admitted through its admission rail, which no '
        'sandbox registry is',
    'theprotocol_federationPolicyUpdateRequest':
        "a policy update rewrites the stored policy of a federated peer registry, so a run updates only a peer row of "
        "its own, on the nightly and proof pairs (earned_ad_ephemeral)",
    'theprotocol_federationCliAudit':
        "the remote CLI's audit events need a federation licence header, which no MCP caller carries",
    'theprotocol_adminGrafanaQuery': 'no Grafana credentials on a sandbox registry (GRAFANA_ADMIN_PASS unset)',
    'theprotocol_deleteOauthFederationTrust':
        'no trusted OAuth registry on a sandbox registry (its trust list is empty)',
    'theprotocol_oauthIntrospect': 'no trusted OAuth registry on a sandbox registry (the route answers 501)',
    'theprotocol_oauthRevoke': 'no trusted OAuth registry on a sandbox registry (the route answers 501)',
    'theprotocol_oauthTokenExchange': 'no trusted OAuth registry on a sandbox registry (the route answers 501)',
    'theprotocol_simulationFundingPreview':
        "the retired network's simulation tooling: the route runs a host script through the docker socket and cannot do"
        ' its job on the new registries (the product half is his call)',
    'theprotocol_forceEmailVerify':
        "a sandbox registry verifies an account when it registers, so no run's account waits for a verify",
    'theprotocol_operatorPortalSelfLogs':
        "an operator's own tool: on a frame the route refuses; the operator runs earn it",
    'theprotocol_getOperatorMyBundle':
        "an operator's own tool: on a frame the route refuses; the operator runs earn it",
    # §MCPTEST30 V0644 (agentvault2-66): the operators' own refusal-only tools outside the frame's 41 (V0641's read of
    # both sandbox operators, 1423 rows each, 18 refusal-only; slashAgentStake is slashAgent since V0643's W3; the fourth,
    # logTegDispute, is earned on an operator since V0644: earned_disputes files the run's own TEG dispute there)
    'theprotocol_acceptComplianceBaseline':
        'a baseline is accepted only for a federated peer whose compliance this registry monitors and which still '
        "publishes the baseline on record (accepting a drift is an admin's decision); the monitor runs on a frame "
        '(IS_CENTRAL_REGISTRY), so an operator holds no such peer',
    'theprotocol_guildCrossRegistryBid':
        'a cross-registry bid needs an order on a peer frame, and the lifecycle that earns it '
        '(earned_guild_cross_registry) needs both frames of a pair, which an operator run does not have',
    'theprotocol_slashAgent':
        'a slash burns locked units, so the run slashes only one unit of a lock its own throwaway agent made '
        '(earned_ad_agents); where locks are switched off (STAKING_ENABLED=false, as on production and both sandbox '
        'operators) there is none to slash',
    # §MCPTEST30 V0644 (agentvault2-66, agentvault2-aa's word 2026-10-26): three routes that answer only on a sandbox frame.
    # SANDBOX_MODE stays unset on the operators (it turns on more than these three), so on an operator each row says why
    # (the lifecycle's 403 under expect_status='any' carries this reason); on a frame they are earned and it never shows
    'theprotocol_previewVotingPowerAttestation':
        "a sandbox-only route: SANDBOX_MODE is a sandbox frame's switch, which an operator does not set",
    'theprotocol_runAttestationExpirySweep':
        "a sandbox-only route: SANDBOX_MODE is a sandbox frame's switch, which an operator does not set",
    'theprotocol_runAttestationScheduleCron':
        "a sandbox-only route: SANDBOX_MODE is a sandbox frame's switch, which an operator does not set",
}


def declared(tool: str) -> Optional[str]:
    """The by-design reason a tool's refusal-only row carries, or None."""
    return BY_DESIGN_REFUSAL.get(str(tool or ""))
