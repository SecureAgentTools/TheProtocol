// services/api/fx.ts — Cross-Frame FX (the AVT⇄BVT swap booth) API wrapper.
//
// Powers the admin FX Desk (strategy §12/§14) + the end-user swap widget (§15).
// Types are grounded in the LIVE sandbox shapes (verified 2026-06-02):
//   - card `fees.fx`            → config (public, well-known)            [reachable]
//   - GET  /teg/fx/pool         → x/y/k/spot_P/mtm_avt (auth)           [reachable, registry route]
//   - POST /teg/fx/quote        → quote preview (agent JWT)             [reachable, registry route]
//   - GET  /admin/events/search → FxSwapSettled / FxSwapRefunded feed   [reachable, registry→ES proxy]
//   - GET  /projections/cross-frame-audit → I1/I2/I3 + reserves + status
//       ⚠ ES-ONLY (registry :8004 returns 404). NOT reachable from the FE via any
//       existing registry route → integrity panel is BACKLOG B8 (needs a registry
//       proxy route, a backend task) — DO NOT add networking here.
import { apiClient } from './client'

import { peerGet } from './peer'

export type CurrencyCode = string

/** The unsigned `fees.fx` block published on the registry card (public). */
export interface FxConfig {
  enabled: boolean
  currency: CurrencyCode
  rate_mode: 'fixed' | 'pool'
  fee_pct: number
  fee_split?: { pool_retained_pct: number; fee_collector_pct: number }
  size_cap?: Record<string, number>
  slippage_max?: number
  breaker_pct?: number
  reserve_floor?: Record<string, number>
  note?: string
}

/** GET /teg/fx/pool — constant-product pool state (auth). Fields permissive
 *  pending live verification of exact keys (P2-5 spec: x,y,k,spot_P,mtm_avt). */
export interface FxPool {
  x?: number
  y?: number
  k?: number
  spot_P?: number
  mtm_avt?: number
  /** D6-058 (V0642): each figure's unit. x is the PEER frame's reserve wherever this frame's unit is not AVT. */
  x_currency?: string
  y_currency?: string
  mtm_currency?: string
  [k: string]: unknown
}

export interface FxQuoteRequest {
  receiver_did: string
  amount: string | number
}

/** POST /teg/fx/quote response (mode-aware; pool mode adds slippage). */
export interface FxQuote {
  quote_id?: string
  source_currency?: CurrencyCode
  dest_currency?: CurrencyCode
  same_currency?: boolean
  amount_in?: number | string
  rate?: number
  rate_mode?: 'fixed' | 'pool' | string
  amount_out_gross?: number | string
  fee?: number | string
  amount_out?: number | string
  fee_pct?: number
  slippage?: number
  expires_at?: string
  [k: string]: unknown
}

/** GET /projections/cross-frame-audit (ES-only; see B8). Shape verified live. */
export interface FxInvariants {
  I1_per_frame_delta_zero?: { ok: boolean; delta: number }
  I2_reserve_solvency?: { ok: boolean; currency: CurrencyCode; reserve_balance: number; floor: number }
  I3_value_conservation?: { ok: boolean; swaps_checked: number; breaches: unknown[] }
  fx_consistent?: boolean
}
export interface CrossFrameAudit {
  local_supply?: { tokens_issued: string; net_supply: string; agent_count: number; bridge_locked: string; wrapped_foreign: string }
  foreign_frames?: Record<string, { events_replicated: number; last_replicated_at: string }>
  total_foreign_events?: number
  cross_frame_consistent?: boolean
  checks?: string[]
  fx_invariants?: FxInvariants
  status?: 'OK' | 'BREACH' | string
}

/** GET /teg/fx/rate — public, env-authoritative live spot. `available` reads
 *  `_fx_enabled()` (FX_ENABLED) directly on the backend, so it is the FAST,
 *  reliable "is FX on for this frame" signal — independent of the well-known
 *  card fetch (which can lag several seconds on a heavily-loaded mainframe and
 *  otherwise makes the desk flash "FX DISABLED" on load). */
export interface FxRate {
  available: boolean
  pair?: string
  rate_mode?: 'fixed' | 'pool' | string
  /** Legacy AVT/BVT keys — present ONLY when the live pair really is AVT/BVT (§BATCH9). */
  avt_per_bvt?: string | number
  bvt_per_avt?: string | number
  /** §BATCH9 honest keys, every pair: 1 peer unit priced in local units, and the inverse. */
  local_currency?: string
  peer_currency?: string
  local_per_peer?: string | number
  peer_per_local?: string | number
  as_of?: string
  reason?: string
  [k: string]: unknown
}

/** One unordered currency pair from /teg/fx/rates. `a_per_b` = 1 b priced in a
 *  (the AMM spot reserve[a]/reserve[b]); `b_per_a` is the inverse. */
export interface FxPair {
  a: string
  b: string
  a_per_b: string | number
  b_per_a: string | number
}

/** GET /teg/fx/rates — ALL live cross-currency pairs (the AVT/JDAY/BVT triangle).
 *  All-pairs sibling of /fx/rate; lets the UI render every edge, not just AVT/BVT. */
export interface FxRates {
  available: boolean
  rate_mode?: 'pool' | string
  currencies?: string[]
  pairs?: FxPair[]
  as_of?: string
  reason?: string
}

/** GET /teg/fx/route/status (admin) — op→op route config + the local @fx_router
 *  transit account (DID + liquid residue available to sweep) + reserve peers. */
/** §FEPARITY-R3 — FX router keeper: keeps @fx_router's working float topped up from
 *  treasury/fx_reserve, and auto-refunds parked routes. Amounts are STRINGS (Decimal). */
export interface FxRouterKeeperConfig {
  enabled: boolean
  target_float: string
  min_float: string
  max_float: string
  source: string                      // fx_reserve | treasury
  check_interval_sec: number
  max_move_per_cycle: string
  dead_letter_refund_enabled: boolean
  dead_letter_max_retries: number
  updated_at?: string | null
  updated_by?: string | null
}
export interface FxRouterKeeper {
  config: FxRouterKeeperConfig
  env_gate_enabled: boolean           // FX_ROUTER_KEEPER_ENABLED — env beats config
  active: boolean                     // env_gate && config.enabled
  frame?: string
  currency?: string
  router_did?: string | null
  router_liquid?: string | null
  dead_letters_pending?: number
}

/** FX reserve peg keeper: holds the local reserve at a ratio vs the anchor currency. */
export interface FxReserveKeeperConfig {
  enabled: boolean
  anchor_currency: string
  ratio_vs_anchor: string
  target_float: string
  min_float: string
  max_float: string
  deadband_pct: string
  source: string
  max_move_per_cycle: string
  check_interval_sec: number
  operator_mode: string
  updated_at?: string | null
  updated_by?: string | null
}
export interface FxReserveKeeper {
  config: FxReserveKeeperConfig
  env_gate_enabled: boolean
  active: boolean
  frame?: string
  currency?: string
  [k: string]: unknown
}

/** A route whose funds are parked at an @fx_router. `locally_refundable` is server-computed:
 *  post_conversion* rows park at the DESTINATION frame's router, so the local keeper skips
 *  them by design — recovery is re-delivery on that frame, not a retry here. */
export interface FxDeadLetterRow {
  id: string
  route_id: string
  origin_did: string
  amount: string
  currency: string
  parked_at_did: string
  phase: string
  status: string
  retries: number
  last_error?: string | null
  resolution_tx?: string | null
  created_at?: string | null
  resolved_at?: string | null
  locally_refundable: boolean
  /** §REPATLANE-2 (V0603): a paying leg whose outcome is not known (phase swap_unknown / egress_unknown): nothing
   *  refunds it on its own; the keeper finishes an egress under its own key, a swap holds for a ledger read. */
  held?: boolean
}

export interface FxRouteStatus {
  route_enabled: boolean
  local_currency: string
  router_did: string | null
  router_liquid: string | null
  peers: { currency?: string; registry_id?: string; router_did?: string; url?: string }[]
  parent_gateway?: { registry_id?: string; router_did?: string; teg_id?: string; url?: string } | null
}

/** Normalized op→op cross-frame FX ROUTE row (from FxRouteSettled / FxRouteRefunded).
 *  These are the recursive gateway-delegated routes (S→ingress→GS→FXcore→GD→egress→D),
 *  distinct from a single-hop FxSwap. `hops` is the per-leg trail. */
export interface FxRouteRow {
  routeId: string
  ts: string
  status: 'settled' | 'refunded' | 'dead_letter'
  from?: string
  to?: string
  sourceCurrency?: CurrencyCode
  destCurrency?: CurrencyCode
  amountIn?: number
  amountOut?: number
  gateway?: string
  hopCount?: number
  sourceFrame?: string
  raw: unknown
}

/** Normalized FX swap row for the live feed (from FxSwapSettled / FxSwapRefunded). */
export interface FxSwapRow {
  txId: string
  ts: string
  status: 'settled' | 'refunded'
  sourceCurrency?: CurrencyCode
  destCurrency?: CurrencyCode
  amountIn?: number
  rate?: number
  amountOut?: number
  fee?: number
  agentDid?: string
  refundReason?: string
  raw: unknown
}

function _num(v: unknown): number | undefined {
  if (v === null || v === undefined) return undefined
  const n = typeof v === 'string' ? parseFloat(v) : (v as number)
  return Number.isFinite(n) ? n : undefined
}

/** Defensively map an EventStore FX event → FxSwapRow (data keys vary). */
export function normalizeFxEvent(ev: any): FxSwapRow {
  const d = (ev?.data ?? ev ?? {}) as Record<string, any>
  const type = ev?.event_type ?? ev?.type ?? ''
  return {
    txId: d.transaction_id || d.swap_id || ev?.id || ev?.event_id || '',
    ts: ev?.timestamp || ev?.created_at || d.timestamp || '',
    status: /Refunded/i.test(String(type)) ? 'refunded' : 'settled',
    sourceCurrency: d.source_currency || d.from_currency,
    destCurrency: d.dest_currency || d.to_currency,
    amountIn: _num(d.amount_in ?? d.amount),
    rate: _num(d.rate),
    amountOut: _num(d.amount_out ?? d.net),
    fee: _num(d.fee),
    agentDid: d.agent_did || d.sender_did || d.from,
    refundReason: d.refund_reason || d.reason,
    raw: ev,
  }
}

/** Defensively map an EventStore FxRoute event → FxRouteRow (op→op route audit). */
export function normalizeFxRouteEvent(ev: any): FxRouteRow {
  const d = (ev?.data ?? ev ?? {}) as Record<string, any>
  const type = ev?.event_type ?? ev?.type ?? ''
  const hops = Array.isArray(d.hops) ? d.hops : []
  return {
    routeId: d.route_id || ev?.id || ev?.event_id || '',
    ts: ev?.timestamp || ev?.created_at || d.timestamp || '',
    // Honor the authoritative data.status (settled | refunded | dead_letter) — a
    // dead-letter (funds parked at GD, NOT returned) must NOT render as "refunded".
    status: (d.status as FxRouteRow['status']) || (/Refunded/i.test(String(type)) ? 'refunded' : 'settled'),
    from: d.from || d.origin_did,
    to: d.to || d.receiver_did,
    sourceCurrency: d.source_currency,
    destCurrency: d.dest_currency,
    amountIn: _num(d.amount_in),
    amountOut: _num(d.amount_out),
    gateway: d.gateway,
    hopCount: hops.length || undefined,
    sourceFrame: d.source_frame,
    raw: ev,
  }
}

/** A read the desk may show as "not here": the registry refused it (401/403) or has no such route (404). Anything else
 *  (no answer, a 5xx) is a failed read the panel must say (§FESUITE V0578). */
function absentOrRefused(e: any): boolean {
  const st = e?.response?.status
  return st === 401 || st === 403 || st === 404
}

class FxService {
  /** Live pool/curve (x,y,k,spot_P,mtm_avt) for the admin FX Desk.
   *  §2026-06-03: uses the admin-treasury-gated /teg/fx/pool/admin, which
   *  auto-resolves the cross-currency counterparty (no receiver_did) and returns
   *  the desk's keys. The agent-gated /teg/fx/pool needs an agent JWT + receiver_did
   *  — neither of which the admin desk has, which left spot/reserves blank ("—").
   *  Returns {available:false,...} gracefully when no corridor / not pool-mode. */
  async pool(): Promise<FxPool> {
    const r = await apiClient.get('/teg/fx/pool/admin')
    return r.data ?? {}
  }

  /** Preview a cross-currency quote (no funds move). Agent JWT. */
  async quote(req: FxQuoteRequest): Promise<FxQuote> {
    const r = await apiClient.post('/teg/fx/quote', req)
    return r.data ?? {}
  }

  /** Recent FX swaps (settled + refunded) via the admin EventStore proxy.
   *  `frame` = the SOURCE frame of the swap (FX events land on the source ES).
   *  When `peerToken` is supplied the frame is FOREIGN → relay through the
   *  same-origin Multi-Frame peer-proxy to that frame's OWN registry (which
   *  resolves its OWN ES correctly). When omitted the frame is LOCAL → the
   *  local registry's /admin/events/search. This mirrors AdminEvents and
   *  replaces the env-sprawl `?frame=` path that made foreign frames load
   *  inconsistently (one frame yes, another no) depending on EVENT_STORE_*_URL. */
  async swapEvents(frame: string = 'A', limit = 100, peerToken?: string | null): Promise<FxSwapRow[]> {
    const q = (event_type: string) => {
      const params = { event_type, frame, limit, sort_order: 'desc' }
      const p = peerToken
        ? peerGet<any>(frame, 'admin/events/search', peerToken, params)
        : apiClient.get('/admin/events/search', { params }).then(r => r.data)
      // §FESUITE (2026-10-04): a failed half answered [] and AdminFx said "No FX swaps recorded on frame X yet." with its
      // reads failed. Only a 404 is the server's own "none"; one failed half fails the feed (half a feed is not the feed).
      return p.then(d => (d?.events ?? []) as any[]).catch((e: any) => { if (e?.response?.status === 404) return []; throw e })
    }
    const [settled, refunded] = await Promise.all([q('FxSwapSettled'), q('FxSwapRefunded')])
    return [...settled, ...refunded]
      .map(normalizeFxEvent)
      .sort((a, b) => (b.ts || '').localeCompare(a.ts || ''))
  }

  /** Live cross-frame FX integrity (I1 Δ=0 / I2 reserve solvency / I3 per-swap
   *  value conservation + status) via the registry's read-only proxy to the
   *  EventStore cross-frame-audit (B8). Returns null when the frame ANSWERED that it has no such projection
   *  (available: false), refused the read (401/403) or has no such route (404). §FESUITE V0578: every other failure
   *  read as "not exposed on this frame (non-FX frame, or admin sign-in required)", a claim about the frame the read
   *  never made; it throws now, so the panel says its read failed. */
  async crossFrameAudit(): Promise<CrossFrameAudit | null> {
    try {
      const r = await apiClient.get('/admin/supply-auditor/cross-frame-audit')
      const d = (r.data ?? {}) as CrossFrameAudit & { available?: boolean }
      if (d.available === false) return null
      return d
    } catch (e: any) {
      if (absentOrRefused(e)) return null
      throw e
    }
  }

  /** Public, env-authoritative live rate. `available:true` ⇔ FX_ENABLED on this
   *  frame — the FAST enabled signal the desk uses so it never flashes "DISABLED"
   *  while the slower well-known card fetch is still resolving. No auth required. */
  // null means the read FAILED (a frame without FX answers { available: false }): AdminFx and ForexDesk read it so, to
  // tell "unread" from "off" (§FESUITE, 2026-10-04; pinned by fx.rate.contract.test.ts)
  async publicRate(): Promise<FxRate | null> {
    try {
      const r = await apiClient.get('/teg/fx/rate')
      return (r.data ?? null) as FxRate | null
    } catch {
      return null
    }
  }

  /** GET /teg/fx/rates — ALL live cross-currency pairs (the triangle). Use this to
   *  render every edge (AVT↔JDAY, JDAY↔BVT, AVT↔BVT), not just the single AVT/BVT pair. */
  async publicRates(): Promise<FxRates | null> {
    try {
      const r = await apiClient.get('/teg/fx/rates')
      return (r.data ?? null) as FxRates | null
    } catch {
      return null
    }
  }

  /** Recent op→op cross-frame FX ROUTES (FxRouteSettled / FxRouteRefunded) via the
   *  admin EventStore proxy — same source-frame ES model as swapEvents(). Surfaces
   *  the gateway-delegated egress routes (distinct from single-hop swaps). */
  async routeEvents(frame: string = 'A', limit = 50, peerToken?: string | null): Promise<FxRouteRow[]> {
    const q = (event_type: string) => {
      const params = { event_type, frame, limit, sort_order: 'desc' }
      const p = peerToken
        ? peerGet<any>(frame, 'admin/events/search', peerToken, params)
        : apiClient.get('/admin/events/search', { params }).then(r => r.data)
      // §FESUITE (2026-10-04): as swapEvents: only a 404 is "none", one failed half fails the feed
      return p.then(d => (d?.events ?? []) as any[]).catch((e: any) => { if (e?.response?.status === 404) return []; throw e })
    }
    const [settled, refunded] = await Promise.all([q('FxRouteSettled'), q('FxRouteRefunded')])
    return [...settled, ...refunded]
      .map(normalizeFxRouteEvent)
      .sort((a, b) => (b.ts || '').localeCompare(a.ts || ''))
  }

  /** Admin: live op→op FX route status (router DID + liquid residue + peers). null: refused (401/403) or no such
   *  route (404); any other failure throws (§FESUITE V0578: the desk's Route Operations, the router's residue and its
   *  sweep, vanished over a failed read). */
  async routeStatus(): Promise<FxRouteStatus | null> {
    try {
      const r = await apiClient.get('/teg/fx/route/status')
      return (r.data ?? null) as FxRouteStatus | null
    } catch (e: any) {
      if (absentOrRefused(e)) return null
      throw e
    }
  }

  /** Admin: sweep the local @fx_router residue 1:1 to a target (Δ-safe). Throws on
   *  error so the desk surfaces it (do NOT swallow — this moves funds). */
  async sweepRouter(toDid: string, amount: string, memo?: string): Promise<{ status: string; amount: string; credited?: string; from?: string; to?: string; tx?: string }> {
    const r = await apiClient.post('/teg/fx/route/sweep', { to_did: toDid, amount, memo })
    return r.data
  }

  // ── §FEPARITY-R3: the two FX keepers + the dead-letter queue ────────────────
  // Both keepers were backend-complete and live (router holding real float,
  // reserve pegging) with the word "keeper" absent from the FX Desk entirely.
  // GETs answer null only when refused (401/403) or absent (404) and throw otherwise (§FESUITE V0578: the Keepers
  // panel vanished over a failed read); PUTs throw so the desk surfaces a rejected config change instead of implying
  // it saved.

  async routerKeeper(): Promise<FxRouterKeeper | null> {
    try {
      return (await apiClient.get('/teg/fx/router-keeper')).data as FxRouterKeeper
    } catch (e: any) {
      if (absentOrRefused(e)) return null
      throw e
    }
  }
  async updateRouterKeeper(patch: Partial<FxRouterKeeperConfig>): Promise<FxRouterKeeper> {
    return (await apiClient.put('/teg/fx/router-keeper', patch)).data
  }
  async reserveKeeper(): Promise<FxReserveKeeper | null> {
    try {
      return (await apiClient.get('/teg/fx/reserve-keeper')).data as FxReserveKeeper
    } catch (e: any) {
      if (absentOrRefused(e)) return null
      throw e
    }
  }
  async updateReserveKeeper(patch: Partial<FxReserveKeeperConfig>): Promise<FxReserveKeeper> {
    return (await apiClient.put('/teg/fx/reserve-keeper', patch)).data
  }
  async deadLetters(status: string = 'pending', limit = 50): Promise<FxDeadLetterRow[]> {
    // §FESUITE (2026-10-04): this answered [] for every failure, and the page read [] as "No parked routes — nothing is
    // waiting on recovery." Only a 404 (a registry without the route) is the server's own "none"; any other failure
    // reaches the page, which says the read failed.
    try {
      const r = await apiClient.get('/teg/fx/dead-letters', { params: { status, limit } })
      return (r.data?.rows ?? []) as FxDeadLetterRow[]
    } catch (e: any) {
      if (e?.response?.status === 404) return []
      throw e
    }
  }
}

export const fxService = new FxService()

/** Parse the public card's `fees.fx` block (config) for the local frame.
 *  §2026-06-03 — made resilient: a SUCCESSFUL fetch is authoritative (returns the
 *  fx block, or null if the card genuinely has none), but a transient failure
 *  (network error / non-2xx / non-JSON SPA-fallback) is RETRIED a few times. The
 *  old single-shot version showed "FX off here" on Frame A whenever the one
 *  well-known fetch hit a transient 5xx under sandbox/canary load — even though
 *  the card has fx.enabled=true. `cache: no-store` avoids a poisoned cache entry. */
export async function fetchFxConfig(retries = 2): Promise<FxConfig | null> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    const ctrl = new AbortController()
    const timer = setTimeout(() => ctrl.abort(), 3000)   // never hang the desk on a slow well-known
    try {
      const resp = await fetch('/.well-known/registry-card.json', { credentials: 'same-origin', cache: 'no-store', signal: ctrl.signal })
      if (!resp.ok) throw new Error(`card ${resp.status}`)
      const card = await resp.json()       // throws on HTML/SPA-fallback → retried
      if (!card || typeof card !== 'object') throw new Error('card not an object')
      const fx = card?.fees?.fx
      // Successful, well-formed card → authoritative answer (no further retry).
      return fx && typeof fx === 'object' ? (fx as FxConfig) : null
    } catch {
      if (attempt === retries) return null
      await new Promise(r => setTimeout(r, 200 * (attempt + 1)))
    } finally {
      clearTimeout(timer)
    }
  }
  return null
}
