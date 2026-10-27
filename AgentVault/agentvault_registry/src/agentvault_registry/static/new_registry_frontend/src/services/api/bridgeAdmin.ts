/**
 * services/api/bridgeAdmin.ts — Cross-Frame Bridge admin wrapper.
 *
 * Build #9 (2026-05-07) — admin oversight for two cross-frame transfer paths:
 *   1. Async cross-frame (cross_frame_transfers + ..._inbound) — high volume,
 *      canary + production. Status: locked → settled | refunded
 *   2. Sync SF-3 bridge (bridge_transactions) — legacy escrow + mint.
 *      Status: INITIATED → LOCKED → MINTED → COMPLETED | FAILED | EXPIRED
 *
 * Backend: routers/admin_health.py:get_bridge_aggregate
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'

export type BridgePeriod = '24h' | '7d' | '30d' | 'all'

export interface AsyncTransferRow {
  id: string
  sender_did: string
  receiver_did: string
  target_frame: string
  amount: string
  status: 'locked' | 'settled' | 'refunded' | string
  created_at: string | null
  timeout_at: string | null
  settled_at: string | null
  refunded_at: string | null
  latency_ms: number | null
}

export interface SyncTransferRow {
  id: string
  source_frame_id: string
  target_frame_id: string
  source_agent_did: string
  target_agent_did: string
  amount: string
  status: string
  direction: string
  lock_tx_id: string | null
  mint_tx_id: string | null
  unlock_tx_id: string | null
  burn_tx_id: string | null
  expires_at: string | null
  created_at: string | null
  completed_at: string | null
  error_message: string | null
  latency_ms: number | null
}

export interface AsyncStats {
  status_counts: Record<string, number>
  total: number
  settled: number
  refunded: number
  locked: number
  settle_rate_pct: number | null
  refund_rate_pct: number | null
  avg_settled_ms: number | null
  p50_settled_ms: number | null
  p95_settled_ms: number | null
  inflight_locked: number
  expiring_5min: number
}

export interface InboundStats {
  status_counts: Record<string, number>
  total: number
}

export interface SyncStats {
  status_counts: Record<string, number>
  total: number
}

export interface BridgeAggregate {
  period: BridgePeriod
  as_of: string
  async: AsyncStats
  inbound: InboundStats
  sync_sf3: SyncStats
  recent_async: AsyncTransferRow[]
  recent_sync: SyncTransferRow[]
}

class BridgeAdminService {
  private base = '/admin/bridge'

  async aggregate(period: BridgePeriod = '7d'): Promise<BridgeAggregate> {
    try {
      const resp = await apiClient.get(`${this.base}/aggregate`, { params: { period } })
      return resp.data
    } catch (err) {
      console.error('Failed to load bridge aggregate:', err)
      throw err
    }
  }
}

export const bridgeAdminService = new BridgeAdminService()
