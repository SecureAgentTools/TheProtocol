/**
 * services/api/forensics.ts — Ledger Forensics console data layer.
 *
 * Frontend wrapper for the /admin/forensics view (2026-06-19). Built strictly
 * on endpoints that ALREADY EXIST (no registry rebuild required):
 *   - GET/PUT /admin/event-emission-policies         (f037 policy table + editor)
 *   - GET     /exchange/admin/invariant              (AGORA I-X1..I-X5 — escrow + gateway solvency)
 *   - GET     /exchange/admin/overview               (orders/escrow/settlement snapshot)
 *   - GET     /admin/command/auditor-latest          (independent Auditor — per-user / shares / composition, ALL frames)
 *   - GET     /admin/fee-collector/info              (fee_collector balance + recent)
 *   - events search/byAggregate                      (reused from eventStoreAdmin)
 *
 * The full anchor→3-DB made-whole Trace verdict + the global Stuck-Funds
 * Inventory predicate battery need a dedicated backend forensics router
 * (read pools to registry + TEG + ES); those are tracked separately and are
 * blocked until registry rebuilds are unblocked. This module deliberately
 * does NOT invent endpoints that don't exist yet.
 *
 * Auth: admin developer JWT (commander). apiClient baseURL already carries
 * /api/v1, so paths arrive as /admin/… and /exchange/admin/….
 */
import { apiClient } from './client'
import type { EventStoreEvent, FrameId } from './eventStoreAdmin'
import { expandLive } from '@/services/ledgerNames'

// ───────────────────────── Emission policy (f037) ─────────────────────────

export interface EmissionPolicy {
  event_type: string
  emit_from_teg: boolean
  emit_from_registry: boolean
  skip_in_projection: boolean
  description?: string | null
  updated_at?: string | null
}

export interface EmissionPolicyUpdate {
  emit_from_teg: boolean
  emit_from_registry: boolean
  skip_in_projection: boolean
  description?: string | null
}

/**
 * The authoritative balance-moving set (must mirror event_emitter.py:63-67
 * registry + TEG). These rows must NEVER be skip_in_projection=true (the
 * backend PUT guards this) and must carry a deterministic idempotency_key.
 * Used to highlight + protect rows in the Policy tab.
 */
export const BALANCE_MOVING_EVENT_TYPES: ReadonlySet<string> = expandLive([
  'TokensIssued',
  'TokensTransferred',
  'TokensStaked',
  'TokensUnstaked',
  'BalanceCorrected',
  'DisputeSlash',
  'DisputeCompensationMinted',
  'TransactionFeeCollected',
  'RewardsAutoCompounded',
  'ProjectionSnapshot',
  // TEG-native L2 balance writer — force-allowed from TEG, drives the projection.
  'LedgerBalanceChanged',
])  // W4 phase 1: with the new names (UnitsTransferred ...)

// ───────────────────────── AGORA exchange invariants ──────────────────────

export interface ExchangeListingInvariant {
  symbol: string
  'I-X1_share_conservation': boolean
  positions_sum: number
  expected: number
  'I-X2_lock_honesty': boolean
  locked_sum: number
  open_sell_remaining: number
}

export interface InvariantPair {
  expected?: string
  actual?: string
  delta?: string
  ok: boolean
}

export interface ExchangeInvariant {
  ok: boolean
  checked_at?: string
  listings: ExchangeListingInvariant[]
  'I-X3_escrow': InvariantPair
  funding_orders_in_transition: number
  'I-X4_settlement_liveness': { stuck_over_slo: number; ok: boolean }
  'I-X5_gateway_solvency': { gateway_balance: string; pending_credits: string; ok: boolean }
}

export interface ExchangeOverview {
  venue_enabled: boolean
  passport_enabled: boolean
  global_halt: boolean
  currency: string
  listings_by_status: Record<string, number>
  orders_by_status: Record<string, number>
  trades_total: number
  trades_24h: number
  notional_24h: string
  settlement: { pending: number; oldest_lag_seconds: number }
  participants_by_source: Record<string, number>
  dividends_unpaid: number
  escrow_balance: string
}

// ───────────────────────── Independent Auditor (all frames) ────────────────

export interface AuditorPerUser {
  status?: string
  negative_liquid_agents?: number
  negative_staked_agents?: number
  neg_liquid?: number
  neg_staked?: number
  worst_liquid?: number
  worst_staked?: number
  negative_total?: number
  escrow_clamps_24h?: number
  orphan_releases_24h?: number
  [key: string]: any
}

export interface AuditorShareListing {
  symbol?: string
  ticker?: string
  name?: string
  neg_holders?: number
  over_locked?: number
  neg_locked?: number
  holders?: number
  violations?: any[]
  ok?: boolean
  [key: string]: any
}

export interface AuditorComposition {
  currency?: string
  buckets?: Record<string, number>
  transit_net?: number
  transit_baseline?: number
  transit_drift?: number
  transit_drift_status?: string
  reconciled?: boolean
  [key: string]: any
}

export interface AuditorSolvency {
  currency?: string
  reserve_balance?: number
  floor?: number
  headroom?: number
  gauge_pct?: number
  status?: string
  [key: string]: any
}

export interface AuditorFrame {
  id?: number
  frame?: string
  timestamp?: string
  status?: string
  delta?: number
  atomic_delta?: number | null
  atomic_status?: string | null
  maintenance?: boolean
  tokens_destroyed?: number | null
  extra_data?: {
    per_user?: AuditorPerUser | null
    composition?: AuditorComposition | null
    shares?: AuditorShareListing[] | Record<string, any> | null
    solvency?: AuditorSolvency | null
    net_supply?: number | null
    true_minted?: number | null
    true_burned?: number | null
    live_error?: string | null
    [key: string]: any
  }
  [key: string]: any
}

export type AuditorLatest = Record<string, AuditorFrame>

// ───────────────────────── Fee collector ──────────────────────────────────

export interface FeeCollectorRecent {
  id: string
  timestamp: string
  payer_did?: string | null
  fee_amount: string
  fee_type?: string | null
  transfer_amount?: string | null
  transaction_id?: string | null
}

export interface FeeCollectorInfo {
  as_of?: string
  period?: string
  fee_collector_did?: string
  balance?: string
  teg_error?: string | null
  totals_in_window?: { inflow?: string; fee_count?: number; fee_truncated?: boolean }
  sparkline?: Array<{ t: string; amount: string; count: number }>
  recent?: FeeCollectorRecent[]
}

// ───────────────────────── Gateway Float Keeper (AGORA passport float) ─────
// Surfaces the parallel-session keeper (background_tasks/gateway_float_keeper.py,
// 2026-06-19): MOVE-only treasury→gateway top-up + autonomous recon re-arm.
// Read-only status endpoint is additive — FE calls it defensively (null until rolled).

export interface KeeperStatusBucket { count: number; sum: number }
export interface GatewayKeeperStatus {
  enabled: boolean
  env_enabled?: boolean
  buffer?: number
  deadband_pct?: number
  max_move_per_cycle?: number
  source?: string
  check_interval_sec?: number
  operator_mode?: string
  updated_at?: string | null
  updated_by?: string | null
  gateway_did?: string
  currency?: string
  gateway_balance?: number
  outstanding_obligation?: number
  repat_dust?: number
  credits?: {
    by_status?: Record<string, KeeperStatusBucket>
    dust?: KeeperStatusBucket
    abandoned?: KeeperStatusBucket
    deliverable_pending?: KeeperStatusBucket
    /** §REPATLANE (V0603): payouts that may have moved; never sent again until a ledger read releases them */
    unresolved?: KeeperStatusBucket
    /** sends whose answer is being applied ('sending', 'batched') */
    in_flight?: KeeperStatusBucket
  }
  [key: string]: any
}

// ───────────────────────── Forensics backend (ES router + registry rails) ──

export interface ForensicSearchResult {
  events: EventStoreEvent[]
  count: number
  truncated?: boolean
  window?: { start: string; end: string }
  frame?: string
  error?: string
}
export interface ForensicScanFinding {
  key: string; severity: string; title: string; detail?: string; count: number; samples?: string[]
}
export interface ForensicScanResult {
  window?: { start: string; end: string }
  findings: ForensicScanFinding[]
  event_type_histogram?: Array<{ event_type: string; count: number }>
  frame?: string
  error?: string
}
export interface InventoryRail {
  rail: string; class: string; severity: string; heal?: string; holding?: string
  detail?: string; currency?: string | null; count: number | null; sum: number | null
  samples?: string[]; error?: string
}
export interface InventoryResult { rails: InventoryRail[]; total_flagged: number; note?: string }
export interface OpenFinding {
  finding_key: string; source: string; severity: string; title: string; detail?: string
  count?: number; amount?: number | null; currency?: string | null; frame?: string
  status: string; first_seen?: string; last_seen?: string; acked_at?: string | null; acked_by?: string | null
}

export interface ForensicSearchParams {
  start?: string; end?: string; event_type?: string; aggregate_id?: string
  transaction_id?: string; kind?: string; source_service?: string
  idempotency_prefix?: string; limit?: number; offset?: number; order?: 'asc' | 'desc'
  frame?: FrameId
}

// ───────────────────────── Service ────────────────────────────────────────

class ForensicsService {
  // ---- Emission policy (f037) ----
  async getPolicies(): Promise<EmissionPolicy[]> {
    const resp = await apiClient.get('/admin/event-emission-policies')
    return (resp.data?.policies ?? []) as EmissionPolicy[]
  }

  async updatePolicy(eventType: string, body: EmissionPolicyUpdate): Promise<EmissionPolicy> {
    const resp = await apiClient.put(
      `/admin/event-emission-policies/${encodeURIComponent(eventType)}`,
      body,
    )
    // Backend returns the updated row (shape may be {policy:{…}} or the row directly).
    return (resp.data?.policy ?? resp.data) as EmissionPolicy
  }

  // ---- AGORA exchange (this registry's frame) ----
  async exchangeInvariant(): Promise<ExchangeInvariant> {
    const resp = await apiClient.get('/agora/admin/invariant')
    return resp.data as ExchangeInvariant
  }

  async exchangeOverview(): Promise<ExchangeOverview> {
    const resp = await apiClient.get('/agora/admin/overview')
    return resp.data as ExchangeOverview
  }

  // ---- Independent Auditor (all frames) ----
  // Registry proxies the external auditor (no-CORS) at /admin/command/auditor-latest.
  // Raw shape: { ok, status_code, latency_ms, data: { <frame_id>: AuditorFrame } }.
  async auditorLatest(): Promise<AuditorLatest> {
    const resp = await apiClient.get('/admin/command/auditor-latest')
    const root = resp.data ?? {}
    return (root.data ?? root) as AuditorLatest
  }

  // ---- Fee collector ----
  async feeCollector(period: '24h' | '7d' | '30d' | 'all' = '7d'): Promise<FeeCollectorInfo> {
    const resp = await apiClient.get('/admin/fee-collector/info', { params: { period } })
    return resp.data as FeeCollectorInfo
  }

  // ---- Gateway Float Keeper status (additive endpoint; null if not yet rolled) ----
  async gatewayKeeper(): Promise<GatewayKeeperStatus | null> {
    try {
      const resp = await apiClient.get('/agora/admin/gateway-keeper')
      return resp.data as GatewayKeeperStatus
    } catch {
      return null // progressive enhancement — endpoint ships in a later registry roll
    }
  }

  // ---- Forensics backend (registry → ES /forensics proxy; null/empty if not rolled) ----
  async search(params: ForensicSearchParams): Promise<ForensicSearchResult> {
    const resp = await apiClient.get('/admin/forensics/search', { params })
    return resp.data as ForensicSearchResult
  }

  async traceTxid(transactionId: string, frame: FrameId = 'A'): Promise<ForensicSearchResult> {
    const resp = await apiClient.get(
      `/admin/forensics/trace/${encodeURIComponent(transactionId)}`,
      { params: { frame } },
    )
    return resp.data as ForensicSearchResult
  }

  async scan(frame: FrameId = 'A', start?: string, end?: string): Promise<ForensicScanResult | null> {
    try {
      const resp = await apiClient.get('/admin/forensics/scan', { params: { frame, start, end } })
      return resp.data as ForensicScanResult
    } catch {
      return null
    }
  }

  async inventory(): Promise<InventoryResult | null> {
    try {
      const resp = await apiClient.get('/admin/forensics/inventory')
      return resp.data as InventoryResult
    } catch {
      return null
    }
  }

  async findings(status?: 'open' | 'acked'): Promise<{ findings: OpenFinding[]; count: number; scanner_inactive?: boolean }> {
    try {
      const resp = await apiClient.get('/admin/forensics/findings', { params: status ? { status } : {} })
      return resp.data
    } catch (e: any) {
      // §FESUITE V0577: only a registry without the route (404) has no scanner to ask. Every other failure (no answer, a
      // 5xx, a refusal) said "Scanner inactive … FORENSIC_SCANNER_ENABLED=false", a claim about this frame's configuration
      // the read never made; it throws now and the store says the read failed.
      if (e?.response?.status === 404) return { findings: [], count: 0, scanner_inactive: true }
      throw e
    }
  }

  async ackFinding(findingKey: string): Promise<boolean> {
    try {
      await apiClient.post(`/admin/forensics/findings/${encodeURIComponent(findingKey)}/ack`)
      return true
    } catch {
      return false
    }
  }
}

export const forensicsApi = new ForensicsService()
