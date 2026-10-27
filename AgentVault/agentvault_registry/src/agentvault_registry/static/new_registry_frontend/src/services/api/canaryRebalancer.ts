/**
 * services/api/canaryRebalancer.ts — Canary rebalancer observability (§pass27 Phase 2).
 *
 * Backend:
 *   GET /admin/canary-rebalancer/status   — Prom + DB + worker live cache
 *   GET /admin/canary-rebalancer/events   — EventStore feed for 2 audit event types
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export type RebalancerState = 'healthy' | 'cooldown' | 'under_floor' | 'errored' | 'unknown'

export interface RebalancerAgentRow {
  agent_did: string
  name: string
  home_kind: string
  registry_url: string
  frame: string
  current_balance: string | null
  balance_checked_iso: string | null
  last_funded_iso: string | null
  next_eligible_iso: string | null
  last_error: string | null
  state: RebalancerState
}

export interface RebalancerStatusResponse {
  summary: {
    cycles_24h: number
    funded_24h: number
    errors_24h: number
    avt_disbursed_24h: string
    agents_active: number
    agents_under_floor: number
  }
  by_home_kind: {
    funded: Record<string, number>
    errors: Record<string, number>
  }
  config: {
    enabled: boolean
    interval_sec: number
    floor_avt: string
    topup_avt: string
    min_interval_sec: number
    op_creds_count: number
  }
  per_agent: RebalancerAgentRow[]
  snapshot_iso: string
}

export type RebalancerAction = 'funded' | 'error'

export interface RebalancerEvent {
  event_id: string | null
  timestamp: string | null
  event_type: string
  action: RebalancerAction | 'unknown'
  agent_did: string | null
  home_kind: string | null
  registry_url: string | null
  amount: string | null
  pre_balance: string | null
  reason: string | null
  floor: string | null
}

export interface RebalancerEventsResponse {
  events: RebalancerEvent[]
  total_returned: number
  filters_applied: {
    agent_did: string | null
    action: string | null
    home_kind: string | null
    limit: number
  }
}

export async function getRebalancerStatus(): Promise<RebalancerStatusResponse> {
  const r = await apiClient.get<RebalancerStatusResponse>('/admin/canary-rebalancer/status')
  return r.data
}

export async function getRebalancerEvents(opts: {
  agent_did?: string
  action?: RebalancerAction
  home_kind?: string
  limit?: number
} = {}): Promise<RebalancerEventsResponse> {
  const params = new URLSearchParams()
  if (opts.agent_did) params.set('agent_did', opts.agent_did)
  if (opts.action) params.set('action', opts.action)
  if (opts.home_kind) params.set('home_kind', opts.home_kind)
  if (opts.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  const url = '/admin/canary-rebalancer/events' + (q ? `?${q}` : '')
  const r = await apiClient.get<RebalancerEventsResponse>(url)
  return r.data
}
