import { apiClient } from './client'

// 2026-05-31: real path/backend enums (the FE previously sent "modern"/"legacy"
// which never matched the backend and was silently ignored — see admin_simulation.py).
// 'market' = §V0064 AGORA venue order-flow (band-aware limit orders + passport
// relays A↔C). Backend SimMode already supports it (admin_simulation.py); the FE
// type just hadn't been widened, so it couldn't be selected.
// 'delegation' = §2026-07-19 IRONKEY conformance battery + audit self-check on the frame-c
// mainframe (the pathfinder frame where agent-RBAC/delegation enforce): issue→consume→attenuate,
// caveat/revoked-reuse DENYs, L3 grant→act-token→revoke, a periodic circuit-breaker trip, then a
// query that asserts every fired action left its durable security_audit_logs row.
export type SimMode = 'mixed' | 'local-only' | 'cross-only' | 'cross-frame-only' | 'fx' | 'market' | 'delegation'
export type SimBackendMode = 'mixed' | 'async' | '2pc' | 'intra'

export interface SimStatus {
  running: boolean
  instances: number
  container_ids: string[]
  uptime_seconds: number
  params: Record<string, any>
  timestamp?: string
}

export interface SimAgent {
  did: string
  name: string
  registry: string
  frame: string
  balance: number
  funded: boolean
}

export interface RegistryGroup {
  name: string
  frame: string
  agents: SimAgent[]
  total_balance: number
  funded_count: number
}

export type SimTargetMetric = 'p50' | 'p95' | 'avg'

export interface SimStartParams {
  mode: SimMode
  pairs: number
  cycle_interval: number
  cycles: number
  raw: boolean
  instances: number
  concurrency?: number
  backend_mode?: SimBackendMode
  rate_tps?: number | null
  metrics_jsonl?: string | null
  // ── Dynamic auto-regulation (AIMD) ──
  dynamic?: boolean
  target_settle_ms?: number
  target_metric?: SimTargetMetric
  min_concurrency?: number
  max_concurrency?: number
  // Settlement-backlog backpressure: hold new orders while any venue's pending_settlement
  // exceeds this (resume under 0.8x). Keeps the sim from outrunning settlement. 0 = off.
  max_backlog?: number
  // Market mode currency-balance anti-skew: 'currency' (default) gives each currency equal
  // flow (the single BVT venue C = both AVT venues A+B); 'venue' = legacy uniform-per-venue.
  venue_balance?: 'currency' | 'venue'
  // Fraction of market fires that are passport relays (foreign agent → frame-c BVT). 0–0.95.
  passport_share?: number
  // §2026-07-19 IRONKEY — desk model: a bounded pool of frame-c-mainframe parents each spawn ONE
  // execution-clerk sub-agent that places their market orders via X-Capability-Token; in market
  // mode also folds a full delegation lifecycle + audit-self-check tick every N cycles. Default off.
  spawn_subagents?: boolean
  // Optional cross-registry delegation leg (frame-c → doha) in the delegation battery. Default off.
  xreg_delegation?: boolean
  // §XREGMODE 2026-08-12 — "100% foreign-federated" overlay.
  // spawn_frames: MAINFRAME frames whose parents spawn execution-clerks ("C" default; "A,B,C" = all three).
  // xreg_only: force every clerk-routed market fire to a FOREIGN passport order (target venue != sender
  //   home) → 100% cross-registry order-flow. Implies mode=market + spawn_subagents (forced server-side).
  // clerk_anchored: spawn the clerk WALLETLESS (draws from the PARENT via §SPAWN-ANCHOR). Leave off under xreg_only.
  spawn_frames?: string
  xreg_only?: boolean
  clerk_anchored?: boolean
}

export interface FundParams {
  target_balance: number
  only_depleted: boolean
  depleted_threshold: number
}

// ── Telemetry / safety types (2026-05-31) ──────────────────────────────────
export interface SimHealthSnapshot {
  ts?: string
  load1m?: number | null
  total_gb?: number
  available_gb?: number
  swap_used_gb?: number
}

export interface SimDeadmanStatus {
  armed: boolean
  enabled_at_start: boolean
  thresholds: {
    load1m_max: number
    swap_used_gb_max: number
    mem_available_gb_min: number
    max_runtime_min: number
    consecutive_breach: number
    check_interval_sec: number
  }
  last_snapshot: SimHealthSnapshot
  breach_history: Array<{ ts: string; reason: string; details?: any; snap?: SimHealthSnapshot }>
  last_stop: { ts: string; reason: string; details?: any; snap?: SimHealthSnapshot } | null
  instance_cap: number
}

export interface SimLatency {
  p50: number
  p95: number
  p99: number
}

export interface SimInstanceMetric {
  instance: number
  cycle: number
  ok: number
  fail: number
  tps: number
  latency: Record<string, SimLatency>
}

export interface SimDynamicState {
  enabled: boolean
  concurrency?: number
  settle_ms?: number
  target_settle_ms?: number
}

export interface SimMetrics {
  running: boolean
  instances: number
  throughput_tps: number
  ok: number
  fail: number
  fail_pct: number
  paths: { local?: number; cross_reg?: number; cross_frame?: number }
  latency: Record<string, SimLatency>
  dynamic?: SimDynamicState
  per_instance: SimInstanceMetric[]
  ts: string
}

export const simulationApi = {
  async getStatus(): Promise<SimStatus> {
    const { data } = await apiClient.get('/admin/simulation/status')
    return data
  },

  async start(params: SimStartParams): Promise<any> {
    const { data } = await apiClient.post('/admin/simulation/start', params)
    return data
  },

  async stop(): Promise<any> {
    const { data } = await apiClient.post('/admin/simulation/stop')
    return data
  },

  // 2026-05-31: structured live telemetry (throughput / success / latency).
  async getMetrics(): Promise<SimMetrics> {
    const { data } = await apiClient.get('/admin/simulation/metrics')
    return data
  },

  // 2026-05-31: deadman safety state + last stop-reason (cross-worker).
  async getDeadmanStatus(): Promise<SimDeadmanStatus> {
    const { data } = await apiClient.get('/admin/simulation/deadman-status')
    return data
  },

  async getAgents(): Promise<{ registries: RegistryGroup[], total_agents: number, total_funded: number, total_balance: number }> {
    const { data } = await apiClient.get('/admin/simulation/agents')
    return data
  },

  async fundAgents(params: FundParams): Promise<any> {
    const { data } = await apiClient.post('/admin/simulation/fund', params)
    return data
  },

  async fundingPreview(params: FundParams): Promise<any> {
    const { data } = await apiClient.post('/admin/simulation/funding-preview', params)
    return data
  },

  async getFundStatus(): Promise<{ lines: { type: string, message: string }[], total: number }> {
    const { data } = await apiClient.get('/admin/simulation/fund-status')
    return data
  },

  async mintTokens(amount: string, reason: string = 'EigenTrust funding top-up'): Promise<any> {
    const { data } = await apiClient.post('/teg/treasury/mint', { amount, reason })
    return data
  },

  async getTopology(): Promise<any> {
    const { data } = await apiClient.get('/admin/simulation/topology')
    return data
  },

  async getSupplyAudit(): Promise<Record<string, any>> {
    const { data } = await apiClient.get('/admin/simulation/supply-audit')
    return data
  },

  async getLogs(tail: number = 40): Promise<{ lines: { instance: number, line: string }[], total: number, instances?: number[] }> {
    const { data } = await apiClient.get('/admin/simulation/logs', { params: { tail } })
    return data
  },
}
