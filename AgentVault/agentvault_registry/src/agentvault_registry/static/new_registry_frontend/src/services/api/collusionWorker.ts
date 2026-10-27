/**
 * services/api/collusionWorker.ts — Collusion worker observability (§pass28 Phase 5).
 *
 *   GET /admin/collusion/status   — fleet + DB rollup
 *   GET /admin/collusion/rings    — paginated AuditorFlagLog rows
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface CollusionRegistryRow {
  registry_id: string
  cycles_24h: number
  decay_passes_24h: number
  rings_detected_24h: number
  errors_24h: number
}

export interface CollusionLocalCycle {
  last_cycle_iso: string | null
  last_duration_ms: number
  decay_pass_status: 'ok' | 'error' | 'never_run' | string
  decay_pass_error: string | null
  collusion_scan_status: 'ok' | 'error' | 'never_run' | string
  collusion_scan_error: string | null
  rings_detected_last_cycle: number
}

export interface CollusionStatusResponse {
  summary: {
    lifetime_rings: number
    rings_24h: number
    cycles_24h: number
    errors_24h: number
    registries_reporting: number
    interval_sec: number
    next_cycle_iso: string | null
  }
  by_severity: Record<string, number>
  errors_by_stage: Record<string, number>
  per_registry: CollusionRegistryRow[]
  top_flagged_dids: Array<{ agent_did: string; last_flagged_iso: string | null }>
  local_last_cycle: CollusionLocalCycle
  snapshot_iso: string
}

export interface CollusionRing {
  id: number
  flagged_agent_did: string
  severity: string
  created_at: string | null
  scc_size: number | null
  score: number | null
  members: string[]
  details: Record<string, unknown>
}

export interface CollusionRingsResponse {
  rings: CollusionRing[]
  total_returned: number
  filters_applied: {
    severity: string | null
    agent_did: string | null
    since: string | null
    limit: number
  }
}

export async function getCollusionStatus(): Promise<CollusionStatusResponse> {
  const r = await apiClient.get<CollusionStatusResponse>('/admin/collusion/status')
  return r.data
}

export async function getCollusionRings(opts: {
  severity?: 'LOW' | 'MEDIUM' | 'HIGH'
  agent_did?: string
  since?: '24h' | '7d' | '30d' | 'all'
  limit?: number
} = {}): Promise<CollusionRingsResponse> {
  const params = new URLSearchParams()
  if (opts.severity) params.set('severity', opts.severity)
  if (opts.agent_did) params.set('agent_did', opts.agent_did)
  if (opts.since) params.set('since', opts.since)
  if (opts.limit) params.set('limit', String(opts.limit))
  const q = params.toString()
  const url = '/admin/collusion/rings' + (q ? `?${q}` : '')
  const r = await apiClient.get<CollusionRingsResponse>(url)
  return r.data
}
