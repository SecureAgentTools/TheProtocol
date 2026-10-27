/**
 * services/api/supplyAuditor.ts — Supply auditor observability (§pass28 Phase 4).
 *
 *   GET /admin/supply-auditor/status   — per-registry cycles + breaches + live audit
 *   GET /admin/supply-auditor/events   — SupplyInvariantBreach event feed
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface SupplyRegistryRow {
  registry_id: string
  cycles_24h: number
  breaches_24h: number
  errors_24h: number
  last_delta: number | null
  net_supply: number | null
  total_circulating: number | null
  healthy: boolean
}

export interface SupplyAuditLive {
  status?: string             // "OK" | "BREACH"
  delta?: string | number
  net_supply?: string | number
  total_circulating?: string | number
  tokens_issued?: string | number
  tokens_destroyed?: string | number
  tokens_fees_collected?: string | number
  audited_at_iso?: string
}

export interface SupplyLocalCycle {
  status: string | null
  delta: string
  net_supply: string
  total_circulating: string
  tokens_issued: string
  tokens_destroyed: string
  tokens_fees: string
  last_audit_iso: string | null
  consecutive_failures: number
}

export interface SupplyStatusResponse {
  summary: {
    cycles_24h: number
    breaches_24h: number
    errors_24h: number
    registries_reporting: number
    live_status: string | null
    live_delta: string | number | null
    live_net_supply: string | number | null
    live_total_circulating: string | number | null
  }
  errors_by_reason: Record<string, number>
  per_registry: SupplyRegistryRow[]
  live_audit: SupplyAuditLive | null
  local_last_cycle: SupplyLocalCycle
  snapshot_iso: string
}

export interface SupplyBreachEvent {
  event_id: string | null
  timestamp: string | null
  delta: string | null
  net_supply: string | null
  total_circulating: string | null
  tokens_issued: string | null
  tokens_destroyed: string | null
  tokens_fees: string | null
  tolerance: string | null
  auto_lockdown: boolean | null
  audit_type: string | null
  detected_at: string | null
}

export interface SupplyEventsResponse {
  events: SupplyBreachEvent[]
  total_returned: number
  filters_applied: { limit: number }
}

export async function getSupplyAuditorStatus(): Promise<SupplyStatusResponse> {
  const r = await apiClient.get<SupplyStatusResponse>('/admin/supply-auditor/status')
  return r.data
}

export async function getSupplyAuditorEvents(limit = 50): Promise<SupplyEventsResponse> {
  const r = await apiClient.get<SupplyEventsResponse>(`/admin/supply-auditor/events?limit=${limit}`)
  return r.data
}
