/**
 * services/api/treasuryAdmin.ts — Admin Treasury & Fee Audit wrapper.
 *
 * Build #7 (2026-05-07) — frontend wrapper for the Treasury & Fee Audit Dashboard.
 * Backend: routers/admin_health.py:get_treasury_aggregate (added in Build #7).
 *
 * Auth: admin_treasury flag (gates ledger/financial admin surfaces).
 *
 * Frame-aware: Frame A returns full data including live treasury balance from TEG.
 * Frame B skips treasury balance (sovereign isolation; different TEG admin key not
 * present in registry-a env). Supply audit + mints + fees still come back via the
 * frame_b_network attachment.
 */
import { apiClient } from './client'

/** Build #7: time window for treasury aggregate. */
export type TreasuryPeriod = '24h' | '7d' | '30d' | 'all'

/** §FEDEVENTS: OPEN string ('local' sentinel | legacy letters) — a closed union
 *  caps the app at three frames (see config/frames.ts). */
export type FrameId = string

export interface SupplyAudit {
  tokens_issued?: number
  tokens_destroyed?: number
  tokens_fees_collected?: number
  net_supply?: number
  total_circulating?: number
  delta?: number
  status?: 'OK' | 'BREACH' | string
  agent_count?: number
}

export interface TreasuryInfo {
  balance: string | null
  treasury_did: string | null
  error: string | null
}

export interface TreasuryWindowTotals {
  minted: string
  fees_collected: string
  mint_count: number
  fee_count: number
  mint_truncated: boolean
  fee_truncated: boolean
}

export interface FeePayer {
  agent_did: string
  total_fees: string
  tx_count: number
}

export interface RecentMint {
  id: string | null
  timestamp: string
  amount: string
  reason: string | null
  agent_did: string | null
  transaction_id: string | null
}

export interface SparklinePoint {
  t: string       // ISO bucket-start
  minted: string  // sum of mints in bucket (Decimal as string)
  fees: string    // sum of fees in bucket (Decimal as string)
}

export interface TreasuryAggregate {
  frame: FrameId
  period: TreasuryPeriod
  as_of: string
  supply_audit: SupplyAudit
  treasury: TreasuryInfo
  totals_in_window: TreasuryWindowTotals
  mints_by_reason: Record<string, string>
  top_fee_payers: FeePayer[]
  recent_mints: RecentMint[]
  sparkline: SparklinePoint[]
}

class TreasuryAdminService {
  private base = '/admin/treasury'

  /**
   * GET /admin/treasury/aggregate?period=&frame=
   * Pre-aggregated treasury & fee metrics for AdminTreasury view.
   */
  async aggregate(period: TreasuryPeriod = '7d', frame: FrameId = 'A'): Promise<TreasuryAggregate> {
    try {
      const resp = await apiClient.get(`${this.base}/aggregate`, { params: { period, frame } })
      return resp.data
    } catch (err) {
      console.error('Failed to load treasury aggregate:', err)
      throw err
    }
  }
}

export const treasuryAdminService = new TreasuryAdminService()
