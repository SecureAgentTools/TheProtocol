// IRONKEY — agent authorization API client (STRATEGY §21.6).
// apiClient.baseURL already carries /api/v1, so paths here are relative.
import { apiClient } from './client'

export interface SpendPolicy {
  max_per_tx: number | null
  max_per_day: number | null
  allowed_currencies: string[] | null
  counterparty_mode: string
  counterparty_allow: string[] | null
  require_approval_above: number | null
}

export interface AgentAuthzDelegation {
  grant_id: number
  principal_type: string        // 'dev' | 'org' | 'agent' | 'service'
  principal_ref: string         // e.g. "org:acme-slug"
  permissions: string[]
  expires_at: string | null
}

export interface AgentAuthz {
  agent_did: string
  mode: 'off' | 'shadow' | 'enforce'
  roles: string[]
  effective_permissions: string[]
  spend_policy: SpendPolicy | null
  delegate_enabled?: boolean
  /** Track A2 provenance — authority delegated TO this agent, per principal.
   *  Bites only when the agent presents a matching act-token (never merged into
   *  effective_permissions, which is OWN authority). */
  delegations?: AgentAuthzDelegation[]
  /** B2 — per-role grant detail incl. the optional time-box. */
  role_grants?: { role: string; expires_at: string | null }[]
}

export interface AgentDenial {
  action: string                // rbac_deny | spend_deny | org_ceiling_deny | capability_misuse
  timestamp: string | null
  target_type: string | null
  target: string | null
  details: Record<string, any>
  /** §MISUSEDETAIL — the row has always carried these and the endpoint returns them
   *  (routers/agent_authz_api.py:313, mapped at :357): a misuse row is
   *  warning/denied, a breaker trip is critical/revoked. AgentAccessPanel reads
   *  both; until now neither was declared, which is 4 of the ratchet's errors. */
  severity?: string | null
  outcome?: string | null
}

export interface AuthzCatalog {
  mode: 'off' | 'shadow' | 'enforce'
  assignable_roles: string[]
  all_permissions: string[]
  base_permissions: string[]
  grantable_permissions?: string[]
  roles: Record<string, string[]>
  /** SEC-11: what a delegation grant from each principal type (dev, org, agent, service) may carry */
  delegatable_permissions?: Record<string, string[]>
}

export interface AuthzReport {
  mode: string
  legacy_full_agents: number
  capped_agents: number
  role_census: Record<string, number>
}

class AgentAuthzApi {
  /** Served role→permission catalog (single source of truth). */
  async catalog(): Promise<AuthzCatalog> {
    const { data } = await apiClient.get('/agents/authz/catalog')
    return data
  }

  /** An agent's roles + effective permissions + spend policy (owner/admin). */
  async get(did: string): Promise<AgentAuthz> {
    const { data } = await apiClient.get(`/agents/${encodeURIComponent(did)}/authz`)
    return data
  }

  /** Set roles and/or spend policy (full-replace roles; upsert policy).
   *  roles_expires_at (B2, ISO-8601) time-boxes the roles set in this call. */
  async set(
    did: string,
    body: {
      roles?: string[]
      roles_expires_at?: string | null
      spend_policy?: Partial<SpendPolicy>
      delegate_enabled?: boolean
    },
  ): Promise<AgentAuthz> {
    const { data } = await apiClient.put(`/agents/${encodeURIComponent(did)}/authz`, body)
    return data
  }

  /** §MEMBERSHIP (agentvault2-33's authz-role-add): grant ONE role and leave every other grant exactly as it is (the
   *  PUT above replaces the whole set under one expiry). An active grant is left alone (`changed: false`). An image
   *  without the rail answers 404/405; those come back as `null` with no global toast, so a caller can fall back. */
  async addRole(did: string, role: string, expiresAt: string | null = null): Promise<{
    agent_did: string; role: string; changed: boolean; roles: string[]; effective_permissions: string[] } | null> {
    try {
      const { data } = await apiClient.post(`/agents/${encodeURIComponent(did)}/authz/roles`,
        { role, expires_at: expiresAt }, { expectedStatuses: [404, 405] })
      return data
    } catch (e: any) {
      const st = e?.response?.status
      if (st === 405) return null
      // a 404 is either a missing rail (FastAPI's bare "Not Found") or an unknown agent (the route's own sentence)
      if (st === 404 && String(e?.response?.data?.detail ?? '') === 'Not Found') return null
      throw e
    }
  }

  async denials(did: string): Promise<{ agent_did: string; mode: string; denials: AgentDenial[] }> {
    const { data } = await apiClient.get(`/agents/${encodeURIComponent(did)}/authz/denials`)
    return data
  }

  /** Admin fleet report (legacy-full count, capped, role census). */
  async report(): Promise<AuthzReport> {
    const { data } = await apiClient.get('/admin/agents/authz/report')
    return data
  }

  /** Admin clamp: force a role set + optional zero cap. */
  async clamp(did: string, body: { roles: string[]; zero_cap: boolean }): Promise<AgentAuthz> {
    const { data } = await apiClient.post(`/admin/agents/${encodeURIComponent(did)}/authz/clamp`, body)
    return data
  }

  // ─── B3 — the spend step-up approval queue (Settings → Approvals) ───

  /** My agents' parked spends (all statuses unless filtered). */
  async spendApprovals(status?: string): Promise<{ approvals: SpendApproval[] }> {
    const { data } = await apiClient.get('/agents/authz/spend-approvals',
      { params: status ? { status_filter: status } : {} })
    return data
  }

  /** Approve ONE parked spend — usable once, 15-minute fuse. */
  async approveSpend(id: string): Promise<{ id: string; status: string; usable_for_minutes: number }> {
    const { data } = await apiClient.post(`/agents/authz/spend-approvals/${encodeURIComponent(id)}/approve`)
    return data
  }

  /** Deny ONE parked spend. */
  async denySpend(id: string): Promise<{ id: string; status: string }> {
    const { data } = await apiClient.post(`/agents/authz/spend-approvals/${encodeURIComponent(id)}/deny`)
    return data
  }
}

export interface SpendApproval {
  id: string
  agent_did: string
  action: string | null
  amount: string
  currency: string | null
  counterparty_did: string | null
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'consumed'
  reason: string | null
  created_at: string
  expires_at: string
  resolved_at: string | null
  consumed_at: string | null
}

export const agentAuthzApi = new AgentAuthzApi()
