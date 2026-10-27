/**
 * services/bridge/grammar.ts — §BRIDGE #B1
 *
 * THE VISUAL GRAMMAR. A pure, total function from one raw EventStore envelope to
 * at most one VerbDescriptor. The stage renders descriptors and nothing else;
 * this file is the ONLY place the event-type -> verb mapping exists.
 *
 * Why pure: it is 100% unit-testable without WebGL, without a DOM and without a
 * socket. The canvas is untestable; the meaning is not. Keep the meaning here.
 *
 *   raw envelope ──> normalize ──> classify ──> extract ──> VerbDescriptor | null
 *
 * HONESTY RULES BAKED IN (strategy §2.5):
 *  - Unknown event types return null. They are NOT invented into motion.
 *  - `LedgerBalanceChanged` returns null ON PURPOSE. It is the accounting shadow
 *    of movements we already draw (8.1M rows on frame-c alone, one or more per
 *    transfer). Drawing it would double-count the same money on screen. The
 *    ledger console still COUNTS it; the stage refuses to draw it twice.
 *  - Trust events (ReputationChanged, AttestationSubmitted, EigenTrustSignal,
 *    the IRONKEY capability/delegation family) return null: trust is rendered as
 *    a star's own collar and brightness, never as traffic. Motion means value or
 *    work moved.
 *  - ALARM is breach-class only. Routine failure (a refund, a halt, a swept 2PC
 *    row) is never red.
 *
 * Mapping table grounded on the LIVE union of event types across Frame A (144)
 * and Frame C (140) EventStores measured 2026-08-18 = 194 distinct types.
 * See `scratchpad/.bridge_ev_union.txt`.
 */

// ─── Verbs (strategy §2.1: 7 verbs + 2 garnishes) ────────────────────────────
export type Verb =
  | 'transfer'   // V1 value moves between two parties
  | 'fx'         // V2 value crosses a currency boundary and recolors in flight
  | 'trade'      // V3 AGORA venue activity
  | 'guild'      // V4 a work engagement thread (guild + contract spine)
  | 'birth'      // V5 a new star ignites
  | 'treasury'   // V6 issuance, staking, rewards, treasury movement
  | 'alarm'      // V7 breach class ONLY
  | 'canary'     // g1 the system watching the system
  | 'corridor'   // g2 federation / ops truth as scenery

/** Coarse magnitude bucket. Brightness ~ log(amount); 0 = unknown/no amount. */
export type AmountClass = 0 | 1 | 2 | 3 | 4

import { FRAMES } from '@/config/frames'
import { liveOld } from '@/services/ledgerNames'

export interface VerbDescriptor {
  /** Stable id so the renderer can pool + dedupe. */
  id: string
  verb: Verb
  /** Event type verbatim, for the receipt card and the ledger console. */
  eventType: string
  /** Frame key the stream that delivered this event belongs to (the manifest's key: 'eu', 'asia', ...). */
  frame: string
  /** Origin system (registry slug) when the payload names one, else null. */
  from: string | null
  /** Destination system (registry slug) when the payload names one, else null. */
  to: string | null
  /** Origin frame for a cross-frame move (drives the V2 midpoint recolor). */
  fromFrame: string | null
  toFrame: string | null
  fromDid: string | null
  toDid: string | null
  /** The party the event is about when it is not a two-sided move. DID or null —
   *  safe to open, route to, or ask `/agents/by-did` for. */
  actorDid: string | null
  /** The actor AS IT ARRIVED (may be a UUID or a system account). Matchable and
   *  displayable; never a door. §BRIDGE R9. */
  actorRef: string | null
  /** Settlement currency: payload truth first, else the delivering frame's. */
  currency: string | null
  /** Raw numeric amount when the payload carries one (never invented). */
  amount: number | null
  amountClass: AmountClass
  /** Groups events that belong to ONE story (strategy §2.4 composed sequences). */
  correlationKey: string | null
  /** True when the viewer owns one of the parties. Set by the caller's did set. */
  mine: boolean
  /** ISO timestamp from the payload, else delivery time. */
  ts: string
  /** Epoch ms of `ts`, precomputed for the renderer's hot path. */
  tsMs: number
  /** Door into Ledger Forensics (strategy §2.3 photons are receipts). */
  receiptRef: { eventId: string | null; aggregateId: string | null }
  /** True for the failure half of a verb (refund, revert, cancel) — drawn dimmer. */
  reverted: boolean
  /**
   * The envelope this descriptor was derived from, BY REFERENCE (§BRIDGE R11 #11).
   *
   * The Commander asked for the raw payload behind a row: *"left clicking it
   * should pop up the json payload to inspect"* and *"the payload itself. could
   * be refined."* Everything else on this object is a reading OF the payload —
   * without the payload itself, an inspector can only show you my interpretation
   * of the event, which is exactly the thing that needs checking.
   *
   * A reference, never a copy: the envelope object already exists on the heap,
   * so a 2,000-entry history ring costs 2,000 pointers, not 2,000 clones.
   */
  raw: unknown
}

export interface GrammarContext {
  /** Frame key of the stream that delivered the event. */
  frame: string
  /** Fallback currency when the payload does not name one. */
  frameCurrency?: string | null
  /** The viewer's own agent DIDs, lowercased. Drives `mine`. */
  mineDids?: Set<string> | null
  /** Registry slug this frame's local events originate from, when known. */
  localRegistry?: string | null
  /** Injected for determinism in tests. Defaults to Date.now(). */
  now?: number
}

// ─── The table ───────────────────────────────────────────────────────────────
// One entry per event type we choose to draw. Everything absent draws nothing.
// `reverted: true` marks the failure half of a pair (refund / reversal / abort).

interface Rule { verb: Verb; reverted?: boolean }

const R = (verb: Verb, reverted = false): Rule => ({ verb, reverted })

export const VERB_TABLE: Readonly<Record<string, Rule>> = Object.freeze({
  // ── V1 TRANSFER ───────────────────────────────────────────────────────────
  TokensTransferred:                R('transfer'),
  TransactionFeeCollected:          R('transfer'),
  CrossRegistryTransferCompleted:   R('transfer'),
  A2APaymentAuthorized:             R('transfer'),
  TokensBridgeLocked:               R('transfer'),

  // ── V2 FX (crosses a currency boundary; recolors at the corridor midpoint) ─
  FxSwapSettled:                    R('fx'),
  FxRouteSettled:                   R('fx'),
  FxSwapRefunded:                   R('fx', true),
  FxRouteRefunded:                  R('fx', true),
  CrossFrameTransferInitiated:      R('fx'),
  CrossFrameTransferSettled:        R('fx'),
  CrossFrameTransferRefunded:       R('fx', true),
  CrossFrameTransferReversed:       R('fx', true),

  // ── V3 TRADE (AGORA venues) ───────────────────────────────────────────────
  ExchangeOrderPlaced:              R('trade'),
  ExchangeTradeExecuted:            R('trade'),
  ExchangeOrderCancelled:           R('trade', true),
  ExchangeSharesIssued:             R('trade'),
  ExchangeSharesSplit:              R('trade'),
  ExchangeShareRefloated:           R('trade'),
  ExchangeDividendDeclared:         R('trade'),
  ExchangeDividendPaid:             R('trade'),
  ExchangeListingCreated:           R('trade'),
  ExchangeListingApproved:          R('trade'),
  ExchangeListingHalted:            R('trade', true),
  ExchangeProposalOpened:           R('trade'),
  ExchangeProposalTallied:          R('trade'),
  ExchangeVoteCast:                 R('trade'),
  ExchangeStopTriggered:            R('trade', true),
  ExchangeIpoPurchased:             R('trade'),

  // ── V4 GUILD (work engagements: guild board + the contract spine) ─────────
  GuildOrderPosted:                 R('guild'),
  GuildBidPlaced:                   R('guild'),
  GuildOrderAwarded:                R('guild'),
  GuildWorkSubmitted:               R('guild'),
  GuildOrderSettled:                R('guild'),
  GuildOrderResolved:               R('guild'),
  GuildOrderDisputed:               R('guild', true),
  GuildOrderCancelled:              R('guild', true),
  GuildCredentialReceived:          R('guild'),
  ContractCreated:                  R('guild'),
  ContractOffered:                  R('guild'),
  ContractAgreed:                   R('guild'),
  ContractAccepted:                 R('guild'),
  ContractWorkSubmitted:            R('guild'),
  ContractMilestoneSubmitted:       R('guild'),
  ContractMilestoneReleased:        R('guild'),
  ContractCompleted:                R('guild'),
  ContractResolved:                 R('guild'),
  ContractMirrored:                 R('guild'),
  ContractTemplatePublished:        R('guild'),
  ContractTemplatePurchased:        R('guild'),
  ContractDisputed:                 R('guild', true),
  ContractCancelled:                R('guild', true),
  ContractExpired:                  R('guild', true),
  ContractFailed:                   R('guild', true),
  DisputeFiled:                     R('guild', true),
  DisputeResolved:                  R('guild'),
  EvidenceSubmitted:                R('guild'),

  // ── V5 BIRTH (a new star ignites) ─────────────────────────────────────────
  AgentCreated:                     R('birth'),
  AgentOnboarded:                   R('birth'),
  AgentSpawned:                     R('birth'),
  AgentImported:                    R('birth'),
  AgentReinstated:                  R('birth'),
  OrganizationCreated:              R('birth'),

  // ── V6 TREASURY (issuance, staking, rewards, treasury rails) ──────────────
  TokensIssued:                     R('treasury'),
  TokensStaked:                     R('treasury'),
  TokensUnstaked:                   R('treasury'),
  RewardsDistributed:               R('treasury'),
  RewardsAutoCompounded:            R('treasury'),
  DailyDistributionCompleted:       R('treasury'),
  TreasurySlashReceived:            R('treasury'),
  DisputeCompensationMinted:        R('treasury'),
  DisputeCompensationApplied:       R('treasury'),
  DisputeCompensationRequest:       R('treasury'),
  FundingRequestApproved:           R('treasury'),
  FiatPurchaseSettled:              R('treasury'),
  CrossTEGTreasuryFunded:           R('treasury'),
  OrganizationTreasuryFunded:       R('treasury'),
  OrganizationTreasuryRemitted:     R('treasury'),
  OrganizationTreasurySwept:        R('treasury'),
  ReputationBondDeposited:          R('treasury'),
  BalanceCorrected:                 R('treasury'),

  // ── V7 ALARM (breach class ONLY — this is what makes red mean something) ──
  SupplyInvariantBreach:               R('alarm'),
  RegulatoryCountersignBroken:         R('alarm'),
  AgentCapabilityCircuitBreakerTripped: R('alarm'),
  TreasuryBankruptcyQuarantineTriggered: R('alarm'),
  CrossRegistryBlockedBySuspension:    R('alarm'),
  FederationLicenseSuspended:          R('alarm'),

  // ── g1 CANARY (the system watching the system) ────────────────────────────
  CanaryRebalancerErrored:          R('canary', true),
  CanaryRebalancerFunded:           R('canary'),
  CommandCenterProbe:               R('canary'),

  // ── g2 CORRIDOR (federation + ops truth as scenery, never red) ────────────
  PeerRegistryDeactivated:          R('corridor', true),
  PeerRegistryReactivated:          R('corridor'),
  PeerRegistryUrlAutoCorrected:     R('corridor'),
  PeerTopologyRefreshed:            R('corridor'),
  FederationStateDriftDetected:     R('corridor', true),
  ComplianceDryRunDrift:            R('corridor', true),
  CompliancePollCycleCompleted:     R('corridor'),
  FederationPolicyUpdated:          R('corridor'),
  FederationLicenseReinstated:      R('corridor'),
  FederationLicenseRevoked:         R('corridor', true),
  RegistryCardUpdated:              R('corridor'),
  ExchangeCircuitBreakerSet:        R('corridor', true),
  CrossTEGStaleSwept:               R('corridor', true),
  CrossTEGCoordinationAbortedByExpiry: R('corridor', true),
  CrossTEGCoordinationCommitResumed: R('corridor'),
  AgentCardPersistentDrift:         R('corridor', true),
  AgentCardJWSVerifyFailed:         R('corridor', true),
  AgentFlaggedForJWSFailures:       R('corridor', true),
  OperatorRenamed:                  R('corridor'),
  OperatorApplicationRevoked:       R('corridor', true),
  FrameInvitationRequested:         R('corridor'),
  FrameInvitationApproved:          R('corridor'),
  RegulatoryAuthorizationRecorded:  R('corridor'),
  RegulatoryAuthorizationRevoked:   R('corridor', true),
  EnforcementActionCreated:         R('corridor', true),
})

/**
 * Types we KNOW about and deliberately do not draw. Kept explicit (not just
 * "absent") so a reviewer can see the decision, and so the test suite can assert
 * that the highest-volume type on the network is silent BY DESIGN.
 */
export const SILENT_BY_DESIGN: ReadonlySet<string> = new Set([
  // The accounting shadow. One or more per movement we already draw.
  'LedgerBalanceChanged',
  // Trust is a star's collar, never traffic.
  'ReputationChanged', 'AttestationSubmitted', 'EigenTrustSignal', 'WitnessIssued',
  'AgentCapabilityIssued', 'AgentCapabilityRevoked', 'AgentCapabilityAttenuated',
  'AgentCapabilityConsumed', 'AgentActTokenMinted', 'AgentDelegationGranted',
  'AgentDelegationRevoked', 'AgentXRegDelegationIssued', 'AgentXRegDelegationReceived',
  // Identity plumbing.
  'AgentHeartbeat', 'AgentCardPulled', 'AgentSigningKeyRotated', 'AgentCredentialsRotated',
  'AgentCredentialReset', 'AgentMtlsEnrolled', 'AgentMtlsRevoked', 'AgentStatusChanged',
  'AgentSuspended', 'AgentHardDeleted', 'AgentExported', 'AgentOwnershipTransferred',
  // Analytics + telemetry snapshots.
  'ProjectionSnapshot', 'TestEvent', 'CommandCenterAction', 'AdminBulkRefreshCards',
  'HagridCemeteryCensus', 'HagridConcentration', 'HagridConservation', 'HagridFeudalism',
  'HagridGiniSnapshot', 'HagridInfancy', 'HagridLifecycle', 'HagridManifesto',
  'HagridPlutocracy', 'HagridSybilRing',
  // Account + org administration.
  'DeveloperSuspended', 'DeveloperReinstated', 'DeveloperDeleted', 'DeveloperForceEmailVerify',
  'DeveloperForcePasswordReset', 'DeveloperAdminFlagsChanged', 'AccountDeletionRequested',
  'OrganizationDeleted', 'OrganizationMemberInvited', 'OrganizationMemberJoined',
  'OrganizationMemberRemoved', 'OrganizationMemberRoleChanged',
  'OrganizationAgentAuthorityBulkApplied', 'OrganizationAgentAuthorityBulkRevoked',
  'OrganizationOwnershipTransferInitiated', 'OrganizationOwnershipTransferCancelled',
  'OrganizationOwnershipTransferDeclined', 'OrganizationOwnershipTransferExpired',
  'OrganizationOwnershipTransferred',
  // Build + delivery plumbing.
  'PipelineCreated', 'PipelineUpdated', 'PipelineDeleted', 'VersionCreated',
  'VersionActivated', 'VersionRolledBack', 'DeploymentTriggered', 'DeploymentStatusUpdated',
  'DeploymentWebhookExhausted', 'BundleCreated', 'WebhookRetryExhausted',
  // Comms + misc.
  'AdminBroadcastSent', 'AdminBroadcastRetracted', 'PhoneSessionStarted',
  'FiatPurchaseInitiated', 'FundingRequestCreated', 'ProposalCreated', 'ProposalAutoTallied',
  'VoteCast', 'ComplianceEnforcementModeChanged', 'DisputeCompensationDeferred',
  'RewardsAutoCompoundSkipped',
])

// ─── Extraction helpers (bounded, allocation-light, never throw) ─────────────

/** Bounded depth-first search for the first non-empty value at `key`. */
function deepFind(obj: any, key: string, depth = 0): any {
  if (!obj || typeof obj !== 'object' || depth > 4) return undefined
  const direct = obj[key]
  if (direct !== undefined && direct !== null && direct !== '') return direct
  for (const k in obj) {
    const v = obj[k]
    if (v && typeof v === 'object') {
      const found = deepFind(v, key, depth + 1)
      if (found !== undefined) return found
    }
  }
  return undefined
}

/** First hit across an ordered key list. Order encodes precedence. */
function pick(obj: any, keys: readonly string[]): any {
  for (const k of keys) {
    const v = deepFind(obj, k)
    if (v !== undefined) return v
  }
  return undefined
}

function asString(v: any): string | null {
  if (v === undefined || v === null) return null
  if (typeof v === 'string') return v.trim() || null
  if (typeof v === 'number' || typeof v === 'boolean') return String(v)
  return null
}

function asNumber(v: any): number | null {
  if (v === undefined || v === null || v === '') return null
  // Balances come back in scientific notation ("1E+3") — parseFloat handles it,
  // parseInt does not (§OPGUIDE-2). Never use int coercion here.
  const n = typeof v === 'number' ? v : parseFloat(String(v))
  return Number.isFinite(n) ? n : null
}

/*
 * THE KEY LISTS ARE MEASURED, NOT GUESSED.
 *
 * §BRIDGE P1 built these from the 194 event TYPE NAMES on the two EventStores
 * and never looked at a payload. 82 unit tests passed against envelopes I had
 * invented, and on the live network `mine` was false for essentially every
 * event, because the highest-volume transfer shapes carry their parties as a
 * bare `from` / `to` — a key that was in none of the lists.
 *
 * Re-derived 2026-08-19 from 60,000 real frame-c events plus 393 real
 * websocket envelopes (`scratchpad/.ws_envelopes.json`):
 *
 *   FxSwapSettled                   from, to  + source/dest_frame + source/dest_teg
 *   TokensTransferred               from, to
 *   TransactionFeeCollected         from, to, agent_did
 *   CrossRegistryTransferCompleted  from, to, source_teg, target_teg
 *   FxRouteSettled                  from, to, source_frame
 *   CrossFrameTransferSettled       sender_did, receiver_did, source/target_frame
 *   ExchangeTradeExecuted           buyer_did, seller_did
 *   LedgerBalanceChanged            entries[].agent_did   <- an ARRAY, see partyDids
 *
 * Bare `from` measured 18,904/18,904 DID-shaped; bare `to` is a DID or the
 * system account `teg:system:fee_collector` — both are real parties, so there
 * is no false-positive risk in treating them as such. Explicit `*_did` keys
 * stay FIRST: order encodes precedence.
 */
const FROM_REGISTRY_KEYS = ['from_registry', 'source_registry', 'sender_registry', 'origin_registry', 'origin_registry_name'] as const
const TO_REGISTRY_KEYS = ['to_registry', 'target_registry', 'destination_registry', 'receiver_registry', 'recipient_registry'] as const
const FROM_DID_KEYS = ['sender_did', 'from_did', 'from_agent_did', 'payer_did', 'buyer_did', 'poster_did', 'client_did', 'principal', 'parent_did', 'issuer_did', 'from'] as const
const TO_DID_KEYS = ['receiver_did', 'to_did', 'to_agent_did', 'recipient_did', 'payee_did', 'seller_did', 'worker_did', 'delegate_agent_did', 'child_did', 'holder_did', 'to'] as const
/** A DID, not merely an identifier. `did:method:…` — anything else is not one. */
import { didOrNull, isDidLike as _isDidLike } from './identity'
// §BRIDGE R9 — identity classification lives in ONE module now. Re-exported so
// existing importers keep working, but the rule itself is no longer duplicated.
export { isDidLike, classifyIdentity, didOrNull, firstOpenable, isUuidLike, isSystemAccount } from './identity'

/**
 * §BRIDGE R11 #11 — the keys the grammar actually READS.
 *
 * The payload inspector highlights these so the difference between "the event
 * carried this" and "the bridge understood this" is visible at a glance. It is
 * derived from the same constants the reader uses, so it cannot drift from the
 * reader the way a hand-kept list would.
 */
export function grammarReadKeys(): ReadonlySet<string> {
  // 'total' + 'dividend_id' — the §DIVVERBS scoped reads (dividend pair only).
  const out = new Set<string>(['event_type', 'type', 'id', 'event_id', 'timestamp', 'aggregate_id', 'entries',
                               'total', 'dividend_id'])
  for (const list of [FROM_REGISTRY_KEYS, TO_REGISTRY_KEYS, FROM_DID_KEYS, TO_DID_KEYS,
                      ACTOR_DID_KEYS, AMOUNT_KEYS, CURRENCY_KEYS, FROM_FRAME_KEYS, TO_FRAME_KEYS]) {
    for (const k of list) out.add(k)
  }
  return out
}

const ACTOR_DID_KEYS = ['agent_did', 'did', 'actor_did', 'subject_did', 'agent_id'] as const
const AMOUNT_KEYS = ['amount', 'total_amount', 'amount_avt', 'value', 'net_amount', 'gross_amount', 'quantity', 'fee_amount', 'bounty_amount', 'price'] as const
const CURRENCY_KEYS = ['currency', 'settlement_currency', 'currency_code', 'token_symbol'] as const
const FROM_FRAME_KEYS = ['from_frame', 'source_frame', 'origin_frame', 'source_teg'] as const
const TO_FRAME_KEYS = ['to_frame', 'target_frame', 'destination_frame', 'dest_frame', 'dest_teg', 'target_teg'] as const

/**
 * Frame hint -> frame key.
 *
 * MEASURED: the payload's frame fields do NOT carry 'A' / 'B' / 'C'. They carry
 * TRUST DOMAINS (`agentvault.com`, `frame-b.theprotocol.cloud`) and TEG ids
 * (`teg-layer-a`, `teg-layer-frame-b`). The renderer matches frame hints against
 * a registry's `frame` field, so an un-normalized domain matched nothing and the
 * V2 FX midpoint recolor had only one resolvable end.
 *
 * Trust domains, origins and keys come from FRAMES (the frame manifest, §FEFRAME W2) so there is ONE source for
 * them; legacy TEG ids follow a rule (`teg-layer-[frame-]<key>`) rather than a second table.
 */
export function normalizeFrameHint(v: string | null): string | null {
  if (!v) return null
  const raw = v.trim()
  if (!raw) return null
  const low = raw.toLowerCase()
  // Already a frame key ('A', 'b', 'frame-c').
  const bare = low.replace(/^frame[-_]?/, '')
  if (/^[a-z]$/.test(bare)) return bare.toUpperCase()
  for (const f of FRAMES) {
    if (f.key.toLowerCase() === low) return f.key
    if (f.trustDomain && f.trustDomain.toLowerCase() === low) return f.key
    if (f.origin && f.origin.toLowerCase() === low) return f.key
  }
  // TEG ids: teg-layer-a, teg-layer-frame-b, teg-frame-c.
  const teg = low.match(/^teg[-_](?:layer[-_])?(?:frame[-_])?([a-z])$/)
  if (teg) return teg[1].toUpperCase()
  // A domain we do not know: keep the raw value rather than invent a frame.
  return raw
}

/**
 * Every party identifier this event names, lowercased.
 *
 * MUST be a scan, not a `pick`. `LedgerBalanceChanged` — the single
 * highest-volume type on the network — carries its parties as `entries[]`, and
 * `deepFind` returns only the FIRST `agent_did` in that array. When the
 * viewer's agent was the second entry (the credit side of half of all
 * transfers) it was invisible to a first-match lookup.
 *
 * Bounded (arrays capped) because this runs once per delivered event.
 */
function partyDids(inner: any, payload: any): string[] {
  const out: string[] = []
  const push = (v: any) => {
    const s = asString(v)
    if (s) { const l = s.toLowerCase(); if (!out.includes(l)) out.push(l) }
  }
  for (const keys of [FROM_DID_KEYS, TO_DID_KEYS, ACTOR_DID_KEYS]) push(pick(payload, keys))
  const entries = payload?.entries
  if (Array.isArray(entries)) {
    for (let i = 0; i < entries.length && i < 16; i++) {
      const e = entries[i]
      if (e && typeof e === 'object') push(e.agent_did ?? e.did ?? e.account)
    }
  }
  const hops = payload?.hops
  if (Array.isArray(hops)) {
    for (let i = 0; i < hops.length && i < 8; i++) {
      const h = hops[i]
      if (h && typeof h === 'object') { push(h.from); push(h.to) }
    }
  }
  push(pick(inner, ['aggregate_id']))
  return out
}

/** Shared membership test. ONE predicate, asked by the stage AND the ledger. */
function anyMine(parties: string[], dids: ReadonlySet<string> | null | undefined): boolean {
  if (!dids || dids.size === 0) return false
  for (const p of parties) if (dids.has(p)) return true
  return false
}

/**
 * Amount -> class. Buckets are decades, so brightness reads as log(amount),
 * which is the only honest way to show 0.1 and 1,000,000 on one screen.
 *   0 = no amount known · 1 = <10 · 2 = <1k · 3 = <100k · 4 = >=100k
 */
export function classifyAmount(amount: number | null): AmountClass {
  if (amount === null || !Number.isFinite(amount)) return 0
  const a = Math.abs(amount)
  if (a === 0) return 0
  if (a < 10) return 1
  if (a < 1_000) return 2
  if (a < 100_000) return 3
  return 4
}

/**
 * Correlation key -> the thread that ties a story together (strategy §2.4).
 * Precedence matters: a guild order id beats an fx route id beats a raw
 * idempotency key, because that is the order in which a human tells the story.
 */
export function correlationKeyFor(payload: any, eventType: string): string | null {
  const guild = asString(pick(payload, ['order_id', 'guild_order_id', 'work_order_id']))
  if (guild && (eventType.startsWith('Guild') || eventType.startsWith('Contract'))) return `guild-${guild}`
  const route = asString(pick(payload, ['route_id', 'fx_route_id']))
  if (route) return `fxroute:${route}`
  const contract = asString(pick(payload, ['contract_ref', 'contract_id']))
  if (contract) return `contract:${contract}`
  // §DIVVERBS — Declared and Paid are ONE story per dividend.
  const dividend = asString(pick(payload, ['dividend_id']))
  if (dividend) return `dividend:${dividend}`
  const swap = asString(pick(payload, ['swap_id']))
  if (swap) return `fxswap:${swap}`
  const idem = asString(pick(payload, ['idempotency_key']))
  if (idem) return `idem:${idem}`
  const tx = asString(pick(payload, ['transaction_id', 'tx_id']))
  if (tx) return `tx:${tx}`
  return null
}

/**
 * Unwrap an EventStore / registry websocket envelope down to the payload object
 * plus the fields that live on the envelope itself.
 *
 * Accepts every shape observed in production:
 *   {type:'event', event:{event_type, data:{...}}}     EventStore
 *   {type:'event', data:{event_type, ...}}             registry broadcast
 *   {event_type, ...}                                  already-unwrapped
 * and tolerates JSON-stringified `data` at one or two levels (the backend does
 * that under load).
 */
export function unwrapEnvelope(envelope: any): any | null {
  if (!envelope || typeof envelope !== 'object') return null
  // Order matters. An ALREADY-UNWRAPPED event carries `event_type` at the top
  // level AND usually a `data` payload — descending into `.data` there would
  // throw the event_type away and silently drop the event. Self first.
  let inner: any = envelope.event_type !== undefined
    ? envelope
    : (envelope.event ?? envelope.data ?? envelope)
  if (typeof inner === 'string') {
    try { inner = JSON.parse(inner) } catch { return null }
  }
  if (!inner || typeof inner !== 'object') return null
  if (typeof inner.data === 'string') {
    try { inner = { ...inner, data: JSON.parse(inner.data) } } catch { /* leave as-is */ }
  }
  if (inner.data && typeof inner.data.data === 'string') {
    try { inner = { ...inner, data: { ...inner.data, data: JSON.parse(inner.data.data) } } } catch { /* leave */ }
  }
  return inner
}

let _seq = 0
/** Monotonic id source. Exported for tests that need determinism. */
export function _resetSeq(): void { _seq = 0 }

/**
 * THE function. One raw websocket envelope in, at most one descriptor out.
 * Never throws: a malformed payload is a null, not an exception on the hot path.
 */
/**
 * §BRIDGE R14.2 — TAXONOMY OPTION C (his approval, 2026-08-20).
 *
 * `toVerb()` returns null for an unknown type AND for a type we know about and
 * deliberately do not draw. Same value, two completely different facts:
 *
 *   'drawn'    115 types with a verb — arcs, threads, blooms.
 *   'counted'   81 types we KNOW and deliberately do not draw as motion, led by
 *               `LedgerBalanceChanged`, the double-entry shadow of movements
 *               already on the stage. Drawing those as arcs would double-count
 *               money on screen, which is why they are silent and why they must
 *               STAY silent as motion.
 *   'unknown'   a type this build has never heard of. Never invented into
 *               motion, and never counted as weather either: pretending to
 *               represent something we cannot classify is the failure mode this
 *               whole grammar exists to avoid.
 *
 * Option C gives the middle category a visible EXISTENCE without giving it
 * motion: it becomes background density, so the stage stops implying the
 * network only does 115 things.
 */
export type EventClass = 'drawn' | 'counted' | 'unknown'

/**
 * Classify a RAW WEBSOCKET ENVELOPE, unwrapping it exactly as `toVerb` does.
 *
 * 🔴 THIS EXISTS BECAUSE THE OBVIOUS VERSION IS SILENTLY WRONG. A live envelope
 * on this network is `{ type: 'event', event: { event_type: ..., data: {...} } }`
 * — verified against the captured fixtures, not assumed. So `envelope.type` is
 * the literal string `'event'` and `envelope.event_type` is undefined. A caller
 * that reads either would classify EVERY event as unknown and produce a feature
 * that fires zero times, forever, with nothing in the logs. The stage's weather
 * layer was written that way for about ten minutes.
 *
 * One unwrap, shared with `toVerb`, so the weather sees exactly what the stage
 * sees and the two can never drift.
 */
export function classifyEnvelope(envelope: any): EventClass {
  let inner: any
  try { inner = unwrapEnvelope(envelope) } catch { return 'unknown' }
  if (!inner) return 'unknown'
  const eventType = asString(pick(inner, ['event_type'])) || asString(inner.type)
  return classifyEventType(eventType)
}

export function classifyEventType(eventType: string | null | undefined): EventClass {
  if (!eventType) return 'unknown'
  if ((VERB_TABLE as Record<string, Rule | undefined>)[liveOld(eventType)]) return 'drawn'
  if (SILENT_BY_DESIGN.has(eventType)) return 'counted'
  return 'unknown'
}

/** Census of the classification itself, so the ledger caption is derived, never typed. */
export function eventTypeCensus(): { drawn: number; counted: number } {
  return { drawn: Object.keys(VERB_TABLE).length, counted: SILENT_BY_DESIGN.size }
}

export function toVerb(envelope: any, ctx: GrammarContext): VerbDescriptor | null {
  let inner: any
  try {
    inner = unwrapEnvelope(envelope)
  } catch {
    return null
  }
  if (!inner) return null

  const eventType = asString(pick(inner, ['event_type'])) || asString(inner.type)
  if (!eventType) return null

  const rule = (VERB_TABLE as Record<string, Rule | undefined>)[liveOld(eventType)]  // W4: either name
  if (!rule) return null   // unknown AND silent-by-design both land here: draw nothing

  const payload = (inner.data && typeof inner.data === 'object') ? inner.data : inner

  let amount = asNumber(pick(payload, AMOUNT_KEYS))
  // §DIVVERBS (2026-08-28): the dividend pair carries its value under `total`
  // — a key too generic for the global AMOUNT_KEYS (a count named `total` on
  // some other event would become fake money on screen), so it is read ONLY
  // for these two types. Measured 2026-08-28: without this, a 94.96 BVT
  // dividend drew as a zero-magnitude anonymous blip and drowned under its
  // own ~1,050 LedgerBalanceChanged legs.
  if (amount === null && (liveOld(eventType) === 'ExchangeDividendDeclared' || liveOld(eventType) === 'ExchangeDividendPaid')) {
    amount = asNumber(pick(payload, ['total']))
  }
  const fromDid = asString(pick(payload, FROM_DID_KEYS))
  const toDid = asString(pick(payload, TO_DID_KEYS))
  // §BRIDGE R8 — `agent_id` is in ACTOR_DID_KEYS because it identifies the actor,
  // but on this network it is a UUID, not a DID. A field called `actorDid` that
  // sometimes holds a UUID is a promise the consumers believe: the fleet log
  // offered it as an "open this agent" door and the modal answered
  // "Agent card not found: 8a3d57d7-752e-4073-aea7-591437039263" (seen, not
  // theorised — screenshot 2026-08-19). It is still collected for party matching
  // by `partyDids`, where a non-matching value is merely inert; it just cannot be
  // handed onward as a DID.
  // §BRIDGE R9 — MEASURED BUG, fixed at the root. R8 wrote
  //     isDidLike(actorRaw) ? actorRaw : null || asString(aggregate_id)
  // and `?:` binds looser than `||`, so the false branch became
  // `null || aggregate_id` and handed the aggregate UUID onward AS A DID. That
  // is literally the value in his screenshot (342df814-…a5c4). No operators
  // now: one function, asked twice, and it can only ever return a DID.
  const actorRaw = asString(pick(payload, ACTOR_DID_KEYS))
  const actorDid = didOrNull(actorRaw) ?? didOrNull(asString(pick(inner, ['aggregate_id'])))
  // The raw actor is kept for DISPLAY and for "is this mine?" — a UUID is a fine
  // identity to match on and a terrible one to hand to a network call.
  const actorRef = actorRaw ?? asString(pick(inner, ['aggregate_id'])) ?? null

  // ONE predicate, shared with involvesDids() below. Before 2026-08-19 the
  // stage and the ledger each answered "is this mine?" their own way and were
  // free to disagree (the §FANOUTFIX mistake); and both missed every party that
  // lives in an entries[] array.
  const mine = anyMine(partyDids(inner, payload), ctx.mineDids)

  const tsRaw = asString(pick(inner, ['timestamp', 'occurred_at', 'created_at']))
  const nowMs = ctx.now ?? Date.now()
  let tsMs = tsRaw ? Date.parse(tsRaw) : NaN
  if (!Number.isFinite(tsMs)) tsMs = nowMs
  const ts = tsRaw && Number.isFinite(Date.parse(tsRaw)) ? tsRaw : new Date(nowMs).toISOString()

  const eventId = asString(pick(inner, ['id', 'event_id']))

  return {
    id: eventId ? `${ctx.frame}:${eventId}` : `${ctx.frame}:${eventType}:${tsMs}:${_seq++}`,
    actorRef,
    verb: rule.verb,
    eventType,
    frame: ctx.frame,
    from: asString(pick(payload, FROM_REGISTRY_KEYS)) ?? ctx.localRegistry ?? null,
    to: asString(pick(payload, TO_REGISTRY_KEYS)),
    fromFrame: normalizeFrameHint(asString(pick(payload, FROM_FRAME_KEYS))),
    toFrame: normalizeFrameHint(asString(pick(payload, TO_FRAME_KEYS))),
    fromDid,
    toDid,
    actorDid,
    currency: asString(pick(payload, CURRENCY_KEYS)) ?? ctx.frameCurrency ?? null,
    amount,
    amountClass: classifyAmount(amount),
    correlationKey: correlationKeyFor(payload, eventType),
    mine,
    ts,
    tsMs,
    receiptRef: { eventId, aggregateId: asString(pick(inner, ['aggregate_id'])) },
    reverted: !!rule.reverted,
    raw: envelope,
  }
}

// ─── Human rendering (the FLEET LOG speaks sentences, not JSON) ──────────────

const VERB_LABEL: Record<Verb, string> = {
  transfer: 'value moved',
  fx: 'crossed frames',
  trade: 'traded',
  guild: 'work',
  birth: 'came online',
  treasury: 'treasury',
  alarm: 'ALARM',
  canary: 'canary',
  corridor: 'federation',
}

/** Short, humane number. Exact value belongs on hover, never in the sentence. */
/**
 * Does this raw event involve any of `dids`?
 *
 * The LIVE LEDGER defaults to the viewer's own traffic, and it must be able to
 * answer that for event types the STAGE draws nothing for — so this cannot be
 * `toVerb(...)?.mine`, which returns null for every silent-by-design type. It
 * reads the party fields directly and works on any event type, drawn or not.
 *
 * Total and allocation-light: called once per delivered event on a hot path.
 */
/**
 * Every DID this envelope names, as one set.
 *
 * Exported so the activity tracker uses the SAME party scan as `mine` and
 * `involvesDids` rather than growing a third opinion about who an event is
 * about — the §FANOUTFIX mistake, and the one that missed every party living
 * in an `entries[]` array.
 */
export function partiesOfEnvelope(envelope: any): string[] {
  const inner = unwrapEnvelope(envelope)
  if (!inner) return []
  // 🔴 read `.data`, NOT `.payload`. Every captured envelope carries `data`
  // (__fixtures__/realEnvelopes.ts: 12 `data` keys, ZERO `payload`), so the old
  // expression fell through to `inner` and this scan silently found nothing —
  // taking activity mode and the whole light-bridge board with it. Its sibling
  // `involvesDids` had it right; this is now the SAME expression, which is the
  // point of exporting one party scan instead of keeping two opinions.
  const payload = (inner.data && typeof inner.data === 'object') ? inner.data : inner
  return [...partyDids(inner, payload)]
}

export function involvesDids(envelope: any, dids: ReadonlySet<string> | null | undefined): boolean {
  if (!dids || dids.size === 0) return false
  let inner: any
  try {
    inner = unwrapEnvelope(envelope)
  } catch {
    return false
  }
  if (!inner) return false
  const payload = (inner.data && typeof inner.data === 'object') ? inner.data : inner
  return anyMine(partyDids(inner, payload), dids)
}

export function humaneAmount(n: number | null): string | null {
  if (n === null || !Number.isFinite(n)) return null
  const a = Math.abs(n)
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  if (a >= 1) return n.toFixed(2)
  return n.toPrecision(2)
}

/**
 * Descriptor -> one plain sentence for the fleet log.
 * `nameFor` resolves a DID to a human name when the caller knows one.
 */
export function describeVerb(
  d: VerbDescriptor,
  nameFor?: (did: string | null) => string | null,
  /* §BRIDGE R16.3 — the fleet log is a stream of sentences that EMBED amounts
   * ("X paid Y 240 BVT"), so the privacy switch has to reach in here or it
   * covers the cards and leaves the running commentary in plain sight. One
   * flag, applied where the money phrase is BUILT, so every branch below and
   * every consumer of this sentence inherits it. */
  opts?: { hideAmounts?: boolean },
): string {
  const name = (did: string | null): string => {
    if (!did) return 'an agent'
    const n = nameFor?.(did)
    if (n) return n
    return did.length > 22 ? `${did.slice(0, 12)}...${did.slice(-4)}` : did
  }
  const amt = opts?.hideAmounts ? '\u2022\u2022\u2022\u2022' : humaneAmount(d.amount)
  // A hidden amount must still read as an amount, or "paid ••••" degrades into
  // "moved value" and the sentence quietly changes meaning.
  const money = amt ? `${amt} ${d.currency || ''}`.trim() : null

  switch (d.verb) {
    case 'transfer':
      if (money && d.toDid) return `${name(d.fromDid)} paid ${name(d.toDid)} ${money}`
      if (money) return `${name(d.fromDid || d.actorDid)} moved ${money}`
      return `${name(d.fromDid || d.actorDid)} moved value`
    case 'fx': {
      const lane = d.fromFrame && d.toFrame ? ` ${d.fromFrame} to ${d.toFrame}` : ''
      if (d.reverted) return `a cross-frame transfer${lane} was refunded`
      return money ? `${money} crossed frames${lane}` : `value crossed frames${lane}`
    }
    case 'trade':
      // §DIVVERBS: a distribution is not somebody trading; say what happened.
      if (liveOld(d.eventType) === 'ExchangeDividendDeclared')
        return money ? `a distribution of ${money} was declared on the AGORA market`
                     : `a distribution was declared on the AGORA market`
      if (liveOld(d.eventType) === 'ExchangeDividendPaid')
        return money ? `a distribution of ${money} finished paying every holder`
                     : `a distribution finished paying every holder`
      if (d.reverted) return `${name(d.actorDid)} pulled an order on the AGORA market`
      return money
        ? `${name(d.actorDid)} traded ${money} on the AGORA market`
        : `${name(d.actorDid)} traded on the AGORA market`
    case 'guild':
      if (d.eventType === 'GuildOrderSettled' || d.eventType === 'ContractMilestoneReleased')
        return money
          ? `${name(d.toDid || d.actorDid)} was paid ${money} for completed work`
          : `${name(d.toDid || d.actorDid)} was paid for completed work`
      if (d.reverted) return `a work engagement was disputed or cancelled`
      return `${name(d.actorDid || d.fromDid)} moved a work engagement forward`
    case 'birth':
      return `${name(d.actorDid)} came online`
    case 'treasury':
      return money ? `treasury moved ${money}` : `the treasury moved`
    case 'alarm':
      return `ALARM: ${d.eventType}`
    case 'canary':
      return d.reverted ? `a canary run reported an error` : `a canary run completed`
    case 'corridor':
      return `federation state changed (${d.eventType})`
    default:
      return VERB_LABEL[d.verb]
  }
}
