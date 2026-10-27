"""The ledger event types this code emits, by emitter (W3, agentvault2-d6, 2026-10-25; his word: "the event emission
policy which needs hardening and a fe page to check the exact configuration from the fe").

REGISTRY_EMITS and TEG_EMITS are what an AST walk of the registry's and the TEG's source finds: every emit call whose type
is a literal, through the helpers that pass a type on (tests/test_emission_policy_catalog.py pins both sets against the
source, both ways: a new emit needs its entry here and a policy row from a migration; an emit removed takes its entry
with it). The emission gate (event_emitter._get_emission_policy), the boot check (event_emitter.emission_policy_boot_check)
and the admin read (services/emission_policy_view.py) compare these with the event_emission_policies table.

TEG_ALWAYS_ALLOWED is the TEG's own allow that no row overrides (agentvault_teg_layer_mvp event_emitter: its outbox emits
LedgerBalanceChanged whatever the table says). BALANCE_MOVING is event_emitter.BALANCE_MOVING_EVENT_TYPES, the event
store's set: a type in it is counted by the balance projection and may never be marked skip_in_projection."""

REGISTRY_EMITS = frozenset({   # 252 types the registry emits
    "A2APaymentAuthorized", "AccountAnonymized", "AccountDeletionRequested", "AdminBroadcastEdited",
    "AdminBroadcastRetracted", "AdminBroadcastSent", "AdminBulkRefreshCards", "AdminDirectNoticeSent",
    "AgentActTokenMinted", "AgentAutoEnrolled", "AgentCapabilityAttenuated", "AgentCapabilityCircuitBreakerTripped",
    "AgentCapabilityConsumed", "AgentCapabilityIssued", "AgentCapabilityRevoked", "AgentCardJWSVerifyFailed",
    "AgentCardPersistentDrift", "AgentCardPulled", "AgentCloned", "AgentCreated", "AgentCredentialReset",
    "AgentCredentialsRotated", "AgentDelegationGranted", "AgentDelegationRevoked", "AgentExported",
    "AgentFlagAcknowledged", "AgentFlaggedForJWSFailures", "AgentHardDeleted", "AgentHeartbeat", "AgentImported",
    "AgentMtlsEnrolled", "AgentMtlsRevoked", "AgentOnboarded", "AgentOwnershipTransferred", "AgentReinstated",
    "AgentSigningKeyRotated", "AgentSpawned", "AgentStatusChanged", "AgentSuspended", "AgentUpdated",
    "AgentXRegDelegationIssued", "AgentXRegDelegationReceived", "AgentXRegDelegationRevoked", "AttestationDueReminder",
    "AttestationExpired", "AttestationReputationClawed", "AttestationRevoked", "AttestationSubmitted",
    "BridgeTransferExpired", "BundleCreated", "BundleDeleted", "BundleDownloaded", "BundleRated", "BundleReported",
    "BundleVisibilityChanged", "CICDNotificationSent", "CanaryRebalancerErrored", "CanaryRebalancerFunded",
    "CommandCenterAction", "CommandCenterProbe", "CommanderFlaggedDrift", "CommonsAwardPaid", "CommonsSeasonClosed",
    "CommonsSeasonOpened", "ComplianceBaselineAccepted", "ComplianceBaselineRecorded", "ComplianceDryRunDrift",
    "ComplianceEnforcementModeChanged", "CompliancePollCycleCompleted", "ContractAccepted", "ContractAgreed",
    "ContractCancelled", "ContractCompleted", "ContractCreated", "ContractDisputed", "ContractExpired",
    "ContractFailed", "ContractMilestoneReleased", "ContractMilestoneSubmitted", "ContractMirrored", "ContractOffered",
    "ContractResolved", "ContractTemplatePublished", "ContractTemplatePurchased", "ContractWorkSubmitted",
    "CrossFrameTransferInitiated", "CrossFrameTransferRefunded", "CrossFrameTransferReversed",
    "CrossFrameTransferSettled", "CrossRegistryBlockedBySuspension", "CrossRegistryTransferCompleted",
    "CrossTEGTreasuryFunded", "DailyDistributionCompleted", "DeploymentStatusUpdated", "DeploymentTriggered",
    "DeploymentWebhookExhausted", "DeveloperAdminFlagsChanged", "DeveloperDeleted", "DeveloperDisable2FA",
    "DeveloperForceEmailVerify", "DeveloperForcePasswordReset", "DeveloperReinstated", "DeveloperRevokeApiKeys",
    "DeveloperSuspended", "DisputeCompensationApplied", "DisputeCompensationDeferred", "DisputeCompensationMinted",
    "DisputeCompensationRequest", "DisputeFiled", "DisputeResolved", "DisputeSlash", "EigenTrustSignal",
    "EnforcementActionCreated", "EnforcementSlashWaterfallApplied", "EnforcementSlashWaterfallPlanned",
    "EventEmissionPolicyUpdated", "EvidenceSubmitted", "ExchangeCircuitBreakerSet", "ExchangeDividendDeclared",
    "ExchangeDividendPaid", "ExchangeListingApproved", "ExchangeListingCreated", "ExchangeListingHalted",
    "ExchangeOrderCancelled", "ExchangeOrderPlaced", "ExchangePriceBandSet", "ExchangeProposalOpened",
    "ExchangeProposalTallied", "ExchangeShareRefloated", "ExchangeSharesIssued", "ExchangeSharesSplit",
    "ExchangeStopTriggered", "ExchangeTradeExecuted", "ExchangeVoteCast", "FederationLicenseReinstated",
    "FederationLicenseSuspended", "FederationPolicyUpdated", "FederationStateDriftDetected", "FiatPricingConfigUpdated",
    "FiatProviderSignatureFailed", "FiatPurchaseDisputed", "FiatPurchaseInitiated", "FiatPurchaseRefunded",
    "FiatPurchaseSettled", "FiatRoutedSettlementCompleted", "FiatRoutedSettlementInitiated",
    "FrameFederationEstablished", "FrameFederationRevoked", "FrameInvitationApproved", "FrameInvitationRejected",
    "FrameInvitationRequested", "FundingRequestApproved", "FundingRequestCreated", "FundingRequestRejected",
    "FxRouteRefunded", "FxRouteSettled", "FxRouteStranded", "FxSwapRefunded", "FxSwapSettled",
    "GovernancePolicyChangeApplied", "GovernancePolicyChangeFailed", "GuildBidPlaced", "GuildCredentialReceived",
    "GuildOrderAwarded", "GuildOrderCancelled", "GuildOrderDisputed", "GuildOrderPosted", "GuildOrderResolved",
    "GuildOrderSettled", "GuildWorkSubmitted", "OperatorApplicationRevoked", "OperatorCliAction", "OperatorRenamed",
    "OrganizationAgentAuthorityBulkApplied", "OrganizationAgentAuthorityBulkRevoked", "OrganizationCreated",
    "OrganizationDeleted", "OrganizationMemberInvited", "OrganizationMemberJoined", "OrganizationMemberRemoved",
    "OrganizationMemberRoleChanged", "OrganizationOwnershipTransferCancelled", "OrganizationOwnershipTransferDeclined",
    "OrganizationOwnershipTransferExpired", "OrganizationOwnershipTransferInitiated",
    "OrganizationOwnershipTransferred", "OrganizationTreasuryFunded", "OrganizationTreasuryRemitted",
    "OrganizationTreasurySwept", "OrphanedListingsSwept", "PeerRegistryDeactivated", "PeerRegistryReactivated",
    "PeerRegistryUrlAutoCorrected", "PeerSlashConfigUpdated", "PeerTopologyRefreshed", "PeerTrustActionApplied",
    "PeerTrustActionObserved", "PeerTrustStateChanged", "PhoneSessionEnded", "PhoneSessionStarted", "PipelineCreated",
    "PipelineDeleted", "PipelineUpdated", "ProjectionSnapshot", "ProposalAutoTallied", "ProposalCreated",
    "ProposalTallied", "ProvisioningGifted", "RegistryBlacklisted", "RegistryCardUpdated", "RegistryFederated",
    "RegistryQuarantineLifted", "RegistryQuarantined", "RegulatoryAuthorizationRecorded",
    "RegulatoryAuthorizationRevoked", "RegulatoryCountersignBroken", "ReputationBondDeposited",
    "ReputationBondForfeited", "ReputationBondMatured", "ReputationBondReleased", "ReputationBondUnlocked",
    "ReputationChanged", "RewardsAutoCompoundSkipped", "RewardsAutoCompounded", "RewardsDistributed",
    "SettlementCompensationMinted", "SettlementFinalized", "SettlementRolledBack", "SettlementSagaInitiated",
    "SettlementSagaTimedOut", "SettlementSlashConfirmed", "SettlementSlashFailed", "SettlementSlashRequested",
    "SettlementTimeout", "SlashWaterfallChanged", "StakeForceUnstaked", "SupplyInvariantBreach", "TokensBridgeLocked",
    "TokensBridgeUnlocked", "TokensIssued", "TokensStaked", "TokensTransferred", "TokensUnstaked",
    "TransactionFeeCollected", "TreasuryBankruptcyQuarantineTriggered", "TreasuryQuarantineLifted",
    "TreasurySlashReceived", "VersionActivated", "VersionCreated", "VersionRolledBack", "VoteCast",
    "WrappedTokensMinted"
})

TEG_EMITS = frozenset({   # 12 types the TEG emits (its gate refuses those its row gives to the registry)
    "AgentCreated", "AgentUpdated", "CrossTEGStaleOutflowSwept", "CrossTEGStaleSwept", "ExchangeOrphanExrefLegSwept",
    "LedgerBalanceChanged", "NegativeEscrowLockClamped", "OrphanedEscrowLockReleased", "TokensIssued", "TokensStaked",
    "TokensTransferred", "TokensUnstaked"
})

TEG_ALWAYS_ALLOWED = frozenset({"LedgerBalanceChanged"})

ALL_EMITTED = REGISTRY_EMITS | TEG_EMITS
