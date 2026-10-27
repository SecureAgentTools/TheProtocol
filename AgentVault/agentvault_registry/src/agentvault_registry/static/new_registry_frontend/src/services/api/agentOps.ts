/**
 * §RAT (P8b) — the read rails behind the "Your agents" cockpit pane.
 *
 * Three DIFFERENT facts about an agent, deliberately kept apart because conflating them
 * is how a dashboard lies:
 *
 *   ENFORCEMENT  `agents.status` — active | suspended | revoked. Written by the
 *                enforcement rail and by soft-delete. It is NOT "is it running", and an
 *                owner cannot set it. (§AGENTCOCKPIT shipped a status select offering
 *                `inactive`/`maintenance`, values the column never holds.)
 *   DEPLOYMENT   the newest `agent_deployments` row — pending | running | success |
 *                failed | cancelled. Absent for an agent that was never deployed through
 *                this registry's CI/CD, which is NOT the same as "not deployed".
 *   TRAFFIC      `/agent-metrics/{id}` — and its empty response is all ZEROS, so an agent
 *                that has never been called is indistinguishable from one failing every
 *                request unless you look at `last_active`.
 */
import apiClient from './client'

/** The vocabulary the CI/CD service actually writes (agent_cicd_service.py:848,1216,1254).
 *  Derived from the writer, never guessed — a status the column cannot hold is fiction. */
export type DeploymentStatus = 'pending' | 'running' | 'success' | 'failed' | 'cancelled'

export interface DeploymentRow {
  id: number | string
  status: DeploymentStatus
  environment?: string | null
  version?: string | null
  started_at?: string | null
  completed_at?: string | null
  duration_seconds?: number | null
  error_message?: string | null
  pipeline_name?: string | null
}

export interface AgentMetrics {
  agent_id: string
  total_requests: number
  success_rate: number
  avg_response_time: number
  uptime_percentage: number
  last_active: string | null
  daily_stats?: { requests_today: number; errors_today: number; unique_callers: number }
}

/** 🔴 The discriminator the metrics endpoint does not give you.
 *
 *  `create_empty_metrics_response` returns total_requests 0 / success_rate 0.0 for an
 *  agent it has never seen — byte-identical to an agent that answered every call with an
 *  error. Rendering "0% success" for the first is a false accusation against a healthy
 *  agent, so the pane asks this instead of reading success_rate directly.
 */
export function neverObserved(m: AgentMetrics | null | undefined): boolean {
  if (!m) return true
  return (m.total_requests || 0) === 0 && !m.last_active
}

export const agentOpsApi = {
  metrics: (agentIdOrDid: string, timeRange: '1h' | '24h' | '7d' | '30d' | 'all' = '24h') =>
    apiClient.get<AgentMetrics>(`/agent-metrics/${encodeURIComponent(agentIdOrDid)}`,
      { params: { time_range: timeRange } }).then(r => r.data),

  /** Newest deployments first. An empty list means "this registry has no CI/CD record",
   *  which the pane says in those words rather than inventing a state. */
  deployments: (did: string, limit = 5) =>
    apiClient.get<any>(`/agents/${encodeURIComponent(did)}/deployments`, { params: { limit } })
      .then(r => {
        const d = r.data
        const rows: DeploymentRow[] = Array.isArray(d) ? d : (d?.deployments || d?.items || [])
        return rows
      }),
}
