/**
 * services/api/canaryIronhand.ts — Canary IRONHAND mTLS observability (§pass30).
 *
 * Backend: /admin/canary-ironhand/{status,events,svids}
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'

export interface CanaryIronhandPathStat {
  path_id: string
  sender_did: string
  transport: string
  amount: string
  interval_sec: number
  is_active: boolean
  passes_24h: number
  failures_24h: number
  pass_rate_24h: number | null
  p50_latency_ms: number | null
  p95_latency_ms: number | null
}

export interface CanaryIronhandStatusResponse {
  snapshot_iso: string
  summary: {
    active_paths: number
    cycles_24h: number
    passes_24h: number
    failures_24h: number
    pass_rate_24h: number | null
    revocation_p95_propagation_ms: number | null
    interval_sec: number
  }
  per_path: CanaryIronhandPathStat[]
  by_failure_type: Record<string, number>
}

export interface CanaryIronhandEvent {
  test_id: string
  path_human: string
  transport: string
  fired_iso: string | null
  completed_iso: string | null
  backend: string
  sender_did: string
  receiver_did: string
  amount: string
  transfer_id: string | null
  http_status: number | null
  http_latency_ms: number | null
  outcome: string
  failure_type: string | null
  failure_detail: Record<string, unknown> | null
  // IRONHAND Theatre: cross-frame FX corridor (registry slugs) the orb travels +
  // the agent SVID that rides it. node_path is [] for intra/local paths.
  node_path?: string[]
  origin_agent_spiffe?: string
}

export interface CanaryIronhandEventsResponse {
  events: CanaryIronhandEvent[]
  limit: number
  offset: number
  count: number
}

export interface CanaryIronhandSvid {
  path_id: string
  sender_did: string
  spiffe_id: string | null
  mtls_enabled: boolean
  mtls_enrolled_at: string | null
  spire_entry_present: boolean
}

export interface CanaryIronhandSvidsResponse {
  svids: CanaryIronhandSvid[]
  count: number
}

export async function getCanaryIronhandStatus(): Promise<CanaryIronhandStatusResponse> {
  const r = await apiClient.get<CanaryIronhandStatusResponse>('/admin/canary-ironhand/status')
  return r.data
}

export async function getCanaryIronhandEvents(opts: {
  path?: string
  outcome?: string
  limit?: number
} = {}): Promise<CanaryIronhandEventsResponse> {
  const params = new URLSearchParams()
  if (opts.path) params.set('path', opts.path)
  if (opts.outcome) params.set('outcome', opts.outcome)
  if (opts.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  const url = '/admin/canary-ironhand/events' + (q ? `?${q}` : '')
  const r = await apiClient.get<CanaryIronhandEventsResponse>(url)
  return r.data
}

export async function getCanaryIronhandSvids(): Promise<CanaryIronhandSvidsResponse> {
  const r = await apiClient.get<CanaryIronhandSvidsResponse>('/admin/canary-ironhand/svids')
  return r.data
}
