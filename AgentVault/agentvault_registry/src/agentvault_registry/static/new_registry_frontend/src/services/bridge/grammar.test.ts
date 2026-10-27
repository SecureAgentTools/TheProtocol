// @vitest-environment node
/**
 * grammar.test.ts — §BRIDGE #B1 unit suite.
 *
 * Runs in the `node` environment on purpose: the grammar is PURE, so it must be
 * provable without a DOM. (The repo's vitest default environment is happy-dom,
 * which is not installed here — a pure unit suite should not depend on it.)
 *
 * The stage is untestable (WebGL). Its MEANING is not. Everything the bridge
 * claims about an event is decided here, so this suite is the real gate.
 *
 * Mutation-verified 2026-08-18: each block below was confirmed to FAIL when the
 * corresponding behaviour in grammar.ts was inverted. A suite that cannot fail
 * measures nothing (§29e).
 */
import { describe, it, expect, beforeEach } from 'vitest'
import {
  toVerb,
  unwrapEnvelope,
  classifyAmount,
  correlationKeyFor,
  describeVerb,
  humaneAmount,
  involvesDids,
  VERB_TABLE,
  SILENT_BY_DESIGN,
  _resetSeq,
  type GrammarContext,
} from './grammar'

/**
 * The LIVE union of event types across the Frame A (144) and Frame C (140)
 * EventStores, measured 2026-08-18 by
 *   SELECT DISTINCT event_type FROM events
 * on both databases. 194 types. This is ground truth, not a guess — the grammar
 * is asserted total over exactly this set.
 */
const LIVE_EVENT_TYPES: readonly string[] = [
  'A2APaymentAuthorized', 'AccountDeletionRequested', 'AdminBroadcastRetracted', 'AdminBroadcastSent',
  'AdminBulkRefreshCards', 'AgentActTokenMinted', 'AgentCapabilityAttenuated',
  'AgentCapabilityCircuitBreakerTripped', 'AgentCapabilityConsumed', 'AgentCapabilityIssued',
  'AgentCapabilityRevoked', 'AgentCardJWSVerifyFailed', 'AgentCardPersistentDrift', 'AgentCardPulled',
  'AgentCreated', 'AgentCredentialReset', 'AgentCredentialsRotated', 'AgentDelegationGranted',
  'AgentDelegationRevoked', 'AgentExported', 'AgentFlaggedForJWSFailures', 'AgentHardDeleted',
  'AgentHeartbeat', 'AgentImported', 'AgentMtlsEnrolled', 'AgentMtlsRevoked', 'AgentOnboarded',
  'AgentOwnershipTransferred', 'AgentReinstated', 'AgentSigningKeyRotated', 'AgentSpawned',
  'AgentStatusChanged', 'AgentSuspended', 'AgentXRegDelegationIssued', 'AgentXRegDelegationReceived',
  'AttestationSubmitted', 'BalanceCorrected', 'BundleCreated', 'CanaryRebalancerErrored',
  'CanaryRebalancerFunded', 'CommandCenterAction', 'CommandCenterProbe', 'ComplianceDryRunDrift',
  'ComplianceEnforcementModeChanged', 'CompliancePollCycleCompleted', 'ContractAccepted',
  'ContractAgreed', 'ContractCancelled', 'ContractCompleted', 'ContractCreated', 'ContractDisputed',
  'ContractExpired', 'ContractFailed', 'ContractMilestoneReleased', 'ContractMilestoneSubmitted',
  'ContractMirrored', 'ContractOffered', 'ContractResolved', 'ContractTemplatePublished',
  'ContractTemplatePurchased', 'ContractWorkSubmitted', 'CrossFrameTransferInitiated',
  'CrossFrameTransferRefunded', 'CrossFrameTransferReversed', 'CrossFrameTransferSettled',
  'CrossRegistryBlockedBySuspension', 'CrossRegistryTransferCompleted',
  'CrossTEGCoordinationAbortedByExpiry', 'CrossTEGCoordinationCommitResumed', 'CrossTEGStaleSwept',
  'CrossTEGTreasuryFunded', 'DailyDistributionCompleted', 'DeploymentStatusUpdated',
  'DeploymentTriggered', 'DeploymentWebhookExhausted', 'DeveloperAdminFlagsChanged', 'DeveloperDeleted',
  'DeveloperForceEmailVerify', 'DeveloperForcePasswordReset', 'DeveloperReinstated',
  'DeveloperSuspended', 'DisputeCompensationApplied', 'DisputeCompensationDeferred',
  'DisputeCompensationMinted', 'DisputeCompensationRequest', 'DisputeFiled', 'DisputeResolved',
  'EigenTrustSignal', 'EnforcementActionCreated', 'EvidenceSubmitted', 'ExchangeCircuitBreakerSet',
  'ExchangeDividendDeclared', 'ExchangeDividendPaid', 'ExchangeListingApproved',
  'ExchangeListingCreated', 'ExchangeListingHalted', 'ExchangeOrderCancelled', 'ExchangeOrderPlaced',
  'ExchangeProposalOpened', 'ExchangeProposalTallied', 'ExchangeShareRefloated', 'ExchangeSharesIssued',
  'ExchangeSharesSplit', 'ExchangeStopTriggered', 'ExchangeTradeExecuted', 'ExchangeVoteCast',
  'FederationLicenseReinstated', 'FederationLicenseSuspended', 'FederationPolicyUpdated',
  'FederationStateDriftDetected', 'FiatPurchaseInitiated', 'FiatPurchaseSettled',
  'FrameInvitationApproved', 'FrameInvitationRequested', 'FundingRequestApproved',
  'FundingRequestCreated', 'FxRouteRefunded', 'FxRouteSettled', 'FxSwapRefunded', 'FxSwapSettled',
  'GuildBidPlaced', 'GuildCredentialReceived', 'GuildOrderAwarded', 'GuildOrderCancelled',
  'GuildOrderDisputed', 'GuildOrderPosted', 'GuildOrderResolved', 'GuildOrderSettled',
  'GuildWorkSubmitted', 'HagridCemeteryCensus', 'HagridConcentration', 'HagridConservation',
  'HagridFeudalism', 'HagridGiniSnapshot', 'HagridInfancy', 'HagridLifecycle', 'HagridManifesto',
  'HagridPlutocracy', 'HagridSybilRing', 'LedgerBalanceChanged', 'OperatorApplicationRevoked',
  'OperatorRenamed', 'OrganizationAgentAuthorityBulkApplied', 'OrganizationAgentAuthorityBulkRevoked',
  'OrganizationCreated', 'OrganizationDeleted', 'OrganizationMemberInvited', 'OrganizationMemberJoined',
  'OrganizationMemberRemoved', 'OrganizationMemberRoleChanged', 'OrganizationOwnershipTransferCancelled',
  'OrganizationOwnershipTransferDeclined', 'OrganizationOwnershipTransferExpired',
  'OrganizationOwnershipTransferInitiated', 'OrganizationOwnershipTransferred',
  'OrganizationTreasuryFunded', 'OrganizationTreasuryRemitted', 'OrganizationTreasurySwept',
  'PeerRegistryDeactivated', 'PeerRegistryReactivated', 'PeerRegistryUrlAutoCorrected',
  'PeerTopologyRefreshed', 'PhoneSessionStarted', 'PipelineCreated', 'PipelineDeleted',
  'PipelineUpdated', 'ProjectionSnapshot', 'ProposalAutoTallied', 'ProposalCreated',
  'RegistryCardUpdated', 'RegulatoryAuthorizationRecorded', 'RegulatoryAuthorizationRevoked',
  'RegulatoryCountersignBroken', 'ReputationBondDeposited', 'ReputationChanged',
  'RewardsAutoCompounded', 'RewardsAutoCompoundSkipped', 'RewardsDistributed', 'SupplyInvariantBreach',
  'TestEvent', 'TokensBridgeLocked', 'TokensIssued', 'TokensStaked', 'TokensTransferred',
  'TokensUnstaked', 'TransactionFeeCollected', 'TreasuryBankruptcyQuarantineTriggered',
  'TreasurySlashReceived', 'VersionActivated', 'VersionCreated', 'VersionRolledBack', 'VoteCast',
  'WebhookRetryExhausted', 'WitnessIssued',
]

const CTX: GrammarContext = { frame: 'C', frameCurrency: 'BVT', localRegistry: 'frame-c', now: 1_755_000_000_000 }

/** EventStore envelope shape: {type:'event', event:{event_type, data:{...}}}. */
function esEnvelope(eventType: string, data: Record<string, any> = {}, extra: Record<string, any> = {}) {
  return {
    type: 'event',
    event: { id: 'evt-1', event_type: eventType, aggregate_id: 'did:theprotocol:agg', timestamp: '2026-08-18T16:34:12Z', data, ...extra },
  }
}

beforeEach(() => _resetSeq())

// ─────────────────────────────────────────────────────────────────────────────
describe('coverage over the LIVE event inventory', () => {
  it('the measured inventory is exactly 194 types', () => {
    expect(new Set(LIVE_EVENT_TYPES).size).toBe(194)
  })

  it('every live type is either mapped to a verb or explicitly silent (no accidental gaps)', () => {
    const unaccounted = LIVE_EVENT_TYPES.filter(
      t => !(t in VERB_TABLE) && !SILENT_BY_DESIGN.has(t),
    )
    expect(unaccounted).toEqual([])
  })

  it('no type is both drawn and silent (the two sets never contradict)', () => {
    const both = Object.keys(VERB_TABLE).filter(t => SILENT_BY_DESIGN.has(t))
    expect(both).toEqual([])
  })

  it('the grammar is TOTAL: every live type returns a descriptor or null, never throws', () => {
    for (const t of LIVE_EVENT_TYPES) {
      expect(() => toVerb(esEnvelope(t), CTX)).not.toThrow()
    }
  })

  it('draws a non-trivial share of the inventory (the table is not a stub)', () => {
    const drawn = LIVE_EVENT_TYPES.filter(t => toVerb(esEnvelope(t), CTX) !== null)
    expect(drawn.length).toBeGreaterThan(80)
  })

  it('every one of the seven verbs plus both garnishes is reachable from real types', () => {
    const seen = new Set<string>()
    for (const t of LIVE_EVENT_TYPES) {
      const d = toVerb(esEnvelope(t), CTX)
      if (d) seen.add(d.verb)
    }
    expect([...seen].sort()).toEqual(
      ['alarm', 'birth', 'canary', 'corridor', 'fx', 'guild', 'trade', 'transfer', 'treasury'],
    )
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('honesty rules', () => {
  it('LedgerBalanceChanged draws NOTHING (accounting shadow of movements already drawn)', () => {
    // 8.1M rows on frame-c alone. Drawing it would double-count every transfer.
    expect(toVerb(esEnvelope('LedgerBalanceChanged', { amount: '500' }), CTX)).toBeNull()
    expect(SILENT_BY_DESIGN.has('LedgerBalanceChanged')).toBe(true)
  })

  it('trust events draw nothing (trust is a collar, never traffic)', () => {
    for (const t of ['ReputationChanged', 'AttestationSubmitted', 'EigenTrustSignal', 'WitnessIssued']) {
      expect(toVerb(esEnvelope(t), CTX)).toBeNull()
    }
  })

  it('an unknown event type draws nothing (no invented motion)', () => {
    expect(toVerb(esEnvelope('SomethingWeHaveNeverSeen'), CTX)).toBeNull()
  })

  it('ALARM is breach class only, and routine failure is never an alarm', () => {
    const alarms = Object.entries(VERB_TABLE).filter(([, r]) => r.verb === 'alarm').map(([k]) => k)
    expect(alarms.sort()).toEqual([
      'AgentCapabilityCircuitBreakerTripped',
      'CrossRegistryBlockedBySuspension',
      'FederationLicenseSuspended',
      'RegulatoryCountersignBroken',
      'SupplyInvariantBreach',
      'TreasuryBankruptcyQuarantineTriggered',
    ])
    // Refunds, halts and swept 2PC rows are routine. They must NOT be red.
    for (const t of ['FxRouteRefunded', 'ExchangeListingHalted', 'CrossTEGStaleSwept', 'ExchangeOrderCancelled']) {
      expect(toVerb(esEnvelope(t), CTX)!.verb).not.toBe('alarm')
    }
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('envelope unwrapping (every shape production actually emits)', () => {
  it('EventStore shape {type:event, event:{...}}', () => {
    const d = toVerb(esEnvelope('TokensTransferred', { amount: 41.2 }), CTX)
    expect(d?.eventType).toBe('TokensTransferred')
    expect(d?.amount).toBe(41.2)
  })

  it('registry broadcast shape {type:event, data:{...}}', () => {
    const d = toVerb({ type: 'event', data: { event_type: 'AgentCreated', agent_did: 'did:x:1' } }, CTX)
    expect(d?.verb).toBe('birth')
    expect(d?.actorDid).toBe('did:x:1')
  })

  it('already-unwrapped shape {event_type, ...}', () => {
    const d = toVerb({ event_type: 'GuildOrderSettled', data: { amount: 234 } }, CTX)
    expect(d?.verb).toBe('guild')
    expect(d?.amount).toBe(234)
  })

  it('JSON-stringified data at one level', () => {
    const d = toVerb({ type: 'event', event: { event_type: 'TokensTransferred', data: JSON.stringify({ amount: 7 }) } }, CTX)
    expect(d?.amount).toBe(7)
  })

  it('JSON-stringified data at two levels (backend does this under load)', () => {
    const d = toVerb(
      { type: 'event', event: { event_type: 'TokensTransferred', data: { data: JSON.stringify({ amount: 9 }) } } },
      CTX,
    )
    expect(d?.amount).toBe(9)
  })

  it('malformed input never throws and never fabricates', () => {
    for (const junk of [null, undefined, 0, 'x', [], {}, { type: 'event' }, { event: 'not json {' }]) {
      expect(() => toVerb(junk as any, CTX)).not.toThrow()
      expect(toVerb(junk as any, CTX)).toBeNull()
    }
  })

  it('unwrapEnvelope tolerates unparseable stringified data instead of exploding', () => {
    expect(unwrapEnvelope({ event: '{ broken' })).toBeNull()
    expect(unwrapEnvelope({ type: 'event', event: { event_type: 'X', data: '{ broken' } })).toMatchObject({ event_type: 'X' })
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('amount extraction and classification', () => {
  it('buckets are decades, so brightness reads as log(amount)', () => {
    expect(classifyAmount(null)).toBe(0)
    expect(classifyAmount(0)).toBe(0)
    expect(classifyAmount(0.5)).toBe(1)
    expect(classifyAmount(9.99)).toBe(1)
    expect(classifyAmount(10)).toBe(2)
    expect(classifyAmount(999)).toBe(2)
    expect(classifyAmount(1_000)).toBe(3)
    expect(classifyAmount(99_999)).toBe(3)
    expect(classifyAmount(100_000)).toBe(4)
    expect(classifyAmount(6.9e8)).toBe(4)
  })

  it('negative amounts classify by magnitude', () => {
    expect(classifyAmount(-500)).toBe(2)
  })

  it('parses SCIENTIFIC NOTATION balances ("1E+3") — the documented API shape', () => {
    // §OPGUIDE-2: balances come back as "1E+3"; int() raises, parseFloat is correct.
    const d = toVerb(esEnvelope('TokensTransferred', { amount: '1E+3' }), CTX)
    expect(d?.amount).toBe(1000)
    expect(d?.amountClass).toBe(3)
  })

  it('a non-numeric amount yields null, not NaN', () => {
    const d = toVerb(esEnvelope('TokensTransferred', { amount: 'none' }), CTX)
    expect(d?.amount).toBeNull()
    expect(d?.amountClass).toBe(0)
  })

  it('finds an amount nested inside the payload', () => {
    const d = toVerb(esEnvelope('GuildOrderSettled', { settlement: { detail: { amount: 234 } } }), CTX)
    expect(d?.amount).toBe(234)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('parties, frames and currency', () => {
  it('extracts sender and receiver DIDs', () => {
    const d = toVerb(esEnvelope('TokensTransferred', { sender_did: 'did:a', receiver_did: 'did:b' }), CTX)
    expect(d?.fromDid).toBe('did:a')
    expect(d?.toDid).toBe('did:b')
  })

  it('falls back to the delivering frame currency when the payload is silent', () => {
    expect(toVerb(esEnvelope('TokensTransferred'), CTX)?.currency).toBe('BVT')
  })

  it('payload currency beats the frame default', () => {
    expect(toVerb(esEnvelope('TokensTransferred', { currency: 'JDAY' }), CTX)?.currency).toBe('JDAY')
  })

  it('origin registry falls back to the local registry, destination does not', () => {
    const d = toVerb(esEnvelope('TokensTransferred'), CTX)
    expect(d?.from).toBe('frame-c')
    expect(d?.to).toBeNull()   // never invent a destination
  })

  it('carries cross-frame endpoints so the arc can recolor at the midpoint', () => {
    const d = toVerb(esEnvelope('FxRouteSettled', { from_frame: 'A', to_frame: 'C', amount: 100 }), CTX)
    expect(d?.verb).toBe('fx')
    expect(d?.fromFrame).toBe('A')
    expect(d?.toFrame).toBe('C')
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('mine (the fleet lens predicate)', () => {
  const mineCtx: GrammarContext = { ...CTX, mineDids: new Set(['did:mine']) }

  it('marks an event mine when the viewer is the sender', () => {
    expect(toVerb(esEnvelope('TokensTransferred', { sender_did: 'did:mine' }), mineCtx)?.mine).toBe(true)
  })

  it('marks an event mine when the viewer is the receiver', () => {
    expect(toVerb(esEnvelope('TokensTransferred', { receiver_did: 'did:mine' }), mineCtx)?.mine).toBe(true)
  })

  it('marks an event mine when the viewer is the actor', () => {
    expect(toVerb(esEnvelope('AgentCreated', { agent_did: 'did:mine' }), mineCtx)?.mine).toBe(true)
  })

  it('is case-insensitive on the DID', () => {
    expect(toVerb(esEnvelope('TokensTransferred', { sender_did: 'DID:MINE' }), mineCtx)?.mine).toBe(true)
  })

  it('is false for a stranger, and false when the viewer owns nothing', () => {
    expect(toVerb(esEnvelope('TokensTransferred', { sender_did: 'did:other' }), mineCtx)?.mine).toBe(false)
    expect(toVerb(esEnvelope('TokensTransferred', { sender_did: 'did:mine' }), CTX)?.mine).toBe(false)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('correlation keys (composed sequences)', () => {
  it('a guild order id wins for guild and contract events', () => {
    expect(correlationKeyFor({ order_id: 'o1' }, 'GuildOrderSettled')).toBe('guild-o1')
    expect(correlationKeyFor({ order_id: 'o1' }, 'ContractCompleted')).toBe('guild-o1')
  })

  it('an order id on a NON guild event does not become a guild thread', () => {
    expect(correlationKeyFor({ order_id: 'o1' }, 'ExchangeOrderPlaced')).toBeNull()
  })

  it('an fx route id threads a cross-frame story', () => {
    expect(correlationKeyFor({ route_id: 'r9' }, 'FxRouteSettled')).toBe('fxroute:r9')
  })

  it('precedence: route beats contract beats swap beats idempotency beats tx', () => {
    expect(correlationKeyFor({ route_id: 'r', contract_id: 'c', swap_id: 's', idempotency_key: 'i', transaction_id: 't' }, 'X'))
      .toBe('fxroute:r')
    expect(correlationKeyFor({ contract_id: 'c', swap_id: 's', idempotency_key: 'i' }, 'X')).toBe('contract:c')
    expect(correlationKeyFor({ swap_id: 's', idempotency_key: 'i' }, 'X')).toBe('fxswap:s')
    expect(correlationKeyFor({ idempotency_key: 'i', transaction_id: 't' }, 'X')).toBe('idem:i')
    expect(correlationKeyFor({ transaction_id: 't' }, 'X')).toBe('tx:t')
  })

  it('no key at all is null, not an empty string', () => {
    expect(correlationKeyFor({}, 'X')).toBeNull()
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('identity, timestamps and the receipt door', () => {
  it('id is frame-scoped and stable when the event carries an id', () => {
    const d = toVerb(esEnvelope('TokensTransferred'), CTX)
    expect(d?.id).toBe('C:evt-1')
  })

  it('ids stay unique when the event carries no id', () => {
    const a = toVerb({ event_type: 'AgentCreated' }, CTX)
    const b = toVerb({ event_type: 'AgentCreated' }, CTX)
    expect(a!.id).not.toBe(b!.id)
  })

  it('uses the payload timestamp when present', () => {
    const d = toVerb(esEnvelope('TokensTransferred'), CTX)
    expect(d?.ts).toBe('2026-08-18T16:34:12Z')
    expect(d?.tsMs).toBe(Date.parse('2026-08-18T16:34:12Z'))
  })

  it('falls back to delivery time when the timestamp is missing or garbage', () => {
    expect(toVerb({ event_type: 'AgentCreated' }, CTX)?.tsMs).toBe(CTX.now)
    expect(toVerb({ event_type: 'AgentCreated', timestamp: 'not-a-date' }, CTX)?.tsMs).toBe(CTX.now)
  })

  it('carries a receipt reference so any photon can be opened', () => {
    const d = toVerb(esEnvelope('TokensTransferred'), CTX)
    expect(d?.receiptRef).toEqual({ eventId: 'evt-1', aggregateId: 'did:theprotocol:agg' })
  })

  it('marks the failure half of a verb as reverted, and the success half as not', () => {
    expect(toVerb(esEnvelope('FxRouteRefunded'), CTX)?.reverted).toBe(true)
    expect(toVerb(esEnvelope('FxRouteSettled'), CTX)?.reverted).toBe(false)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('humane rendering (the fleet log speaks sentences)', () => {
  it('compacts numbers by magnitude', () => {
    expect(humaneAmount(null)).toBeNull()
    expect(humaneAmount(0.25)).toBe('0.25')
    expect(humaneAmount(41.2)).toBe('41.20')
    expect(humaneAmount(1234)).toBe('1.2K')
    expect(humaneAmount(690_428_904.78)).toBe('690.43M')
    expect(humaneAmount(1.51e9)).toBe('1.51B')
  })

  it('names a payment with both parties when it knows them', () => {
    const d = toVerb(esEnvelope('TokensTransferred', { sender_did: 'did:a', receiver_did: 'did:b', amount: 234, currency: 'BVT' }), CTX)!
    const nameFor = (did: string | null) => (did === 'did:b' ? 'Caspian Manifest Services' : null)
    expect(describeVerb(d, nameFor)).toBe('did:a paid Caspian Manifest Services 234.00 BVT')
  })

  it('says a settled guild order paid the worker', () => {
    const d = toVerb(esEnvelope('GuildOrderSettled', { worker_did: 'did:w', amount: 234, currency: 'BVT' }), CTX)!
    expect(describeVerb(d, () => 'Caspian Manifest Services'))
      .toBe('Caspian Manifest Services was paid 234.00 BVT for completed work')
  })

  it('names the frames a cross-frame move crossed', () => {
    const d = toVerb(esEnvelope('FxRouteSettled', { from_frame: 'B', to_frame: 'C', amount: 242.99, currency: 'JDAY' }), CTX)!
    expect(describeVerb(d)).toBe('242.99 JDAY crossed frames B to C')
  })

  it('shortens a long DID instead of printing raw hex', () => {
    const d = toVerb(esEnvelope('AgentCreated', { agent_did: 'did:theprotocol:0123456789abcdef0123' }), CTX)!
    expect(describeVerb(d)).toBe('did:theproto...0123 came online')
  })

  it('produces a sentence for every verb (no verb renders as an empty string)', () => {
    const samples: Record<string, string> = {
      transfer: 'TokensTransferred', fx: 'FxRouteSettled', trade: 'ExchangeTradeExecuted',
      guild: 'GuildOrderPosted', birth: 'AgentCreated', treasury: 'TokensStaked',
      alarm: 'SupplyInvariantBreach', canary: 'CommandCenterProbe', corridor: 'PeerTopologyRefreshed',
    }
    for (const [verb, type] of Object.entries(samples)) {
      const d = toVerb(esEnvelope(type), CTX)!
      expect(d.verb).toBe(verb)
      expect(describeVerb(d).length).toBeGreaterThan(3)
    }
  })
})

// ─────────────────────────────────────────────────────────────────────────────
describe('involvesDids — the LIVE LEDGER\'s "mine" scope', () => {
  const MINE = new Set(['did:theprotocol:mine'])

  it('matches the sender', () => {
    expect(involvesDids(esEnvelope('TokensTransferred', { sender_did: 'did:theprotocol:mine' }), MINE)).toBe(true)
  })

  it('matches the receiver', () => {
    expect(involvesDids(esEnvelope('TokensTransferred', { receiver_did: 'did:theprotocol:mine' }), MINE)).toBe(true)
  })

  it('matches the actor of a one-sided event', () => {
    expect(involvesDids(esEnvelope('TokensStaked', { agent_did: 'did:theprotocol:mine' }), MINE)).toBe(true)
  })

  it('matches on the envelope aggregate_id, which is where agent-scoped events carry the subject', () => {
    const env = esEnvelope('AgentCreated', {}, { aggregate_id: 'did:theprotocol:mine' })
    expect(involvesDids(env, MINE)).toBe(true)
  })

  it('is case-insensitive on the DID', () => {
    expect(involvesDids(esEnvelope('TokensTransferred', { sender_did: 'DID:THEPROTOCOL:MINE' }), MINE)).toBe(true)
  })

  it('says false for somebody else, which is the whole point of the scope', () => {
    expect(involvesDids(esEnvelope('TokensTransferred', { sender_did: 'did:theprotocol:someone' }), MINE)).toBe(false)
  })

  it('works for SILENT-BY-DESIGN types too — the ledger lists what the stage will not draw', () => {
    const env = esEnvelope('LedgerBalanceChanged', { agent_did: 'did:theprotocol:mine' })
    expect(involvesDids(env, MINE)).toBe(true)
    expect(SILENT_BY_DESIGN.has('LedgerBalanceChanged')).toBe(true)
  })

  it('never throws and never matches on an empty set or junk input', () => {
    expect(involvesDids(esEnvelope('TokensTransferred', { sender_did: 'did:theprotocol:mine' }), new Set())).toBe(false)
    expect(involvesDids(null, MINE)).toBe(false)
    expect(involvesDids({ nonsense: true }, MINE)).toBe(false)
    expect(involvesDids(esEnvelope('TokensTransferred'), null)).toBe(false)
  })
})

describe('§BRIDGE R8 — actorDid is a DID, or it is nothing', () => {
  it('refuses a UUID agent_id: a field named actorDid must not hold a non-DID', () => {
    const d = toVerb({ type: 'event', event: {
      id: 'e-uuid', event_type: 'ExchangeTradeExecuted',
      data: { agent_id: '8a3d57d7-752e-4073-aea7-591437039263', amount: '46.00' },
    } }, { frame: 'C', frameCurrency: 'BVT', mineDids: new Set(), localRegistry: null, now: Date.now() })
    expect(d).not.toBeNull()
    expect(d!.actorDid).toBeNull()
  })

  it('keeps a real DID', () => {
    const d = toVerb({ type: 'event', event: {
      id: 'e-did', event_type: 'ExchangeTradeExecuted',
      data: { agent_did: 'did:theprotocol:abc-123', amount: '46.00' },
    } }, { frame: 'C', frameCurrency: 'BVT', mineDids: new Set(), localRegistry: null, now: Date.now() })
    expect(d!.actorDid).toBe('did:theprotocol:abc-123')
  })

  it('still MATCHES on a uuid actor for "mine", where a non-DID is merely inert', () => {
    const env = { type: 'event', event: {
      id: 'e-mine', event_type: 'ExchangeTradeExecuted',
      data: { agent_id: '8a3d57d7-752e-4073-aea7-591437039263', amount: '1' },
    } }
    const mine = new Set(['8a3d57d7-752e-4073-aea7-591437039263'])
    const d = toVerb(env, { frame: 'C', frameCurrency: 'BVT', mineDids: mine, localRegistry: null, now: Date.now() })
    expect(d!.mine).toBe(true)
  })
})

// ─── §DIVVERBS (2026-08-28) — dividends stop being invisible ────────────────
// Payloads are VERBATIM the emit shapes in services/exchange_service.py
// (ExchangeDividendDeclared :2971, ExchangeDividendPaid :3684): the value is
// under `total` (stringified), there are no party DIDs, and dividend_id links
// Declared to Paid. Mutation-verified: each assertion fails with the scoped
// `total` read, the dividend correlation branch, or the sentence branch removed.
describe('§DIVVERBS — dividend pair draws with magnitude, story and sentence', () => {
  const declared = {
    type: 'event',
    event: {
      event_type: 'ExchangeDividendDeclared', id: 'ev-div-1', aggregate_id: 'listing-uuid-1',
      data: { dividend_id: 41, symbol: 'HALD', epoch: '3', per_share: '0.32', total: '94.96', holders: '293' },
    },
  }
  const paid = {
    type: 'event',
    event: {
      event_type: 'ExchangeDividendPaid', id: 'ev-div-2', aggregate_id: 'listing-uuid-1',
      data: { dividend_id: 41, symbol: 'HALD', epoch: '3', total: '94.96' },
    },
  }

  it('reads the amount from `total` — scoped to the dividend pair only', () => {
    const d = toVerb(declared, CTX)
    expect(d?.verb).toBe('trade')
    expect(d?.amount).toBe(94.96)
    expect(d?.amountClass).toBeGreaterThan(0)
    // the scope: a NON-dividend event with a bare `total` must NOT gain an amount
    const other = toVerb({ event_type: 'ExchangeOrderPlaced', data: { total: '94.96' } }, CTX)
    expect(other?.amount).toBeNull()
  })

  it('Declared and Paid share one correlation story per dividend', () => {
    const a = toVerb(declared, CTX)
    const b = toVerb(paid, CTX)
    expect(a?.correlationKey).toBe('dividend:41')
    expect(b?.correlationKey).toBe('dividend:41')
  })

  it('the fleet log says what happened, not "somebody traded"', () => {
    const a = toVerb(declared, CTX)!
    const b = toVerb(paid, CTX)!
    expect(describeVerb(a)).toBe('a distribution of 94.96 BVT was declared on the AGORA market')
    expect(describeVerb(b)).toBe('a distribution of 94.96 BVT finished paying every holder')
    // hidden-amounts mode still reads as an amount
    expect(describeVerb(a, undefined, { hideAmounts: true })).toContain('••••')
  })

  it('receipt door carries the listing aggregate; currency falls to the frame', () => {
    const d = toVerb(declared, CTX)!
    expect(d.receiptRef.aggregateId).toBe('listing-uuid-1')
    expect(d.currency).toBe('BVT')
  })
})
