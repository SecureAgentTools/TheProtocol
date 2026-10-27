/**
 * services/api/settlementsAdmin.ts — Cross-registry settlement admin wrapper.
 *
 * Build #12 (2026-05-07) — admin oversight for dispute compensation
 * settlements. Each row tracks a slash on the defendant's home registry
 * paired with a mint to the complainant's home registry, linked by
 * dispute_id and EventStore event references.
 *
 * Backend: routers/federation_disputes.py:list_settlements (already shipping).
 * Auth: admin_enforcement flag.
 */
import { apiClient } from './client'

export type SettlementStatus =
  | 'PENDING_SLASH'
  | 'SLASHING'
  | 'SLASHED'
  | 'SETTLED'
  | 'FAILED'
  | 'EXPIRED'
  | 'CANCELLED'
  | string

// Backend returns Decimal fields as strings (Pydantic Numeric serialization).
// We accept both string and number for resilience.
type Money = string | number | null

export interface SettlementRow {
  id: string
  dispute_id: number
  status: SettlementStatus
  complainant_did: string
  defendant_did: string
  requested_amount: Money
  slashed_amount: Money
  minted_amount: Money
  shortfall: Money
  is_partial: boolean
  ruling: string
  origin_registry_url: string
  defendant_registry_url: string
  callback_url?: string | null
  slash_tx_id?: string | null
  mint_tx_id?: string | null
  requested_at: string | null
  slashed_at: string | null
  settled_at: string | null
  error_message?: string | null
  saga_state?: string
  saga_timeout_at?: string | null
}

export interface SettlementStats {
  total: number
  pending: number
  settled: number
  slashed: number
  failed: number
  expired: number
  total_requested_avt: Money
  total_slashed_avt: Money
  total_minted_avt: Money
}

export interface SettlementsListResponse {
  count: number
  stats: SettlementStats
  settlements: SettlementRow[]
}

class SettlementsAdminService {
  // Note: prefix is /federation/disputes (with slash), NOT /federation-disputes.
  private base = '/federation/disputes/settlements'

  async list(statusFilter?: string): Promise<SettlementsListResponse> {
    try {
      const params: Record<string, any> = {}
      if (statusFilter && statusFilter !== 'all') params.status_filter = statusFilter
      const resp = await apiClient.get(this.base, { params })
      return resp.data
    } catch (err) {
      console.error('Failed to load settlements:', err)
      throw err
    }
  }

  async get(settlementId: string): Promise<{ settlement: SettlementRow }> {
    try {
      const resp = await apiClient.get(`${this.base}/${encodeURIComponent(settlementId)}`)
      return resp.data
    } catch (err) {
      console.error('Failed to fetch settlement:', err)
      throw err
    }
  }

  /**
   * Approve a PENDING_ADMIN_APPROVAL settlement (Build #17, 2026-05-08).
   * Triggers the slash + callback flow on the defendant registry. Optional
   * `reason` is persisted in event metadata. Backend gated by `admin_enforcement`.
   */
  async approve(settlementId: string, reason?: string): Promise<Record<string, unknown>> {
    const url = `${this.base}/${encodeURIComponent(settlementId)}/approve`
    const body = reason ? { reason } : {}
    const resp = await apiClient.post(url, body)
    return resp.data
  }

  /**
   * Reject a PENDING_ADMIN_APPROVAL settlement. No funds move. Reason is
   * persisted in event metadata. Backend gated by `admin_enforcement`.
   */
  async reject(settlementId: string, reason?: string): Promise<Record<string, unknown>> {
    const url = `${this.base}/${encodeURIComponent(settlementId)}/reject`
    const body = reason ? { reason } : {}
    const resp = await apiClient.post(url, body)
    return resp.data
  }
}

export const settlementsAdminService = new SettlementsAdminService()
