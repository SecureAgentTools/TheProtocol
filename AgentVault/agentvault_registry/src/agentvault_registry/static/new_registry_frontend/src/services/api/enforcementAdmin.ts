// §FEPARITY-4 — the per-agent economic enforcement rail (enforcement_admin.py).
// Existed backend-complete since Phase-6 with ZERO FE callers (the audit's #2
// gap): slash, offense ladder, reward pauses, policy editor and the two-man
// pending queue were MCP/curl-only. apiClient baseURL is /api/v1.
import { apiClient } from './client'

const BASE = '/admin/enforcement'

export interface SlashPreview {
  agent_did?: string
  staked_balance?: number
  slash_amount?: number
  resulting_stake?: number
  [k: string]: unknown
}
export interface EnforcementStatus {
  agent_did?: string
  status?: string
  enforcement_status?: string
  offense_count?: number
  rewards_paused_until?: string | null
  [k: string]: unknown
}
export interface PendingAction {
  id: number | string
  action?: string
  action_type?: string
  agent_did?: string
  requested_by?: string
  reason?: string
  created_at?: string
  [k: string]: unknown
}

export interface PolicyFieldExplain {
  path: string
  value: unknown
  default: unknown
  /** 'policy' = this frame set it · 'default' = the shipped default */
  source: 'policy' | 'default'
  bounds: { min: number | null; max: number | null } | null
  in_bounds: boolean | null
  via_deprecated_key?: string
}

export interface ResolvedPolicy {
  policy_version: number
  /** 'factory_default' = never amended (NOT "unknown") · 'amended' */
  policy_source: 'factory_default' | 'amended'
  policy_hash: string
  modified_by?: string | null
  modified_at?: string | null
  policy_json: Record<string, unknown>
  governed: Record<string, PolicyFieldExplain>
  governed_paths: string[]
}

export const enforcementAdmin = {
  async slashPreview(did: string, amount: number): Promise<SlashPreview> {
    return (await apiClient.get(`${BASE}/agents/${encodeURIComponent(did)}/slash-preview`, { params: { amount } })).data
  },
  async slashStake(did: string, amount: number, reason: string) {
    return (await apiClient.post(`${BASE}/agents/${encodeURIComponent(did)}/slash-stake`, { amount, reason })).data
  },
  async agentStatus(did: string): Promise<EnforcementStatus> {
    return (await apiClient.get(`${BASE}/agents/${encodeURIComponent(did)}/status`)).data
  },
  async recordOffense(did: string, p: { offense_type: string; severity: number; reference?: string; disputed_amount?: number }) {
    return (await apiClient.post(`${BASE}/agents/${encodeURIComponent(did)}/record-offense`, p)).data
  },
  async pauseRewards(did: string, duration_days: number, reason: string) {
    return (await apiClient.post(`${BASE}/agents/${encodeURIComponent(did)}/pause-rewards`, { duration_days, reason })).data
  },
  async resumeRewards(did: string, reason: string) {
    return (await apiClient.post(`${BASE}/agents/${encodeURIComponent(did)}/resume-rewards`, { reason })).data
  },
  async suspend(did: string, reason: string) {
    return (await apiClient.post(`${BASE}/agents/${encodeURIComponent(did)}/suspend`, { reason })).data
  },
  async reinstate(did: string, reason: string) {
    return (await apiClient.post(`${BASE}/agents/${encodeURIComponent(did)}/reinstate`, { reason })).data
  },
  async getPolicy(): Promise<Record<string, unknown>> {
    return (await apiClient.get(`${BASE}/policy`)).data
  },
  async getPolicyDefaults(): Promise<Record<string, unknown>> {
    return (await apiClient.get(`${BASE}/policy/defaults`)).data
  },
  // §FRAMEPOLICY — the policy this frame is ACTUALLY running (the stored row
  // merged onto the shipped defaults), with per-field provenance. getPolicy()
  // returns the stored ROW, which is not the same thing: a row written before a
  // section existed is missing that section and every consumer silently falls
  // back to the default.
  async getResolvedPolicy(): Promise<ResolvedPolicy> {
    return (await apiClient.get(`${BASE}/policy/resolved`)).data
  },
  async updatePolicy(policy_json: Record<string, unknown>, reason: string) {
    return (await apiClient.put(`${BASE}/policy`, { policy_json, reason })).data
  },
  async listPending(): Promise<{ pending?: PendingAction[]; actions?: PendingAction[]; [k: string]: unknown }> {
    return (await apiClient.get(`${BASE}/pending`)).data
  },
  async approvePending(id: number | string) {
    return (await apiClient.post(`${BASE}/pending/${id}/approve`, {})).data
  },
  async rejectPending(id: number | string, reason: string) {
    return (await apiClient.post(`${BASE}/pending/${id}/reject`, { reason })).data
  },
}
