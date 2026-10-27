/**
 * services/api/crossTegSweeper.ts — Cross-TEG 2PC sweeper observability.
 *
 * §pass26 (2026-05-17) — frontend wrapper for the TEG-side 2PC coordination
 * sweeper that closes the stuck-2PC class. Backend:
 *   GET /admin/cross-teg-sweeper/status   — fleet snapshot (Prometheus-sourced)
 *   GET /admin/cross-teg-sweeper/events   — paginated audit feed (EventStore)
 *
 * Auth: admin_platform flag (matches admin_canary).
 *
 * Generic by design — the response shape is intentionally close to a future
 * worker_id-keyed schema so the same modal can later surface canary_judge /
 * canary_rebalancer / saga_timeout_checker. Today only cross_teg_sweeper is
 * mapped on the backend.
 */
import { apiClient } from './client'

export interface SweeperPerOp {
  teg_id: string
  op_slug: string
  cycles_24h: number
  aborted_24h: number
  resumed_24h: number
  errors_24h: number
  pending: number
  healthy: boolean
}

export interface SweeperStatusResponse {
  summary: {
    cycles_24h: number
    aborted_24h: number
    resumed_24h: number
    errors_24h: number
    pending_total: number
    teg_count: number
  }
  per_op: SweeperPerOp[]
  snapshot_iso: string
}

export type SweeperAction = 'aborted' | 'resumed' | 'error'

export interface SweeperEvent {
  event_id: string | null
  timestamp: string | null
  event_type: string
  action: SweeperAction | 'unknown'
  teg_id: string | null
  op_slug: string
  transfer_id: string | null
  source_agent_id: string | null
  target_agent_id: string | null
  amount: string | null
  currency: string | null
  prior_status: string | null
  error_message: string | null
  resolution: string | null
  expired_at: string | null
}

export interface SweeperEventsResponse {
  events: SweeperEvent[]
  total_returned: number
  filters_applied: {
    op: string | null
    action: string | null
    limit: number
  }
}

/** Fetch the fleet snapshot. Cached server-side for 5s. */
export async function getSweeperStatus(): Promise<SweeperStatusResponse> {
  const resp = await apiClient.get<SweeperStatusResponse>('/admin/cross-teg-sweeper/status')
  return resp.data
}

/** Fetch the audit feed. Filters: op_slug, action. Default limit 50. */
export async function getSweeperEvents(opts: {
  op?: string
  action?: SweeperAction
  limit?: number
} = {}): Promise<SweeperEventsResponse> {
  const params = new URLSearchParams()
  if (opts.op) params.set('op', opts.op)
  if (opts.action) params.set('action', opts.action)
  if (opts.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  const url = '/admin/cross-teg-sweeper/events' + (q ? `?${q}` : '')
  const resp = await apiClient.get<SweeperEventsResponse>(url)
  return resp.data
}
