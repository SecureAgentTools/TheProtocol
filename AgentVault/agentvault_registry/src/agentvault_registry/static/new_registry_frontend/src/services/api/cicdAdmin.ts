// §pass49 — admin fleet CI/CD + agent_flags + audit-logs API service.
import { apiClient } from './client'

export interface CicdFleetSummary {
  window_hours: number
  pipelines: { total: number; last_created_at: string | null }
  versions:  { total: number; active: number }
  deployments: {
    total: number; success: number; failed: number; pending: number
    top_failing_agents: Array<{ did: string; fail_count: number }>
  }
  flags: Array<{ flag_type: string; unacked: number; total: number }>
}

export interface CicdAdminDeployment {
  id: string
  agent_did: string
  deployment_type: string | null
  environment: string
  status: 'pending' | 'running' | 'success' | 'failed' | 'cancelled'
  version: string | null
  pipeline_name: string | null
  organization_id: string | null
  started_at: string
  completed_at: string | null
  duration_seconds: number | null
  error_message: string | null
}

export interface AgentFlag {
  id: string
  agent_did: string
  flag_type: string
  raised_at: string
  raised_by_event_id: string | null
  reason: string | null
  source: string | null
  details: Record<string, any> | null
  acknowledged_at: string | null
  acknowledged_by_dev_id: number | null
  ack_notes: string | null
}

export interface AuditLogRow {
  id: string
  timestamp: string
  event_type: string
  correlation_id: string | null
  actor_type: string | null
  actor_id: string | null
  actor_ip: string | null
  target_type: string | null
  target_id: string | null
  action: string
  outcome: string
  severity: string
  details: string | null
  error_message: string | null
  request_id: string | null
  user_agent: string | null
}

class CicdAdminService {
  // ── Fleet ──────────────────────────────────────────────────────────────
  async getFleetSummary(windowHours = 24): Promise<CicdFleetSummary> {
    const r = await apiClient.get('/admin/cicd/summary', { params: { window_hours: windowHours } })
    return r.data
  }

  async listDeployments(opts: {
    status?: string; agent_did?: string; organization_id?: string
    limit?: number; offset?: number
  } = {}): Promise<{ count: number; items: CicdAdminDeployment[] }> {
    const params: Record<string, any> = {}
    if (opts.status) params.status = opts.status
    if (opts.agent_did) params.agent_did = opts.agent_did
    if (opts.organization_id) params.organization_id = opts.organization_id
    params.limit = opts.limit ?? 50
    params.offset = opts.offset ?? 0
    const r = await apiClient.get('/admin/cicd/deployments', { params })
    return r.data
  }

  // ── Flags ──────────────────────────────────────────────────────────────
  async listFlagsForAgent(did: string, onlyUnacked = false, limit = 50):
      Promise<{ agent_did: string; count: number; flags: AgentFlag[] }> {
    const r = await apiClient.get(
      `/admin/agents/${encodeURIComponent(did)}/flags`,
      { params: { only_unacknowledged: onlyUnacked, limit } }
    )
    return r.data
  }

  async listFlagsGlobal(opts: { flag_type?: string; only_unacknowledged?: boolean; since_hours?: number; limit?: number } = {}):
      Promise<{ window_hours: number; count: number; by_type: Record<string, number>; flags: AgentFlag[] }> {
    const r = await apiClient.get('/admin/flags', { params: opts })
    return r.data
  }

  async acknowledgeFlag(did: string, flagId: string, notes?: string):
      Promise<{ status: string; flag: AgentFlag }> {
    const r = await apiClient.post(
      `/admin/agents/${encodeURIComponent(did)}/flags/${flagId}/acknowledge`,
      { notes }
    )
    return r.data
  }

  // ── Audit logs ─────────────────────────────────────────────────────────
  async listAuditLogs(opts: {
    action?: string; actor_id?: string; target_id?: string; severity?: string
    since_hours?: number; limit?: number; offset?: number
  } = {}): Promise<{ count: number; items: AuditLogRow[]; window_hours: number }> {
    const r = await apiClient.get('/admin/audit-logs', { params: opts })
    return r.data
  }
}

export const cicdAdminService = new CicdAdminService()
