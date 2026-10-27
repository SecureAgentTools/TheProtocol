import { apiClient } from './client'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('organizationService')

// TypeScript interfaces for Organizations & Teams
export interface Organization {
  id: string
  name: string
  slug: string
  description?: string
  website?: string
  owner_id: number
  member_count: number
  team_count: number
  agent_count?: number  // Number of agents in the organization
  agent_limit: number
  member_limit: number
  team_limit: number
  settings: Record<string, any>
  created_at: string
  updated_at: string
  is_active: boolean
  /** §ORGPOCKET — `GET /organizations` answers both of these per row
   *  (routers/organizations.py:71-72, filled at :281/:283). They were read by
   *  PocketOrgs and the dashboard without ever being declared here, which is why
   *  the type ratchet carried 12 errors against a field the API really returns. */
  my_role?: string | null
  pending_owner_is_me?: boolean | null
}

/** Wire shape of one row of GET /organizations/{id}/invitations (§ORGINVITE).
 *  ⚠ There is deliberately no `token` field — it is a bearer secret and a list
 *  is exactly what ends up in a log or a screenshot. */
export interface OrgInvitationRow {
  id: string
  email: string
  role: string
  /** pending | accepted | expired | cancelled — expiry is computed server-side */
  status: string
  invited_by?: number | null
  invited_by_name?: string | null
  created_at?: string | null
  expires_at?: string | null
  accepted_at?: string | null
}

/** Wire shape of GET /organizations/invitations/{token} (§ORGJOIN). */
export interface InvitationPreview {
  valid: boolean
  /** pending | accepted | expired | cancelled | unknown */
  status: string
  organization_id?: string
  organization_name?: string | null
  role?: string
  /** the invited address, masked — enough to answer "am I the wrong person" */
  invited_email_hint?: string
  expires_at?: string | null
  /** null when nobody is signed in */
  you_match?: boolean | null
  already_member?: boolean | null
}

export interface Team {
  id: string
  organization_id: string
  name: string
  description?: string
  permissions: string[]
  member_count?: number
  /** Up to six roster names, served by `GET /organizations/{id}/teams`
   *  (routers/organizations.py:106, filled at :606). */
  member_names?: string[]
  created_at: string
  updated_at: string
  is_active: boolean
}

export interface OrganizationMember {
  id: string
  organization_id: string
  developer_id: number
  developer_name: string
  developer_email: string
  role: 'owner' | 'admin' | 'member' | 'guest'
  joined_at: string
  invited_by?: number
  is_active: boolean
}

export interface TeamMember {
  id: string
  team_id: string
  developer_id: number
  developer_name: string
  developer_email: string
  role: 'lead' | 'member'
  joined_at: string
}

export interface OrganizationInvitation {
  id: string
  organization_id: string
  email: string
  role: 'admin' | 'member' | 'guest'
  token: string
  invited_by: number
  created_at: string
  expires_at: string
  accepted_at?: string
  is_active: boolean
  /** the invite route's answer only (§FESUITE V0594): whether the invitation's mail was sent; absent from an older registry */
  mail_sent?: boolean
}

export interface CreateOrganizationRequest {
  name: string
  slug?: string
  description?: string
  website?: string
  settings?: Record<string, any>
}

export interface UpdateOrganizationRequest {
  name?: string
  description?: string
  website?: string
  settings?: Record<string, any>
}

export interface CreateTeamRequest {
  name: string
  description?: string
  permissions?: string[]
}

export interface UpdateTeamRequest {
  name?: string
  description?: string
  permissions?: string[]
}

export interface InviteMemberRequest {
  email: string
  role: 'admin' | 'member' | 'guest'
}

export interface AddTeamMemberRequest {
  developer_id: number
  role?: 'lead' | 'member'
}

export interface BaseResponse {
  success: boolean
  message?: string
  error?: string
}

// ── Organization policy settings (tighten-only over the registry) ──────────────
export type LiabilityMode = 'off' | 'shadow' | 'enforce'

export interface OrgLiabilitySettings {
  mode: LiabilityMode
  presence_threshold_avt: number
}

/** The partial patch the org can store. Any field may be omitted. */
export interface OrgPolicySettings {
  liability?: OrgLiabilitySettings
  contract_offer_ttl_days?: number
}

/** One catalog-driven control descriptor returned by GET /settings. */
export interface OrgSettingsCatalogEntry {
  key: string                 // dotted key, e.g. 'liability.mode'
  /** §ORGSPEND added an object-typed entry (`procurement_limits`, services/org_policy.py:128)
   *  and the union never learned it, so the two `e.type === 'object'` filters that route
   *  those entries to the Members tab were dead to the checker. */
  type: 'enum' | 'number' | 'bool' | 'object'
  label: string
  help?: string
  tighten_only?: boolean      // true → org may only be equal-or-stricter than the registry
  values?: string[]           // enum options
  min?: number                // number bounds
  max?: number
}

/** The registry's own posture — the floor the org tightens on top of. */
export interface OrgRegistryPosture {
  liability_mode: LiabilityMode
  presence_threshold_avt: number
}

export interface PendingOwnershipTransfer {
  to_developer_id: number
  expires_at: string | null
}

export interface OrgSettingsResponse {
  org_id: string
  settings: OrgPolicySettings
  catalog: OrgSettingsCatalogEntry[]
  registry: OrgRegistryPosture
  // E1a — present since the ownership-transfer release; older backends omit both.
  owner_id?: number
  pending_ownership_transfer?: PendingOwnershipTransfer | null
}

export interface OrgSettingsUpdateResponse {
  org_id: string
  settings: OrgPolicySettings
}

/** Error thrown by the settings calls — carries the HTTP status + RFC-7807
 *  `detail` string so callers can branch on 403 (forbidden) vs 422 (validation). */
export interface OrgSettingsError extends Error {
  status?: number
  detail?: string
}

/**
 * Organization Service
 * Handles all organization and team related API calls
 */
class OrganizationService {
  private basePath = '/organizations'

  // ==================
  // Organization CRUD
  // ==================

  /**
   * Create a new organization
   */
  async createOrganization(data: CreateOrganizationRequest): Promise<Organization> {
    try {
      const response = await apiClient.post<Organization>(this.basePath, data)
      return response.data
    } catch (error: any) {
      console.error('Create organization error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to create organization')
    }
  }

  /**
   * List user's organizations
   */
  async listOrganizations(): Promise<Organization[]> {
    try {
      const response = await apiClient.get<Organization[]>(this.basePath)
      return response.data
    } catch (error: any) {
      // §FESUITE (2026-10-05): rethrown, so the caller reports it; logging it here too printed one failure twice
      // (agentvault2-b2, the V0574 leave sweep)
      log.warn('List organizations error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to list organizations')
    }
  }

  /**
   * Get organization by ID
   */
  async getOrganization(orgId: string): Promise<Organization> {
    try {
      const response = await apiClient.get<Organization>(`${this.basePath}/${orgId}`)
      return response.data
    } catch (error: any) {
      console.error('Get organization error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to get organization')
    }
  }

  /**
   * Get organization by slug
   */
  async getOrganizationBySlug(slug: string): Promise<Organization> {
    try {
      const response = await apiClient.get<Organization>(`${this.basePath}/slug/${slug}`)
      return response.data
    } catch (error: any) {
      console.error('Get organization by slug error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to get organization')
    }
  }

  /**
   * Update organization
   */
  async updateOrganization(orgId: string, data: UpdateOrganizationRequest): Promise<Organization> {
    try {
      const response = await apiClient.put<Organization>(`${this.basePath}/${orgId}`, data)
      return response.data
    } catch (error: any) {
      console.error('Update organization error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to update organization')
    }
  }

  /**
   * Delete organization
   */
  async deleteOrganization(orgId: string): Promise<BaseResponse> {
    try {
      const response = await apiClient.delete<BaseResponse>(`${this.basePath}/${orgId}`)
      return response.data
    } catch (error: any) {
      console.error('Delete organization error:', error)
      // E1b — a 409 carries a STRUCTURED detail ({message, blockers[]}): keep it on the
      // Error so the dashboard can render the checklist instead of "[object Object]".
      // The registry's RFC7807 handler json.dumps() a dict detail onto the wire, so it
      // arrives as a JSON STRING here — parse it back before deciding its shape.
      let rawDetail = error.response?.data?.detail
      if (typeof rawDetail === 'string' && rawDetail.trim().startsWith('{')) {
        try { rawDetail = JSON.parse(rawDetail) } catch { /* keep the string */ }
      }
      const message = typeof rawDetail === 'string'
        ? rawDetail
        : (rawDetail?.message || 'Failed to delete organization')
      const err = new Error(message) as Error & { status?: number; detail?: any }
      err.status = error.response?.status
      err.detail = rawDetail
      throw err
    }
  }

  // ==================
  // Team Management
  // ==================

  /**
   * Create a team in an organization
   */
  async createTeam(orgId: string, data: CreateTeamRequest): Promise<Team> {
    try {
      const response = await apiClient.post<Team>(`${this.basePath}/${orgId}/teams`, data)
      return response.data
    } catch (error: any) {
      console.error('Create team error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to create team')
    }
  }

  /**
   * List teams in an organization
   */
  async listTeams(orgId: string): Promise<Team[]> {
    try {
      const response = await apiClient.get<Team[]>(`${this.basePath}/${orgId}/teams`)
      return response.data
    } catch (error: any) {
      console.error('List teams error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to list teams')
    }
  }

  /**
   * Get team details
   */
  async getTeam(orgId: string, teamId: string): Promise<Team> {
    try {
      const response = await apiClient.get<Team>(`${this.basePath}/${orgId}/teams/${teamId}`)
      return response.data
    } catch (error: any) {
      console.error('Get team error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to get team')
    }
  }

  /**
   * Update team
   */
  async updateTeam(orgId: string, teamId: string, data: UpdateTeamRequest): Promise<Team> {
    try {
      const response = await apiClient.put<Team>(`${this.basePath}/${orgId}/teams/${teamId}`, data)
      return response.data
    } catch (error: any) {
      console.error('Update team error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to update team')
    }
  }

  /**
   * Delete team
   */
  async deleteTeam(orgId: string, teamId: string): Promise<BaseResponse> {
    try {
      const response = await apiClient.delete<BaseResponse>(`${this.basePath}/${orgId}/teams/${teamId}`)
      return response.data || { success: true, message: 'Team deleted successfully' }
    } catch (error: any) {
      console.error('Delete team error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to delete team')
    }
  }

  // ==================
  // Member Management
  // ==================

  /**
   * List organization members
   */
  async listMembers(orgId: string): Promise<OrganizationMember[]> {
    try {
      const response = await apiClient.get<OrganizationMember[]>(`${this.basePath}/${orgId}/members`)
      return response.data
    } catch (error: any) {
      console.error('List members error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to list members')
    }
  }

  /**
   * Invite member to organization
   */
  async inviteMember(orgId: string, data: InviteMemberRequest): Promise<OrganizationInvitation> {
    try {
      const response = await apiClient.post<OrganizationInvitation>(`${this.basePath}/${orgId}/invite`, data)
      return response.data
    } catch (error: any) {
      console.error('Invite member error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to invite member')
    }
  }

  /**
   * Remove member from organization
   */
  async removeMember(orgId: string, developerId: number): Promise<BaseResponse> {
    try {
      const response = await apiClient.delete<BaseResponse>(`${this.basePath}/${orgId}/members/${developerId}`)
      return response.data
    } catch (error: any) {
      console.error('Remove member error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to remove member')
    }
  }

  /**
   * Update member role
   */
  async updateMemberRole(orgId: string, developerId: number, role: string): Promise<OrganizationMember> {
    try {
      const response = await apiClient.put<OrganizationMember>(
        `${this.basePath}/${orgId}/members/${developerId}/role`,
        { role }
      )
      return response.data
    } catch (error: any) {
      console.error('Update member role error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to update member role')
    }
  }

  /**
   * Accept organization invitation
   */
  /**
   * §ORGINVITE — the invitations this organization has sent. Owner/admin only;
   * a plain member gets a 403 from the server, which is where that decision
   * belongs. The payload carries an `id` and never the token.
   */
  async listInvitations(orgId: string): Promise<OrgInvitationRow[]> {
    const { data } = await apiClient.get<{ invitations: OrgInvitationRow[] }>(
      `${this.basePath}/${orgId}/invitations`)
    return data?.invitations || []
  }

  /**
   * §ORGINVITE — withdraw one that has not been answered. Also FREES THE
   * ADDRESS: `create_invitation` refuses a second pending invitation for the
   * same email, so cancel-then-invite is the repair path for a typo.
   */
  async revokeInvitation(orgId: string, invitationId: string): Promise<{ id: string; status: string; already?: boolean }> {
    const { data } = await apiClient.delete(`${this.basePath}/${orgId}/invitations/${invitationId}`)
    return data
  }

  /**
   * §ORGJOIN — what is behind an invitation link, without accepting it.
   * PUBLIC: an invitee usually arrives with no session at all, so this must
   * resolve before login or the page has nothing to show. `you_match` and
   * `already_member` come back null when nobody is signed in, and are answered
   * by the SERVER when somebody is — never by comparing a masked hint locally.
   */
  async previewInvitation(token: string): Promise<InvitationPreview> {
    const { data } = await apiClient.get<InvitationPreview>(
      `${this.basePath}/invitations/${encodeURIComponent(token)}`)
    return data
  }

  async acceptInvitation(token: string): Promise<BaseResponse> {
    try {
      const response = await apiClient.post<BaseResponse>(`${this.basePath}/invitations/${token}/accept`)
      return response.data
    } catch (error: any) {
      console.error('Accept invitation error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to accept invitation')
    }
  }

  // ==================
  // Team Member Management
  // ==================

  /**
   * Add member to team
   */
  async addTeamMember(orgId: string, teamId: string, data: AddTeamMemberRequest): Promise<TeamMember> {
    try {
      const response = await apiClient.post<TeamMember>(
        `${this.basePath}/${orgId}/teams/${teamId}/members`,
        data
      )
      return response.data
    } catch (error: any) {
      console.error('Add team member error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to add team member')
    }
  }

  /**
   * List team members
   */
  async listTeamMembers(orgId: string, teamId: string): Promise<TeamMember[]> {
    try {
      const response = await apiClient.get<TeamMember[]>(
        `${this.basePath}/${orgId}/teams/${teamId}/members`
      )
      return response.data
    } catch (error: any) {
      console.error('List team members error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to list team members')
    }
  }

  /**
   * Remove member from team
   */
  async removeTeamMember(orgId: string, teamId: string, developerId: number): Promise<BaseResponse> {
    try {
      const response = await apiClient.delete<BaseResponse>(
        `${this.basePath}/${orgId}/teams/${teamId}/members/${developerId}`
      )
      return response.data
    } catch (error: any) {
      console.error('Remove team member error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to remove team member')
    }
  }

  // ==================
  // Track A (RBAC plan) — org authz catalog + org→agent authority grants
  // ==================

  /** A1 — the canonical org-role → agent-permission default slices (any member). */
  async getOrgAuthzCatalog(orgId: string): Promise<{
    org_id: string
    roles: { role: string; permissions: string[]; adds: string[] }[]
    never_included: string[]
  }> {
    try {
      const response = await apiClient.get(`${this.basePath}/${orgId}/authz/catalog`)
      return response.data
    } catch (error: any) {
      console.error('Org authz catalog error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to load org authz catalog')
    }
  }

  /** A2 — every LIVE org→agent authority grant this org has issued (owner/admin). */
  async getOrgAuthorityGrants(orgId: string): Promise<{
    org_id: string
    org_slug: string
    grants: {
      grant_id: number
      agent_did: string
      agent_name: string | null
      permissions: string[]
      expires_at: string | null
      granted_by_dev_id: number | null
      org_linked: boolean
    }[]
  }> {
    try {
      const response = await apiClient.get(`${this.basePath}/${orgId}/agents/authority`)
      return response.data
    } catch (error: any) {
      console.error('Org authority grants error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to load org authority grants')
    }
  }

  /** B3 oversight — spend approvals of the org's agents (owner/admin, READ-ONLY).
   *  Deciding stays with each agent's owning developer (Settings → Approvals). */
  async listOrgSpendApprovals(orgId: string, status?: string, limit = 50): Promise<{
    organization_id: string
    approvals: {
      id: string
      agent_did: string
      agent_name: string | null
      owner_developer_id: number
      action: string
      amount: string
      currency: string | null
      counterparty_did: string | null
      status: string
      reason: string | null
      created_at: string
      expires_at: string | null
      resolved_at: string | null
      consumed_at: string | null
    }[]
    count: number
  }> {
    try {
      const params: Record<string, any> = { limit }
      if (status) params.status = status
      const response = await apiClient.get(`${this.basePath}/${orgId}/spend-approvals`, { params })
      return response.data
    } catch (error: any) {
      console.error('Org spend approvals error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to load org spend approvals')
    }
  }

  /** A4 — apply one A1 role slice to EVERY org agent (owner/admin, idempotent). */
  async bulkApplyAuthority(orgId: string, role: 'guest' | 'member' | 'admin' | 'owner'): Promise<{
    org_id: string; role_slice: string; permissions: string[]; agents: number
  }> {
    try {
      const response = await apiClient.post(`${this.basePath}/${orgId}/agents/grant-bulk`, { role })
      return response.data
    } catch (error: any) {
      console.error('Bulk apply authority error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to bulk-apply authority')
    }
  }

  /** A4 — revoke every live org→agent grant (owner/admin). */
  async bulkRevokeAuthority(orgId: string): Promise<{ org_id: string; revoked: number }> {
    try {
      const response = await apiClient.delete(`${this.basePath}/${orgId}/agents/grant-bulk`)
      return response.data
    } catch (error: any) {
      console.error('Bulk revoke authority error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to bulk-revoke authority')
    }
  }

  /** A6 — the org's own EventStore audit trail (owner/admin, newest-first). */
  async getOrgAuditEvents(orgId: string, opts?: { eventTypes?: string; limit?: number }): Promise<{
    org_id: string; count: number
    events: { event_type: string; timestamp: string | null; data: Record<string, any> }[]
  }> {
    try {
      const params: Record<string, any> = {}
      if (opts?.eventTypes) params.event_types = opts.eventTypes
      if (opts?.limit) params.limit = opts.limit
      const response = await apiClient.get(`${this.basePath}/${orgId}/audit`, { params })
      return response.data
    } catch (error: any) {
      console.error('Org audit error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to load org audit trail')
    }
  }

  // ==================
  // Track C — the org's OWN treasury (distinct from the AGORA listing purses below)
  // ==================

  /** The org money account: which DID, where it came from, live TEG balance.
   *  `source` is 'org' (its own account), 'agora_listing' (money lives in a listing purse
   *  because no org treasury exists yet) or null (no account at all). */
  async getOrgTreasuryAccount(orgId: string): Promise<{
    org_id: string; treasury_agent_did: string | null
    source: 'org' | 'agora_listing' | null; balance: string | null; exists: boolean
  }> {
    const response = await apiClient.get(`${this.basePath}/${orgId}/treasury`)
    return response.data
  }

  /** Create the org's own keyless treasury. Owner only; idempotent server-side. */
  async createOrgTreasuryAccount(orgId: string): Promise<{
    org_id: string; treasury_agent_did: string; created: boolean
  }> {
    const response = await apiClient.post(`${this.basePath}/${orgId}/treasury`)
    return response.data
  }

  /** Fund one of the org's agents from the org treasury (org admin).
   *  The Idempotency-Key is REQUIRED by the server and both escrow legs derive from it —
   *  a fresh key per user-initiated transfer, reused verbatim on any retry of THAT transfer. */
  async fundOrgAgent(orgId: string, agentDid: string, amount: string, idempotencyKey: string): Promise<any> {
    const response = await apiClient.post(
      `${this.basePath}/${orgId}/treasury/fund`,
      { agent_did: agentDid, amount },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    )
    return response.data
  }

  // ==================
  // §ORGCLIENT (H3.1) — the firm commissions guild work as the CLIENT
  // ==================

  /** POST /{orgId}/work-orders — bounty leaves the ORG TREASURY (procurement cap binds). */
  async postOrgWorkOrder(orgId: string, body: {
    title: string; spec?: string; bounty: string; currency?: string
    required_skills?: string[]; min_reputation?: number
    deadline_seconds?: number; stake_required?: number
  }, idempotencyKey: string): Promise<any> {
    const response = await apiClient.post(
      `${this.basePath}/${orgId}/work-orders`, body,
      { headers: { 'Idempotency-Key': idempotencyKey } },
    )
    return response.data
  }

  /** The org's commissioned orders (member read). */
  async listOrgWorkOrders(orgId: string, limit = 50): Promise<any> {
    const response = await apiClient.get(`${this.basePath}/${orgId}/work-orders`, { params: { limit } })
    return response.data
  }

  /** Award a bid on the firm's order (org admin; local bidders only — the door says why). */
  async awardOrgWorkOrder(orgId: string, oid: string, bidId: number): Promise<any> {
    const response = await apiClient.post(`${this.basePath}/${orgId}/work-orders/${oid}/award`, { bid_id: bidId })
    return response.data
  }

  /** Accept + pay (or reject → dispute) the firm's order (org admin). */
  async verifyOrgWorkOrder(orgId: string, oid: string, body: { accept: boolean; stars?: number; feedback?: string }): Promise<any> {
    const response = await apiClient.post(`${this.basePath}/${orgId}/work-orders/${oid}/verify`, body)
    return response.data
  }

  /** Cancel the firm's OPEN order → bounty refunds the treasury (org admin). */
  async cancelOrgWorkOrder(orgId: string, oid: string): Promise<any> {
    const response = await apiClient.post(`${this.basePath}/${orgId}/work-orders/${oid}/cancel`)
    return response.data
  }

  // ==================
  // §pass49 B3 — Org-Agent assignment + CI/CD summary
  // ==================

  /** List agents assigned to an organization (optionally filtered by team). */
  async listOrganizationAgents(orgId: string, teamId?: string): Promise<any> {
    try {
      const params: Record<string, string> = {}
      if (teamId) params.team_id = teamId
      const response = await apiClient.get(`${this.basePath}/${orgId}/agents`, { params })
      return response.data
    } catch (error: any) {
      console.error('List organization agents error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to list organization agents')
    }
  }

  /** Assign an agent to the org (and optionally a team). Creator-only on the agent. */
  async assignAgent(orgId: string, agentDid: string, teamId?: string): Promise<any> {
    try {
      const body: Record<string, any> = {}
      if (teamId) body.team_id = teamId
      const response = await apiClient.post(
        `${this.basePath}/${orgId}/agents/${encodeURIComponent(agentDid)}/assign`,
        body
      )
      return response.data
    } catch (error: any) {
      console.error('Assign agent error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to assign agent')
    }
  }

  /** Remove an agent from the org. */
  async unassignAgent(orgId: string, agentDid: string): Promise<any> {
    try {
      const response = await apiClient.post(
        `${this.basePath}/${orgId}/agents/${encodeURIComponent(agentDid)}/unassign`
      )
      return response.data
    } catch (error: any) {
      console.error('Unassign agent error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to unassign agent')
    }
  }

  /** §pass47 O4 — fleet CI/CD rollup scoped to one org. */
  async getCicdSummary(orgId: string): Promise<any> {
    try {
      const response = await apiClient.get(`${this.basePath}/${orgId}/cicd-summary`)
      return response.data
    } catch (error: any) {
      console.error('Get cicd-summary error:', error)
      throw new Error(error.response?.data?.detail || 'Failed to load org CI/CD summary')
    }
  }

  // ==================
  // Policy settings (tighten-only over the registry)
  // ==================

  /** Normalise an axios error into an Error carrying `.status` + `.detail`,
   *  so callers can distinguish 403 (forbidden) from 422 (validation). The
   *  `.message` mirrors the RFC-7807 detail (falling back to a generic string),
   *  matching the throw-Error(detail) convention used across this service. */
  private normalizeSettingsError(error: any, fallback: string) {
    const status: number | undefined = error?.response?.status
    const rawDetail = error?.response?.data?.detail
    const detail = typeof rawDetail === 'string' ? rawDetail : undefined
    const err = new Error(detail || fallback) as OrgSettingsError
    err.status = status
    err.detail = detail
    return err
  }

  /** GET /organizations/{orgId}/settings — current settings + control catalog + registry posture. */
  async getOrgSettings(orgId: string): Promise<OrgSettingsResponse> {
    try {
      const response = await apiClient.get<OrgSettingsResponse>(`${this.basePath}/${orgId}/settings`)
      return response.data
    } catch (error: any) {
      console.error('Get org settings error:', error)
      throw this.normalizeSettingsError(error, 'Failed to load organization settings')
    }
  }

  /** PUT /organizations/{orgId}/settings — partial patch; returns the stored settings. */
  async updateOrgSettings(orgId: string, patch: OrgPolicySettings): Promise<OrgSettingsUpdateResponse> {
    try {
      const response = await apiClient.put<OrgSettingsUpdateResponse>(`${this.basePath}/${orgId}/settings`, patch)
      return response.data
    } catch (error: any) {
      console.error('Update org settings error:', error)
      throw this.normalizeSettingsError(error, 'Failed to update organization settings')
    }
  }

  // ==================
  // E1a — ownership transfer (two-party handshake) + E1b treasury sweep
  // ==================

  /** Owner offers the org to an active ADMIN member. 400 if the target is not admin yet. */
  async initiateOwnershipTransfer(orgId: string, toDeveloperId: number): Promise<any> {
    const response = await apiClient.post(`${this.basePath}/${orgId}/ownership/transfer`,
      { to_developer_id: toDeveloperId })
    return response.data
  }

  /** The offered developer accepts (takes ownership + its liability) or declines. 410 = offer gone. */
  async respondOwnershipTransfer(orgId: string, accept: boolean): Promise<any> {
    const response = await apiClient.post(`${this.basePath}/${orgId}/ownership/respond`, { accept })
    return response.data
  }

  /** Owner withdraws the pending offer. */
  async cancelOwnershipTransfer(orgId: string): Promise<any> {
    const response = await apiClient.delete(`${this.basePath}/${orgId}/ownership/transfer`)
    return response.data
  }

  /** E3 — the org money/denial roll-up: spend per agent (velocity truth), B1 denials,
   *  approvals by status, treasury flow (flows_available=false when the ES is unreachable). */
  async getOrgActivityRollup(orgId: string, days = 7): Promise<any> {
    const response = await apiClient.get(`${this.basePath}/${orgId}/activity-rollup`, { params: { days } })
    return response.data
  }

  /** E1b — drain the org treasury to an agent the OWNER created (delete pre-requisite).
   *  Same Idempotency-Key contract as fund: fresh per user action, reused verbatim on retry. */
  async sweepOrgTreasury(orgId: string, destAgentDid: string, idempotencyKey: string): Promise<any> {
    const response = await apiClient.post(
      `${this.basePath}/${orgId}/treasury/sweep`,
      { dest_agent_did: destAgentDid },
      { headers: { 'Idempotency-Key': idempotencyKey } },
    )
    return response.data
  }

  /** §CHATDESK H1.1 — the FIRM's verifiable track record (PUBLIC read-side
   *  aggregation over receipts' payee_org_id; the write side has existed since
   *  the firm-bid rail). Honest zeros. */
  async getOrgTrackRecord(orgId: string): Promise<any> {
    const response = await apiClient.get(`${this.basePath}/${orgId}/track-record`)
    return response.data
  }
}

// Export singleton instance
export const organizationService = new OrganizationService()
