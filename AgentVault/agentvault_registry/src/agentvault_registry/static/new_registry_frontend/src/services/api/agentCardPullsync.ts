/**
 * services/api/agentCardPullsync.ts — Option C Phase 3 (§pass36).
 *
 *   GET /admin/agent-card-pullsync/status   — worker snapshot + 24h Prom rollup
 *   GET /admin/agent-card-pullsync/events   — recent AgentCardPulled audit feed
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface PullsyncLastPullEntry {
  url?: string
  status?: number | string
  etag?: string
  drift_fields?: string[]
  ts?: string
}

export interface PullsyncLastStats {
  candidates?: number
  fetched_200?: number
  fetched_304?: number
  fetched_4xx?: number
  fetched_5xx?: number
  fetched_timeout?: number
  skipped_internal?: number
  drift_agents?: number
  drift_field_counts?: Record<string, number>
  errors?: number
  last_pull_per_agent?: Record<string, PullsyncLastPullEntry>
}

export interface PullsyncSnapshot {
  worker_id: string
  registry_id: string
  is_leader_now: boolean
  last_cycle_iso: string | null
  last_duration_ms: number
  last_stats: PullsyncLastStats
  interval_sec: number
  enabled: boolean
}

export interface PullsyncSummary {
  cycles_24h: number
  pulls_200_24h: number
  pulls_304_24h: number
  pulls_4xx_24h: number
  pulls_5xx_24h: number
  pulls_timeout_24h: number
  pulls_skipped_24h: number
  drift_events_24h: number
}

export interface PullsyncDbBuckets {
  total_native_active: number
  never_pulled: number
  stale: number
  fresh: number
}

export interface PullsyncBanner {
  level: 'info' | 'warn'
  msg: string
}

export interface PullsyncStatusResponse {
  worker_snapshot: PullsyncSnapshot | null
  summary: PullsyncSummary
  db_buckets: PullsyncDbBuckets
  drift_24h_by_field: Record<string, number>
  cycles_24h_by_registry: Record<string, number>
  banner: PullsyncBanner | null
}

export async function getPullsyncStatus(): Promise<PullsyncStatusResponse> {
  const r = await apiClient.get('/admin/agent-card-pullsync/status')
  return r.data
}

export interface PullsyncEvent {
  event_id?: string
  event_type: string
  timestamp: string
  agent_did?: string
  registry_id?: string
  drift: boolean
  drifted_fields: string[]
  new_etag?: string
}

export interface PullsyncEventsResponse {
  events: PullsyncEvent[]
  total_returned: number
}

export async function getPullsyncEvents(opts: {
  agent_did?: string
  drifted_field?: string
  limit?: number
} = {}): Promise<PullsyncEventsResponse> {
  const r = await apiClient.get('/admin/agent-card-pullsync/events', {
    params: opts,
  })
  return r.data
}
