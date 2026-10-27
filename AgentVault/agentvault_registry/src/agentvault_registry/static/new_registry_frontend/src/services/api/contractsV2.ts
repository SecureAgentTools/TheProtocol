/**
 * CONTRACT SPINE API (P2-P4, 2026-07-25) — v2 contracts + template library + discovery Engage.
 *
 * Ground truth: routers/contracts_v2.py · routers/contract_templates.py
 * Feature-gated server-side (CONTRACTS_V2_ENABLED / CONTRACT_TEMPLATES_ENABLED → 503 when dark);
 * callers should treat 503 as "not enabled on this registry" and degrade quietly.
 *
 * Mutations require an agent JWT (same override pattern as contracts.ts).
 */

import { apiClient } from './client'
import { registryConfigWithin } from '@/composables/useRegistryConfig'

/** The template library's own refusal where CONTRACT_TEMPLATES_ENABLED is off (routers/contract_templates.py). */
export const TEMPLATES_OFF_DETAIL = 'Contract templates are disabled on this registry'

/** §FESUITE (2026-10-10, the operator batch) — where the registry says it does not run the template library
 *  (registry-config `contract_templates_enabled: false`), a template call is not sent: it answers what the route would
 *  (that 503, which the library tab already reads as "disabled here"). Measured on the sandbox operators: Contracts and
 *  the desk each sent a refused read per visit. An older registry or a config not read in time asks as before. */
async function templatesRunHere(): Promise<void> {
  const cfg = await registryConfigWithin()
  if (cfg.contract_templates_enabled === false) {
    throw Object.assign(new Error(TEMPLATES_OFF_DETAIL), {
      isAxiosError: true, notAsked: true, response: { status: 503, data: { detail: TEMPLATES_OFF_DETAIL } },
    })
  }
}

// ─── shapes (mirror backend dicts) ────────────────────────────────────────────

export interface MilestoneV2 {
  seq: number
  title: string
  terms: Record<string, any> | null
  amount: string
  status: 'pending' | 'submitted' | 'releasing' | 'released' | 'rejected' | 'cancelled'
  deliverable: Record<string, any> | null
  due_at: string | null
  submitted_at: string | null
  released_at: string | null
}

export interface ContractV2 {
  id: string
  legacy_ruc_id: number | null
  contract_type: string
  origin_surface: string
  origin_ref: string | null
  client_did: string
  provider_did: string | null
  payee_did: string | null
  title: string
  terms: Record<string, any> | null
  currency: string
  total_amount: string
  fee_bps: number
  fee_charged: string | null
  escrow_ref: string | null
  template_version_id: string | null
  status: 'draft' | 'offered' | 'agreed' | 'in_progress' | 'completed' | 'disputed' | 'cancelled' | 'expired'
  deadline: string | null
  offer_expires_at: string | null
  created_at: string
  agreed_at: string | null
  completed_at: string | null
  milestones?: MilestoneV2[]
  events?: Array<{ seq: number; event_type: string; actor_did: string | null; payload: any; created_at: string }>
  // §XHIRE cross-registry fields: home rows carry counterparty_home_registry
  // when the OTHER party lives elsewhere; replica rows (read-only couriers
  // from contract_replicas, unioned into /v2/mine) carry replica+home_registry+stale.
  counterparty_home_registry?: string | null
  replica?: boolean
  home_registry?: string
  stale?: boolean
  // §TWOAGENT (V0434 home, V0437 read): the milestones the home has released, from the replica's signed payload;
  // null when the home does not state them
  released_milestones?: number[] | null
}

export interface ContractTemplate {
  id: string
  slug: string
  title: string
  summary: string | null
  owner_agent_did: string
  source_org_id: string | null
  maintained_by_org_id: string | null
  contract_type: string
  visibility: 'private' | 'org' | 'unlisted' | 'public'
  pricing_model: 'free' | 'purchase' | 'royalty'
  price: string | null
  price_currency: string | null
  royalty_bps: number
  verified: boolean
  forked_from_template_id: string | null
  current_version_id: string | null
  usage_count: number
  settle_rate?: number | null
  versions?: Array<{ id: string; version: number; changelog: string | null; content_hash: string; published_at: string | null }>
}

/** Agent-JWT override for mutations — same auth-store pattern as contracts.ts (mutations are
 *  agent-tier; apiClient defaults to the developer JWT for /contracts/*). */
async function agentAuth() {
  const { useAuthStore } = await import('@/stores/auth')
  const authStore = useAuthStore()
  let jwt = authStore.agentToken as string | null
  if (!jwt && authStore.activeAgent?.client_id && authStore.activeAgent?.client_secret) {
    const ok = await authStore.authenticateAsAgent(authStore.activeAgent)
    if (ok) jwt = authStore.agentToken
  }
  return jwt ? { headers: { Authorization: `Bearer ${jwt}` } } : {}
}

export const contractsV2Api = {
  // ── spine ──
  async listOpenOffers(params: { limit?: number; cursor?: string; contract_type?: string } = {}) {
    const { data } = await apiClient.get('/contracts/v2', { params })
    return data as { items: ContractV2[]; next_cursor: string | null }
  },
  async mine(params: { role?: 'client' | 'provider'; status_f?: string } = {}) {
    const { data } = await apiClient.get('/contracts/v2/mine', { params, ...await agentAuth() })
    return data as { items: ContractV2[] }
  },
  async get(cid: string) {
    const { data } = await apiClient.get(`/contracts/v2/${cid}`)
    return data as ContractV2
  },
  async create(body: Record<string, any>) {
    const { data } = await apiClient.post('/contracts/v2', body, await agentAuth())
    return data as ContractV2
  },
  async accept(cid: string) {
    const { data } = await apiClient.post(`/contracts/v2/${cid}/accept`, {}, await agentAuth())
    return data as ContractV2
  },
  async offer(cid: string) {
    const { data } = await apiClient.post(`/contracts/v2/${cid}/offer`, {}, await agentAuth())
    return data as ContractV2
  },
  async submitMilestone(cid: string, seq: number, deliverable: Record<string, any> = {}) {
    const { data } = await apiClient.post(`/contracts/v2/${cid}/milestones/${seq}/submit`, { deliverable }, await agentAuth())
    return data
  },
  async releaseMilestone(cid: string, seq: number, stars?: number) {
    const { data } = await apiClient.post(`/contracts/v2/${cid}/milestones/${seq}/release`, stars ? { stars } : {}, await agentAuth())
    return data
  },
  async rejectMilestone(cid: string, seq: number, reason?: string) {
    const { data } = await apiClient.post(`/contracts/v2/${cid}/milestones/${seq}/reject`, { reason }, await agentAuth())
    return data
  },
  async cancel(cid: string) {
    const { data } = await apiClient.post(`/contracts/v2/${cid}/cancel`, {}, await agentAuth())
    return data
  },

  // ── discovery Engage ──
  // (types below the object, see EngagePreview)
  async engagePreview(did: string) {
    const { data } = await apiClient.get(`/contracts/v2/engage-preview/${did}`)
    // §HIRECOHERE — the preview now answers for ANY discoverable agent and reports the three
    // doors with a reason for each shut one, instead of 404ing. `engagement`/`draft` are
    // unchanged for existing callers and are null when the card carries no terms.
    return data as EngagePreview
  },
  async engage(did: string, body: { total_amount?: number; message?: string; deadline_seconds?: number; open_thread?: boolean } = {}) {
    const { data } = await apiClient.post(`/contracts/v2/engage/${did}`, body, await agentAuth())
    return data as ContractV2
  },

  // ── template library ──
  // §FEPARITY-R4: these reads must carry AGENT auth when an agent is active. The server
  // resolves the reader via get_current_actor_for_read, and `mine` is honoured only for an
  // agent actor — sending only the developer token made the "Mine" filter silently do
  // nothing and left an owner's own private/org templates invisible in the library.
  // agentAuth() returns {} when no agent is active, so anonymous browsing is unchanged.
  async listTemplates(params: { q?: string; contract_type?: string; pricing_model?: string; mine?: boolean; limit?: number; cursor?: string } = {}) {
    await templatesRunHere()
    const { data } = await apiClient.get('/contracts/templates', { params, ...await agentAuth() })
    return data as { items: ContractTemplate[]; next_cursor: string | null }
  },
  async getTemplate(tid: string) {
    await templatesRunHere()
    const { data } = await apiClient.get(`/contracts/templates/${tid}`, await agentAuth())
    return data as ContractTemplate
  },
  async getTemplateVersion(tid: string, n: number) {
    await templatesRunHere()
    const { data } = await apiClient.get(`/contracts/templates/${tid}/versions/${n}`, await agentAuth())
    return data
  },
  async purchaseTemplate(tid: string) {
    await templatesRunHere()
    const { data } = await apiClient.post(`/contracts/templates/${tid}/purchase`, {}, await agentAuth())
    return data
  },
  async instantiateTemplate(tid: string, body: { version?: number; total_amount?: number; provider_did?: string; terms_overrides?: Record<string, any> } = {}) {
    await templatesRunHere()
    const { data } = await apiClient.post(`/contracts/templates/${tid}/instantiate`, body, await agentAuth())
    return data as ContractV2
  },

  // ── template AUTHORING (§FEPARITY-R4) ────────────────────────────────────────
  // Every route below is agent-JWT + require_agent_permission('contract.template.publish').
  // That permission is grant-only (never in a normal role; legacy-full carries it), so a
  // 403 here is a legitimate answer, not a bug — the UI must say so rather than retry.
  // These deliberately THROW: a rejected authoring write must never look like it landed.

  /** Create a template; v1 draft is created inline and is NOT published. */
  async createTemplate(body: {
    slug: string
    title: string
    summary?: string
    contract_type?: string
    visibility?: string
    pricing_model?: string
    price?: number | string
    royalty_bps?: number
    terms?: Record<string, any>
    terms_schema?: Record<string, any>
    milestones?: Array<Record<string, any>>
    suggested_amount?: number | string
    suggested_deadline_seconds?: number
  }) {
    await templatesRunHere()
    const { data } = await apiClient.post('/contracts/templates', body, await agentAuth())
    return data as { template_id: string; version_id: string; version: number; published: boolean }
  },

  /** New DRAFT version on an owned template (content is versioned, never edited in place). */
  async createTemplateVersion(tid: string, body: {
    terms?: Record<string, any>
    terms_schema?: Record<string, any>
    milestones?: Array<Record<string, any>>
    suggested_amount?: number | string
    suggested_deadline_seconds?: number
    changelog?: string
  }) {
    await templatesRunHere()
    const { data } = await apiClient.post(`/contracts/templates/${tid}/versions`, body, await agentAuth())
    return data as { template_id: string; version_id: string; version: number; published: boolean }
  },

  /** FREEZE a version. Irreversible: a published version can never be edited underneath
   *  the agreements that reference it. 409 = missing or already frozen. */
  async publishTemplateVersion(tid: string, n: number) {
    await templatesRunHere()
    const { data } = await apiClient.post(`/contracts/templates/${tid}/versions/${n}/publish`, {}, await agentAuth())
    return data as { template_id: string; version: number; published: boolean; version_id: string }
  },

  /** Metadata / visibility / pricing only — NEVER content. */
  async patchTemplate(tid: string, body: {
    title?: string
    summary?: string
    visibility?: string
    pricing_model?: string
    price?: number | string
    royalty_bps?: number
    maintained_by_org_id?: string
  }) {
    await templatesRunHere()
    const { data } = await apiClient.patch(`/contracts/templates/${tid}`, body, await agentAuth())
    return data as ContractTemplate
  },

  /** Fork a visible template. Lineage is recorded; the copy starts private/free and
   *  royalty is NOT inherited (you price your own line). */
  async forkTemplate(tid: string, body: { slug: string; title?: string }) {
    await templatesRunHere()
    const { data } = await apiClient.post(`/contracts/templates/${tid}/fork`, body, await agentAuth())
    return data as { template_id: string; version_id: string; forked_from: string; published: boolean }
  },
}

/** §HIRECOHERE — what one preview call answers, so no hire surface has to guess.
 *  `available:false` always carries a `reason` a person can read. */
export interface EngageDoor {
  available: boolean
  reason: string | null
  price?: { model: string; currency: string; base_rate: string | null;
            payment_required: boolean; source: 'pricing-block' | 'a2a-extension' } | null
}
export interface EngagePreview {
  provider_did: string
  provider_name: string | null
  is_local: boolean
  /** readable origin name ("Registry-A"), null when the agent is homed here */
  home_registry: string | null
  doors: { per_request: EngageDoor; contract: EngageDoor; guild: EngageDoor }
  engagement: any | null
  draft: any | null
}
