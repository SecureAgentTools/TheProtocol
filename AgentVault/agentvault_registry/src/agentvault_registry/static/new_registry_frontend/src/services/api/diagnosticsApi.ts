import { apiClient } from './client'
import type {
  ActionResult,
  ActionsResponse,
  ChecksResponse,
  ConfigResponse,
  RunAllResponse,
  RunResponse,
  TargetsResponse,
} from './types/diagnostics'

const BASE = '/admin/diagnostics'

export const diagnosticsApi = {
  async listTargets(): Promise<TargetsResponse> {
    const { data } = await apiClient.get<TargetsResponse>(`${BASE}/targets`)
    return data
  },

  async listChecks(): Promise<ChecksResponse> {
    const { data } = await apiClient.get<ChecksResponse>(`${BASE}/checks`)
    return data
  },

  async runAll(target: string, force = false): Promise<RunAllResponse> {
    const { data } = await apiClient.post<RunAllResponse>(`${BASE}/run-all`, {
      target,
      force,
    })
    return data
  },

  async runSubset(check_ids: string[], targets: string[], force = false): Promise<RunResponse> {
    const { data } = await apiClient.post<RunResponse>(`${BASE}/run`, {
      check_ids,
      targets,
      force,
    })
    return data
  },

  async listActions(): Promise<ActionsResponse> {
    const { data } = await apiClient.get<ActionsResponse>(`${BASE}/actions`)
    return data
  },

  async runAction(action_id: string, target: string, dry_run = false): Promise<ActionResult> {
    const { data } = await apiClient.post<ActionResult>(
      `${BASE}/actions/${action_id}`,
      { target, dry_run },
    )
    return data
  },

  async getConfig(target: string, sections = 'docker,env,nginx,spire,partner_tegs'): Promise<ConfigResponse> {
    const { data } = await apiClient.get<ConfigResponse>(
      `${BASE}/config/${encodeURIComponent(target)}`,
      { params: { sections } },
    )
    return data
  },
}
