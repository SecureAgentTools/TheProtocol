/**
 * services/api/canaryJudge.ts — Canary judge observability (§pass27 Phase 1).
 *
 * Backend lives alongside the legacy /admin/canary/* router; this wrapper hits
 * the new Tier-3 modal endpoints:
 *   GET /admin/canary-judge/status   — judge snapshot (Prom + DB)
 *   GET /admin/canary-judge/events   — recent canary_test_results
 *
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'

export interface CanaryJudgePathStat {
  path_id: number
  path_human: string
  backend: string
  is_active: boolean
  passes_24h: number
  failures_24h: number
  pass_rate_24h: number | null
  avg_latency_ms: number | null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
  max_latency_ms: number | null
  last_fired_iso: string | null
  health: boolean
}

export interface CanaryJudgeStatusResponse {
  summary: {
    cycles_24h: number
    passes_24h: number
    failures_24h: number
    pass_rate_24h: number | null
    errors_24h: number
    active_paths: number
    in_flight_count: number
  }
  by_failure_type: Record<string, number>
  per_path: CanaryJudgePathStat[]
  snapshot_iso: string
}

export type CanaryOutcome = 'passed' | 'failed' | 'fired'

export interface CanaryJudgeEvent {
  test_id: string
  path_id: number
  path_human: string
  backend: string
  fired_iso: string | null
  completed_iso: string | null
  outcome: CanaryOutcome | string
  http_status: number | null
  http_latency_ms: number | null
  total_latency_ms: number | null
  failure_type: string | null
  failure_detail: Record<string, unknown> | null
  transfer_id: string | null
  sender_did: string
  receiver_did: string
  amount: string | null
}

export interface CanaryJudgeEventsResponse {
  events: CanaryJudgeEvent[]
  total_returned: number
  filters_applied: {
    path: string | null
    backend: string | null
    outcome: string | null
    limit: number
  }
}

/** Fetch judge snapshot. Server-side 5s cache. */
export async function getCanaryJudgeStatus(): Promise<CanaryJudgeStatusResponse> {
  const r = await apiClient.get<CanaryJudgeStatusResponse>('/admin/canary-judge/status')
  return r.data
}

/** Fetch recent canary test results, server-filtered. Default limit 100. */
export async function getCanaryJudgeEvents(opts: {
  path?: string
  backend?: string
  outcome?: CanaryOutcome | string
  limit?: number
} = {}): Promise<CanaryJudgeEventsResponse> {
  const params = new URLSearchParams()
  if (opts.path) params.set('path', opts.path)
  if (opts.backend) params.set('backend', opts.backend)
  if (opts.outcome) params.set('outcome', opts.outcome)
  if (opts.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  const url = '/admin/canary-judge/events' + (q ? `?${q}` : '')
  const r = await apiClient.get<CanaryJudgeEventsResponse>(url)
  return r.data
}
