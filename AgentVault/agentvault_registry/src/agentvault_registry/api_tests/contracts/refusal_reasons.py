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
        'operators a critical notice, registry.quarantined), which no tester run does',
    'theprotocol_liftQuarantine':
        'a lift needs a registry in quarantine, which no tester run makes (a quarantine holds a real registry)',
    'theprotocol_blacklistRegistry':
        'a blacklist cuts a real peer registry off the federation, which no tester run does',
    'theprotocol_approveOperatorApplication':
        'approving an operator application provisions a real operator, which no tester run does',
    'theprotocol_rejectOperatorApplication':
        "a rejection needs an application of the run's own, and one stays in Operator Management for good (no route "
        'removes it)',
    'theprotocol_adminDownloadOperatorBundle':
        "an operator's bundle carries its credentials, and it exists only for an approved application, which no tester "
        'run makes',
    'theprotocol_suspendOperator':
        "suspending an operator stops a real operator's federation, which no tester run does",
    'theprotocol_reinstateOperator': 'a reinstatement needs a suspended operator, which no tester run makes',
    'theprotocol_revokeOperatorAccess': "revoking an operator's access ends a real operator, which no tester run does",
    'theprotocol_rotateOperatorPullToken':
        "rotating an operator's image pull token breaks that real operator's next pull until it takes the new one, "
        'which no tester run does',
    'theprotocol_suspendFederationLicense':
        'the run never mints a federation licence (a well-formed generateFederationLicense makes a real credential), so'
        ' it has none of its own to suspend',
    'theprotocol_reinstateFederationLicense':
        'the run never mints a federation licence, so it has none of its own to reinstate',
    'theprotocol_revokeFederationLicense':
        'the run never mints a federation licence, so it has none of its own to revoke',
    'theprotocol_deleteFederationLicense':
        'the run never mints a federation licence, so it has none of its own to delete',
    'theprotocol_uploadRegistryCardIcon':
        "the icon is the registry's own, on its signed registry card, which no tester run changes",
    'theprotocol_tegTreasuryMint': 'minting is never automated (his decision D9: no automated mint)',
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
    'theprotocol_requestFrame': 'a frame request stays in Frame Management for good (no route removes it)',
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
        'a policy update request goes to a real peer registry, which no tester run asks',
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
