/**
 * AGORA exchange ADMIN client (§V0064 AdminExchange view, 2026-06-13).
 * All endpoints developer-JWT (admin_federation flag server-side); client.ts
 * exchange rule routes non-order/portfolio/ipo paths to developer auth.
 */
import { apiClient } from './client'

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
  escrow_balance: string | null
  fetched_at: string
}

export interface InvariantListing {
  symbol: string
  'I-X1_share_conservation': boolean
  positions_sum: number
  expected: number
  'I-X2_lock_honesty': boolean
  locked_sum: number
  open_sell_remaining: number
}

export interface InvariantReport {
  ok: boolean
  checked_at: string
  listings: InvariantListing[]
  'I-X3_escrow'?: { expected: string; actual?: string; delta?: string; ok?: boolean; error?: string }
  'I-X4_settlement_liveness'?: { stuck_over_slo: number; ok: boolean }
  funding_orders_in_transition?: number
}

export interface Participant {
  agent_did: string
  home_registry: string
  owner_dev_ref: string | null
  owner_dev_name: string | null
  owner_dev_contact: string | null
  verification_source: string
  compliance_status: string
  first_seen: string | null
  verified_at: string | null
}

/** A single ticker's demand bias: dir>0 up · <0 down · 0 flat; strength 0..1. */
export interface DemandTicker {
  dir: number
  strength: number
}
export interface DemandDirectorConfig {
  enabled: boolean
  tickers: Record<string, DemandTicker>
}

/** §V0132 Campaign Engine — a built-in scripted trading-scenario (timed demand-director run). */
export interface CampaignPreset {
  key: string
  name: string
  description: string
  phases: number
  duration_sec: number
}

/** Live campaign progress. active=false when none is running (only `active` is then present). */
export interface CampaignStatus {
  active: boolean
  name?: string
  elapsed_sec?: number
  total_sec?: number
  phase?: string
  phase_idx?: number
  phase_elapsed_sec?: number
  current_dir?: number | null
  current_strength?: number | null
}

class ExchangeAdminService {
  async overview(): Promise<ExchangeOverview> {
    const { data } = await apiClient.get('/agora/admin/overview')
    return data
  }

  async invariant(): Promise<InvariantReport> {
    const { data } = await apiClient.get('/agora/admin/invariant')
    return data
  }

  async participants(status?: string): Promise<{ participants: Participant[]; count: number }> {
    const { data } = await apiClient.get('/agora/admin/participants', { params: status ? { status } : {} })
    return data
  }

  async approve(ref: string): Promise<any> {
    const { data } = await apiClient.post(`/agora/admin/listings/${encodeURIComponent(ref)}/approve`)
    return data
  }

  async halt(ref: string, halted: boolean): Promise<any> {
    const { data } = await apiClient.post(`/agora/admin/listings/${encodeURIComponent(ref)}/halt`, { halted })
    return data
  }

  /** §#84 set a listing's volatility circuit-breaker threshold (bps; 0 disables). */
  async setCircuitBreaker(ref: string, cbPct: number): Promise<any> {
    const { data } = await apiClient.post(`/agora/admin/listings/${encodeURIComponent(ref)}/circuit-breaker`, { cb_pct: cbPct })
    return data
  }

  async delist(ref: string): Promise<any> {
    const { data } = await apiClient.post(`/agora/admin/listings/${encodeURIComponent(ref)}/delist`)
    return data
  }

  async globalHalt(halted: boolean): Promise<{ global_halt: boolean }> {
    const { data } = await apiClient.post('/agora/admin/global-halt', { halted })
    return data
  }

  /** Read the live Demand Director config (public — market-mode sim reads the same). */
  async getDemandDirector(): Promise<DemandDirectorConfig> {
    const { data } = await apiClient.get('/agora/demand-director')
    return data
  }

  /** Persist the Demand Director config; the market-mode sim picks it up and pushes prices. */
  async setDemandDirector(payload: DemandDirectorConfig): Promise<DemandDirectorConfig> {
    const { data } = await apiClient.put('/agora/admin/demand-director', payload)
    return data
  }

  // ── §V0132 Campaign Engine — scripted, timed demand-director scenarios ──────
  /** Built-in scenario library: bull_run / flash_crash / pump_and_dump / soft_peg (public). */
  async getCampaignPresets(): Promise<{ presets: CampaignPreset[] }> {
    const { data } = await apiClient.get('/agora/campaign/presets')
    return data
  }

  /** Live campaign progress — phase, elapsed, current dir/strength (public). */
  async getCampaignStatus(): Promise<CampaignStatus> {
    const { data } = await apiClient.get('/agora/campaign/status')
    return data
  }

  /** Begin a scripted demand-director campaign by preset key (admin). */
  async startCampaign(preset: string): Promise<{ status: string; started: boolean; name: string; phases: number }> {
    const { data } = await apiClient.post('/agora/admin/campaign/start', { preset })
    return data
  }

  /** Stop the active campaign; optionally restore the uniform soft-peg director (admin). */
  async stopCampaign(restoreSoftpeg = true): Promise<{ status: string; stopped: boolean; restored_softpeg: boolean }> {
    const { data } = await apiClient.post('/agora/admin/campaign/stop', { restore_softpeg: restoreSoftpeg })
    return data
  }
}

export const exchangeAdminService = new ExchangeAdminService()
