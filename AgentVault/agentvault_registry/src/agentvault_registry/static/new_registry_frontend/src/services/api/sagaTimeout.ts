/**
 * services/api/sagaTimeout.ts — Saga timeout checker (§pass27 Phase 3).
 *
 *   GET /admin/saga-timeout/status   — fleet snapshot (both frames aggregated)
 *   GET /admin/saga-timeout/events   — settlement + cross-frame refund stream
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface SagaRegistryRow {
  registry_id: string
  settlement_cycles_24h: number
  cross_frame_cycles_24h: number
  settlements_timed_out_24h: number
  cross_frame_refunded_24h: number
  errors_24h: number
  pending_now: number
}

export interface FramePairCell {
  source_frame: string
  target_frame: string
  refunded_24h: number
}

export interface PendingSettlement {
  settlement_id: string
  saga_state: string
  status: string
  dispute_id: number
  saga_timeout_at: string | null
  age_hours: number | null
  requested_amount: string | null
  defendant_did: string
  complainant_did: string
}

export interface SagaStatusResponse {
  summary: {
    settlements_timed_out_24h: number
    cross_frame_refunded_24h: number
    pending_now: number
    errors_24h: number
    settlement_cycles_24h: number
    cross_frame_cycles_24h: number
  }
  per_registry: SagaRegistryRow[]
  frame_pair_matrix: FramePairCell[]
  pending_settlements: PendingSettlement[]
  snapshot_iso: string
}

export type SagaAction = 'settlement' | 'cross_frame'

export interface SagaEvent {
  event_id: string | null
  timestamp: string | null
  event_type: string
  action: SagaAction | 'unknown'
  registry_id: string | null
  source_frame: string | null
  target_frame: string | null
  settlement_id: string | null
  transfer_id: string | null
  sender_did: string | null
  receiver_did: string | null
  amount: string | null
  reason: string | null
}

export interface SagaEventsResponse {
  events: SagaEvent[]
  total_returned: number
  filters_applied: {
    action: string | null
    source_frame: string | null
    target_frame: string | null
    limit: number
  }
}

export async function getSagaStatus(): Promise<SagaStatusResponse> {
  const r = await apiClient.get<SagaStatusResponse>('/admin/saga-timeout/status')
  return r.data
}

export async function getSagaEvents(opts: {
  action?: SagaAction
  source_frame?: string
  target_frame?: string
  limit?: number
} = {}): Promise<SagaEventsResponse> {
  const params = new URLSearchParams()
  if (opts.action) params.set('action', opts.action)
  if (opts.source_frame) params.set('source_frame', opts.source_frame)
  if (opts.target_frame) params.set('target_frame', opts.target_frame)
  if (opts.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  const url = '/admin/saga-timeout/events' + (q ? `?${q}` : '')
  const r = await apiClient.get<SagaEventsResponse>(url)
  return r.data
}
