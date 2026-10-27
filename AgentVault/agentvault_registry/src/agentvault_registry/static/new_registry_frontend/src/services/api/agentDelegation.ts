// IRONKEY L3/L4 — delegation grants + capability-token oversight API client.
// apiClient.baseURL already carries /api/v1, so paths here are relative.
// Developer-JWT surfaces only (owner/admin) — the issue/attenuate/consume agent-JWT
// endpoints are machine-to-machine and are not called from this human panel.
import { apiClient } from './client'

export interface DelegationGrant {
  id: number
  principal: string            // "dev:12" | "org:acme" | "agent:did:…"
  permissions: string[]
  may_redelegate: boolean
  max_depth: number
  expires_at: string | null
  revoked: boolean
}

export interface DelegationCreate {
  principal_type: 'dev' | 'org' | 'agent' | 'service'
  principal_ref: string
  permissions: string[]
  may_redelegate?: boolean
  max_depth?: number
  ttl_hours?: number | null
}

export interface CapabilityToken {
  id: number
  role: 'issuer' | 'holder'
  issuer_did: string
  holder_did: string | null
  parent_token_id: number | null
  depth: number
  status: 'issued' | 'active' | 'expired' | 'revoked' | 'exhausted'
  permissions: string[]
  budget_remaining: number | null
  currency: string | null
  expires_at: string | null
  /** SEC-11: the token's own limits, which a child derived from it must stay within */
  caveats?: Record<string, any>
  max_uses?: number | null      // null = unbounded reuse
  uses_left?: number | null
}

export interface DelegationReport {
  mode: 'off' | 'shadow' | 'enforce'
  active_delegation_grants: number
  capability_tokens_by_status: Record<string, number>
  /** D6-272: this registry's cross-registry revokes, by delivery state, and the ones not delivered */
  xreg_revoke_delivery?: {
    counts: Record<XRegRevokeDelivery['state'], number>
    undelivered: Array<XRegRevokeDelivery & { credential_id: string; issuer_did: string; delegate_registry: string }>
    max_attempts: number
  }
}

// §SUBAGENT-LIABILITY — one HAND (walletless sub-agent, anchored to a principal)
// or a normal sub-agent token in an agent's lineage tree. Flat; nest client-side
// via parent_did→hand_did using `generation` as depth.
export interface LineageHand {
  token_id: number
  hand_did: string
  parent_did: string
  generation: number            // 1-based depth from the root agent
  anchored: boolean             // true = walletless hand, principal is the party of record
  permissions: string[]
  status: string
  alive: boolean
  uses: number
  max_uses: number | null       // null = unbounded reuse
  uses_left: number | null
  budget_remaining: number | null
  currency: string | null
  expires_at: string | null     // ISO
  no_redelegate: boolean
}

export interface LineageBirth {
  parent_did: string
  birth_token_id: number
  status: string
  anchored: boolean
  expires_at: string | null     // ISO
}

// A cross-frame delegation ("foreign hand"): a bounded slice of THIS agent's
// authority extended to an agent living on a PEER frame (POST /agents/delegate-
// cross-registry). It is not a spawned local hand — it lives on another registry
// and is opened cross-origin on that registry's own UI.
export interface ForeignHand {
  credential_id: string
  delegate_did: string
  home_registry: string | null
  home_frame: string | null          // short label, e.g. "op-doha" / "frame-b"
  home_ui_url: string | null         // peer's own /ui#/agent/<did>
  permissions: string[]
  caveats: Record<string, any>
  expires_at: string | null
  status: string                     // delegated | active | revoked | expired | ship_failed
  live: boolean                      // true = peer-confirmed live status; false = declared from local audit
  issued_at: string | null
}

export interface AgentLineage {
  agent_did: string
  mode: 'off' | 'shadow' | 'enforce' | string
  born_from: LineageBirth | null
  hands: LineageHand[]
  foreign_hands?: ForeignHand[]
  counts: { total: number; alive: number; anchored: number; generations: number; foreign?: number }
  note: string
}

/** D6-272: how a revoke's message to the delegate's registry stands (the revoke itself is decided here). */
export interface XRegRevokeDelivery {
  /** not_queued: recorded before this registry sent undelivered revokes again */
  state: 'delivered' | 'retrying' | 'given_up' | 'expired' | 'not_queued'
  attempts: number | null
  next_attempt_at: string | null
  last_status: number | null
  last_error: string | null
}

/** §FESUITE V0595: a delegation this agent issued to an agent on another registry (its issue-side record). */
export interface XRegDelegation {
  credential_id: string
  delegate_did: string
  delegate_registry: string | null
  permissions: string[]
  caveats: Record<string, unknown>
  expires_at: string | null
  issued_at: string
  /** the delegate's home took the credential */
  delivered: boolean
  revoked_at: string | null
  revoke_delivered: boolean | null
  /** D6-272: null until a revoke is recorded */
  revoke_delivery?: XRegRevokeDelivery | null
  /** 'revoked' once a revoke is recorded here, delivered or not */
  state: 'active' | 'expired' | 'revoked' | 'not_delivered'
}

class AgentDelegationApi {
  /** §FESUITE V0595: the cross-registry delegations the ACTING agent issued (its token: tier.ts). */
  async listXreg(): Promise<{ issuer_did: string; delegations: XRegDelegation[] }> {
    const { data } = await apiClient.get('/agents/delegate-cross-registry')
    return data
  }

  /** §FESUITE V0595: delegate a subset of the acting agent's authority to an agent on another registry. */
  async issueXreg(body: {
    delegate_did: string; delegate_registry_url: string; permissions: string[]; ttl_hours: number
    max_per_tx?: number | null
  }): Promise<{ ok: boolean; credential_id: string; expires_at: string; peer_response: any }> {
    const { data } = await apiClient.post('/agents/delegate-cross-registry', body)
    return data
  }

  /** §FESUITE V0595: revoke one the acting agent issued. D6-272: recorded here; its message to the delegate's home is
   *  sent again until it lands (`ok` says whether this send landed, `delivery` how it stands). */
  async revokeXreg(credentialId: string, delegateRegistryUrl: string): Promise<{
    ok: boolean; peer_status: number | null; delegate_registry?: string; delivery?: XRegRevokeDelivery
  }> {
    const { data } = await apiClient.delete(`/agents/delegate-cross-registry/${encodeURIComponent(credentialId)}`,
      { params: { delegate_registry_url: delegateRegistryUrl } })
    return data
  }

  /** Delegation grants held by an agent (owner/admin). */
  async listGrants(did: string): Promise<{ agent_did: string; grants: DelegationGrant[] }> {
    const { data } = await apiClient.get(`/agents/${encodeURIComponent(did)}/delegations`)
    return data
  }

  /** Delegate a permission subset TO an agent from a principal the caller controls. */
  async createGrant(did: string, body: DelegationCreate): Promise<any> {
    const { data } = await apiClient.post(`/agents/${encodeURIComponent(did)}/delegations`, body)
    return data
  }

  async revokeGrant(grantId: number): Promise<any> {
    const { data } = await apiClient.delete(`/delegations/${grantId}`)
    return data
  }

  /** Read-only oversight: capability tokens an agent issued or holds (owner/admin). */
  async listCapabilities(did: string): Promise<{ agent_did: string; mode: string; tokens: CapabilityToken[] }> {
    const { data } = await apiClient.get(`/agents/${encodeURIComponent(did)}/capabilities`)
    return data
  }

  /** Oversight revoke of a token + its whole subtree (owner/admin). */
  async revokeCapability(did: string, tokenId: number): Promise<any> {
    const { data } = await apiClient.delete(`/agents/${encodeURIComponent(did)}/capabilities/${tokenId}`)
    return data
  }

  /** Admin fleet delegation/capability census. */
  async report(): Promise<DelegationReport> {
    const { data } = await apiClient.get('/admin/agents/delegation/report')
    return data
  }

  /**
   * Sub-agent lineage for an agent (owner/admin): who spawned it (born_from) plus
   * every hand it has spawned, flat with `generation` depth for client-side nesting.
   * maxGen bounds how deep the server walks.
   */
  async getLineage(did: string, maxGen = 8): Promise<AgentLineage> {
    const { data } = await apiClient.get(`/agents/${encodeURIComponent(did)}/lineage`, {
      params: { max_gen: maxGen },
    })
    return data
  }

  // ─── B5 — self-service spawn + attenuate (both are AGENT-authenticated rails:
  //     the caller passes the acting agent's own JWT explicitly) ───

  /** Spawn a scoped sub-agent (hand) under the acting agent. Secrets in the
   *  response are shown ONCE — surface them immediately or lose them. */
  async spawn(body: {
    name?: string | null
    permissions: string[]
    ttl_seconds?: number
    budget_total?: number | null
    max_per_tx?: number | null
    max_uses?: number | null
  }): Promise<{
    child_did: string; client_id: string; client_secret: string
    birth_token: string; birth_token_id: number; parent_did: string
    permissions: string[]; expires_at: string; note: string
  }> {
    // agent-JWT rail — client.ts isAgentEndpoint injects the ACTIVE agent's token
    const { data } = await apiClient.post('/agents/spawn', body)
    return data
  }

  /** Issue a ROOT capability token for one of YOUR agents (developer JWT — the owner
   *  wrapper; no client secret pasting). The agent itself must hold authz.delegate and
   *  the granted permissions must be ⊆ its live authority. Token shown ONCE. */
  async issueAsOwner(did: string, body: {
    holder_agent_did?: string | null
    caveats: Record<string, any>
    budget_total?: number | null
    currency?: string | null
    max_uses?: number | null
    ttl_seconds?: number
  }): Promise<{
    id: number; token: string; issuer_did: string; depth: number
    caveats: Record<string, any>; expires_at: string; note: string
  }> {
    // developer-JWT rail on purpose (isAgentEndpoint deliberately does NOT match this URL)
    const { data } = await apiClient.post(
      `/agents/${encodeURIComponent(did)}/capabilities/issue-as-owner`, body)
    return data
  }

  /** Derive a strictly-weaker child capability token from one the agent holds.
   *  The child att_ string is shown ONCE. */
  async attenuate(tokenId: number, body: {
    caveats: Record<string, any>
    budget_total?: number | null
    max_uses?: number | null
    ttl_seconds?: number
  }): Promise<any> {
    // agent-JWT rail — client.ts isAgentEndpoint injects the ACTIVE agent's token
    const { data } = await apiClient.post(`/agents/capabilities/${tokenId}/attenuate`, body)
    return data
  }
}

export const agentDelegationApi = new AgentDelegationApi()
