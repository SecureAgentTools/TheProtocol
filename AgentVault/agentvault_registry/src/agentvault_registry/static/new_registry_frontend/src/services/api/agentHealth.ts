/**
 * services/api/agentHealth.ts — Agent health checker observability (§pass29 Phase 7).
 *
 *   GET /admin/agent-health/status       — fleet snapshot + DB rollup
 *   GET /admin/agent-health/transitions  — recent state transitions
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface AHRegistryRow {
  registry_id: string
  cycles_24h: number
  probes_24h: number
}

export interface AHTransition {
  agent_did: string
  from_state: string
  to_state: string
  url: string
  observed_iso: string
}

export interface AHFlapping {
  agent_did: string
  last_health: string
  last_active_iso: string | null
  url: string
}

export interface AHLocalCycle {
  last_cycle_iso: string | null
  last_duration_ms: number
  checked: number
  healthy: number
  unhealthy: number
  unreachable: number
  first_observations: number
  state_changes: number
  errors: number
  cycle_error: string | null
}

export interface AgentHealthStatusResponse {
  summary: {
    cycles_24h: number
    probes_24h: number
    state_changes_24h: number
    registries_reporting: number
    agents_active: number
    agents_unhealthy: number
    agents_unreachable: number
    agents_never_observed: number
    interval_sec: number
  }
  probes_by_outcome: Record<string, number>
  transitions_grid: Record<string, Record<string, number>>  // from → to → count
  per_registry: AHRegistryRow[]
  db_summary: Record<string, number>
  flapping_or_down: AHFlapping[]
  local_last_cycle: AHLocalCycle
  snapshot_iso: string
}

export interface AgentHealthTransitionsResponse {
  transitions: AHTransition[]
  total_returned: number
  filters_applied: { limit: number }
}

export async function getAgentHealthStatus(): Promise<AgentHealthStatusResponse> {
  const r = await apiClient.get<AgentHealthStatusResponse>('/admin/agent-health/status')
  return r.data
}

export async function getAgentHealthTransitions(limit = 100): Promise<AgentHealthTransitionsResponse> {
  const r = await apiClient.get<AgentHealthTransitionsResponse>(`/admin/agent-health/transitions?limit=${limit}`)
  return r.data
}
