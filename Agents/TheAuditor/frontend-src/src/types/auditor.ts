export interface AuditResult {
  id: number
  timestamp: string
  tokens_issued: number
  total_circulating: number
  // Live-read (HTTP /supply-audit) — transient; reflects in-flight outbox lag.
  delta: number
  status: 'OK' | 'BREACH' | 'ERROR' | 'UNKNOWN'
  // Atomic (single-statement DB) invariant — the TRUTH. null when DB unavailable.
  atomic_delta?: number | null
  atomic_status?: 'OK' | 'BREACH' | null
  maintenance?: boolean
  // §LIVESTATS: the server's rule for this row (database.counts_ok / counts_breach). Absent from an older server.
  counts_ok?: boolean | null
  counts_breach?: boolean | null
  tokens_destroyed?: number | null
  response_ms: number
  frame: string
  extra_data?: {
    tokens_destroyed?: number | null
    tokens_fees_collected?: number | null
    net_supply?: number | null
    agent_count?: number | null
    atomic_available?: boolean
    live_delta?: number
    live_status?: string
    live_tokens_issued?: number
    live_total_circulating?: number
    // A2: real issuance/burn from typed supply events since the balance-integrity baseline
    // (tokens_issued/tokens_destroyed are transfer-leg-inflated ledger accumulators).
    true_minted?: number | null
    true_burned?: number | null
    true_supply_since?: string | null
    // I2: independent FX reserve solvency (null on non-reserve frames, e.g. Frame B).
    solvency?: Solvency | null
    // I3: per-user conservation (negative agent balances + escrow lock-anomaly fingerprint).
    per_user?: PerUser | null
    // V4: supply composition — where the circulating sits + what created the
    // issued↔circulating gap (transit_net by kind).
    composition?: Composition | null
    // V5: AGORA share registry — per-listing cap table (who holds the stocks),
    // read directly from the frame's registry DB. null if the frame has no reg_dsn.
    shares?: ShareRegistry | null
    // V6: native-supply per-currency — native_issued == native_circulating, the
    // coverage-gated recon gate + cross-TEG currency attribution. null if DB unavailable.
    native_supply?: NativeSupply | null
    live_error?: string
    // §MTLSHOPS (a) (2026-09-15): a live read the auditor did not make (the reason), and a public-only frame's reading
    live_skipped?: string
    public_only?: boolean
    public_read?: boolean
    public_source?: string
    public_breach_readings?: number
    not_measured?: Record<string, string>
    attested_by?: string
  }
  // §MTLSHOPS (a): consecutive public BREACH readings (a public-only frame), and the reading's source
  public_breach_streak?: number
  source?: string
  error?: string
}

// AGORA share registry (V5) — the stock analog of currency CIRCULATING SUPPLY.
// Read by the auditor directly from each frame's registry DB (org_share_positions
// + exchange_listings). Quantities are integer SHARE counts, not money.
export interface NativeSupplyCcy {
  currency: string
  native: boolean        // true → this is the frame's own currency
  transfers: number
  completed_volume: number
}
export interface NativeSupply {
  native_currency: string | null
  native_issued: number              // typed issuance SINCE baseline
  native_burned: number
  native_issued_complete: boolean | null  // true → native_issued == total issuance
  native_circulating: number         // = circulating − transit_net (native on the books)
  crossframe_residual: number        // in-transit cross-frame settlement (transit_net)
  recon_gap: number
  // §GLOBALSTD Phase 0-A (2026-08-22): rebased recon (§NATIVEBASE). Raw recon_gap restates the
  // documented write-down on every render; where a frozen per-frame baseline exists the honest
  // figure is recon_gap_rebased. Non-null only under recon_basis = writedown_rebaselined.
  recon_gap_rebased?: number | null
  writedown_baseline?: number | null
  writedown_baseline_set_at?: string | null
  recon_basis: string                // typed_mints_complete | federated_reconciled | writedown_rebaselined | pre_baseline_genesis | coverage_unknown
  native_supply_ok: boolean | null   // true=proven · false=breach · null=unverified (pre-baseline)
  crossteg_by_currency?: NativeSupplyCcy[]
  crossteg_scope?: string
}

export interface ShareHolder {
  did: string
  label: 'treasury' | 'public'
  qty: number
  locked: number
  pct: number // share of total_shares
}
export interface ShareListing {
  symbol: string
  display_name: string
  currency: string
  status: string
  total_shares: number
  ipo_float: number
  ipo_sold: number
  holders: number
  treasury_did: string
  treasury_qty: number
  public_held: number    // held by non-treasury DIDs (secondary market)
  float_unissued: number // total − held = unsold IPO float
  locked: number         // shares locked backing open SELL orders
  neg_holders: number    // positions with qty < 0 (I-Shares violation)
  over_locked: number    // positions with locked_qty > qty (I-Shares violation)
  ok: boolean            // I-Shares conservation holds for this listing
  violations: string[]   // human-readable conservation breaches (empty when ok)
  reconciled: boolean    // == ok (kept for the per-card badge)
  // Current price (listing's local currency) + 24h trend.
  price: number | null
  price_currency: string
  last_trade_at: string | null
  price_spark: number[]          // ≤24 hourly last-prices over 24h (oldest→newest)
  // §AGORAFLAT (2026-08-22) — 24h activity: pinned price must not masquerade as a dead market
  trades_24h?: number
  vol_24h_qty?: number
  vol_24h_notional?: number
  price_change_pct: number | null // % change across the spark window
  spark_window: string           // e.g. '24h'
  top_holders: ShareHolder[]
}
export interface ShareRegistry {
  listings: ShareListing[]
  listing_count: number
  // I-Shares aggregate invariant for the frame (independent of the I1 supply Δ).
  status: 'OK' | 'BREACH'
  breached_count: number
  breached: { symbol: string; violations: string[] }[]
  spark_at?: string | null
}

export interface PerUser {
  status: 'OK' | 'BREACH'
  negative_agents: number
  neg_liquid_agents: number
  neg_staked_agents: number
  worst_liquid: number
  worst_staked: number
  negative_total: number
  tolerance?: number
  escrow_negative_clamps_24h: number
  escrow_orphan_releases_24h: number
}

export interface Composition {
  issued: number
  destroyed: number
  transit_net: number
  circulating: number
  issued_minus_circulating: number
  transit_baseline?: number
  transit_baseline_at?: string | null
  transit_drift?: number
  transit_drift_status?: 'OK' | 'STRANDING' | 'RETURNING'
  currency?: string
  buckets: {
    treasury: number
    fee_collector: number
    fx_reserve: number
    fx_router: number
    escrow: number
    agents: number
    total_staked: number
  }
  holder_count: number
  top_holders: { did: string; label: string; liquid: number; staked: number; total: number }[]
  transit_by_kind?: { kind: string; events: number | null; net_to_balances: number }[] | null
  transit_by_kind_at?: string | null
  reconciled?: boolean
}

// Independent FX reserve solvency (I2) — read by the auditor directly from each
// frame's materialized_balances and checked against its OWN configured floor.
export interface Solvency {
  present: boolean
  currency: string
  reserve_did: string
  reserve_balance: number
  floor: number
  headroom: number
  headroom_x: number | null
  gauge_pct: number
  status: 'SOLVENT' | 'LOW' | 'BREACH'
  router_did?: string
  router_residue?: number
  router_threshold?: number
  router_status?: 'OK' | 'RESIDUE'
}

// Cross-frame FX triangle (TRACKED, never gated) — the auditor's INDEPENDENT
// reserve-implied view of cross-frame liquidity. Each frame's @fx_reserve is a
// vertex; each pair of reserves is an edge whose implied cross-rate is
// reserveₓ / reserveᵧ. With all three sovereign reserves present (AVT · JDAY · BVT)
// the three rates close the loop to 1.0000 by construction — mutually consistent /
// arbitrage-free. (Generalises the old single AVT↔BVT pool to the live 3-currency
// triangle; currency-agnostic — it reads whatever reserves the frames expose.)
export interface FxVertex {
  ccy: string
  frame: string
  reserve: number
}
export interface FxEdge {
  a: string            // currency a (e.g. 'AVT')
  b: string            // currency b (e.g. 'JDAY')
  spot_a_per_b: number // reserveA / reserveB
  spot_b_per_a: number // reserveB / reserveA
}
export interface FxTriangle {
  vertices: FxVertex[]        // 2–3 reserve frames, ordered AVT · JDAY · BVT
  edges: FxEdge[]             // every pair
  loop_product: number | null // ∏ of a-per-b around a 3-cycle (=1.0000 by construction); null if < 3 vertices
}

export interface AuditStats {
  total_audits: number
  // §LIVESTATS: the rows get_stats counts as OK, the integer the page adds live rows to. Absent from an older server.
  ok_audits?: number
  consecutive_ok: number
  last_breach: string | null
  avg_delta: number
  max_delta: number
  avg_atomic_delta?: number
  max_atomic_delta?: number
  uptime_pct: number | null
  oldest_audit: string | null
}

export interface Breach {
  id: number
  detected_at: string
  delta: number
  resolved_at: string | null
  frame: string
}

export interface FrameConfig {
  id: string
  name: string
  mode?: string
  currency?: string
  public_only?: boolean
  public_read?: boolean
}

export interface Maintenance {
  active: boolean
  title: string
  message: string
  patch_ref: string
  since: string | null
  updated_at: string | null
}
