/**
 * services/api/feeCollectorAdmin.ts — Fee collector visibility + admin distribute.
 *
 * Phase 1 (2026-05-08) of the fee → funding waterfall plan. Frontend reads
 * fee_collector balance + recent inflows; admin (admin_treasury flag) can
 * manually move AVT out of the fee pool to a target agent.
 *
 * Backend:
 *   GET  /admin/fee-collector/info?period=...
 *   POST /admin/fee-collector/distribute
 *   POST /teg/treasury/mint     (existing, used by Mint AVT button)
 *
 * Auth: admin_treasury flag (or is_admin=True superadmin).
 */
import { apiClient } from './client'

export type FeePeriod = '24h' | '7d' | '30d' | 'all'

export interface FeeCollectorWindowTotals {
  inflow: string
  fee_count: number
  fee_truncated: boolean
}

export interface FeeSparklinePoint {
  t: string
  amount: string
  count: number
}

export interface FeeRecentRow {
  id: string | null
  timestamp: string | null
  payer_did: string
  fee_amount: string
  fee_type: string | null
  transfer_amount: string | null
  transaction_id: string | null
}

export interface FeeCollectorInfo {
  as_of: string
  period: FeePeriod
  fee_collector_did: string | null
  balance: string | null      // live AVT balance from TEG (string Decimal)
  teg_error: string | null    // populated when TEG unreachable
  totals_in_window: FeeCollectorWindowTotals
  sparkline: FeeSparklinePoint[]
  recent: FeeRecentRow[]
}

export interface FeeDistributeRequest {
  target_agent_did: string
  amount: string              // string for Decimal precision
  reason: string              // staking_reward / dispute_compensation / manual_payout / etc.
  reference_id?: string | null
}

export interface FeeDistributeResponse {
  transaction_id: string
  status: string
  amount: string
  reason: string
  reference_id?: string | null
  new_fee_collector_balance: string
  new_target_balance: string
  fee_collector_did: string
  target_agent_id: string
  timestamp: string
}

export interface MintRequest {
  target_agent_did: string
  amount: string
  reason: string
}

export interface MintResponse {
  transaction_id: string
  new_target_balance?: string
  [key: string]: any
}

// ── Phase 3 (2026-05-08) — funding policy types ──
export interface RewardFundingPolicy {
  policy: Record<string, string[]>          // reason → ordered source list
  default_waterfall: string[]                // canonical default ["fee_collector","treasury"]
  valid_sources: string[]                    // ["fee_collector","treasury"]
}

export interface RewardPolicyUpdate {
  policy: Record<string, string[]>           // FULL replacement; must include "default"
}

class FeeCollectorAdminService {
  private base = '/admin/fee-collector'

  async info(period: FeePeriod = '7d'): Promise<FeeCollectorInfo> {
    try {
      const resp = await apiClient.get(`${this.base}/info`, { params: { period } })
      return resp.data
    } catch (err) {
      console.error('Failed to load fee_collector info:', err)
      throw err
    }
  }

  async distribute(req: FeeDistributeRequest): Promise<FeeDistributeResponse> {
    try {
      const resp = await apiClient.post(`${this.base}/distribute`, req)
      return resp.data
    } catch (err) {
      console.error('Failed to distribute from fee_collector:', err)
      throw err
    }
  }

  /** Existing /teg/treasury/mint endpoint — gated by admin_treasury. */
  async mint(req: MintRequest): Promise<MintResponse> {
    try {
      const resp = await apiClient.post('/teg/treasury/mint', req)
      return resp.data
    } catch (err) {
      console.error('Failed to issue units:', err)
      throw err
    }
  }

  /** §FEPARITY-R3 — return funds FROM an agent TO the treasury (`/teg/treasury/receive`).
   *  The only rail for this: the treasury is a system account, so a plain
   *  `/teg/transfer` to the treasury DID 404s (PART 5 live API facts). Δ-neutral —
   *  both sides are in circulation, this moves rather than mints. Throws on error. */
  async receive(req: { source_agent_did: string; amount: string; reason: string; reference_id?: string }): Promise<Record<string, any>> {
    const resp = await apiClient.post('/teg/treasury/receive', req)
    return resp.data
  }

  // ── Phase 3 (2026-05-08) — funding policy ──
  async getPolicy(): Promise<RewardFundingPolicy> {
    try {
      const resp = await apiClient.get('/admin/reward-funding/policy')
      return resp.data
    } catch (err) {
      console.error('Failed to load reward funding policy:', err)
      throw err
    }
  }

  async updatePolicy(update: RewardPolicyUpdate): Promise<RewardFundingPolicy> {
    try {
      const resp = await apiClient.put('/admin/reward-funding/policy', update)
      return resp.data
    } catch (err) {
      console.error('Failed to update reward funding policy:', err)
      throw err
    }
  }
}

export const feeCollectorAdminService = new FeeCollectorAdminService()
