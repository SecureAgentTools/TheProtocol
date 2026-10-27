import { apiClient } from './client'
import { useLogger } from '@/composables/useLogger'
import { cardPricing } from '@/services/cardPricing'
import { cardAuthSchemes } from '@/services/cardAuth'
import { authService } from '@/services/auth'

const log = useLogger('Discovery')

/**
 * Discovery Service - OWL22 Rewrite
 *
 * Real data sources (source-verified 2026-03-10):
 *   1. GET /api/v1/agent-cards/              → card summaries (10 local agents)
 *   2. GET /api/v1/agent-cards/{id}          → full card_data per agent
 *   3. GET /api/v1/developers/me/agents      → DID + reputation_score + balances (dev JWT)
 *   4. GET /api/v1/federation/network-stats  → total network scope (public)
 *   5. GET /api/v1/admin/federation/peers/all → known peer registries (dev JWT)
 *
 * Note: agent_did is null on card records — reputation merged by name matching.
 * Note: origin_registry_name on cards = null for local, "Registry-B" for federated synced agents.
 */

// ─── Types ─────────────────────────────────────────────────────────────────

interface FullAgentCard {
  id: string
  developer_id: number
  developer_is_verified: boolean
  name: string
  description: string | null
  is_active: boolean
  origin_registry_name: string | null
  created_at: string
  updated_at: string
  card_data: Record<string, any>
  // B8 (2026-06-03) — home-frame currency tags from backend list_agent_cards.
  settlement_currency?: string | null
  trust_domain?: string | null
}

interface AgentMetadata {
  did: string
  name: string | null
  reputation_score: number
  liquid_balance: number
  staked_balance: number
  status: string
  last_active_at: string | null
}

// §DISCOTRUST — this frame's own verdict on a peer, as the public federation rail serves it to an
// AUTHENTICATED caller. Absent for anonymous ones by design, and absent is not "trusted": the
// consumer must render a third state rather than an inviting blank.
export interface PeerTrust {
  state: 'unmeasured' | 'ok' | 'warn' | 'restricted' | 'suspended' | 'unavailable'
  label: string
  discount?: number | null
  interactions?: number
  enforced?: boolean
}

export interface FederationPeer {
  id: number
  name: string
  base_url: string
  status: string
  last_synced_at: string | null
  description: string | null
  trust?: PeerTrust | null
}

export interface NetworkStats {
  totalRegistries: number
  activeRegistries: number
  totalAgents: number
  crossRegistryAgents: number
  /** §TOURBLOG-3 — server-side, local-scoped counts (page sums read 0 on mirror pages) */
  activeAgents: number
  paidServices: number
  /** §DISCFIX — honest counts: DID-deduped network total, local cards, real liveness */
  networkAgents: number
  localAgents: number
  activeAgents24h: number
  activeAgents15m: number
  networkHealth: number
  lastGlobalSync: string | null
}

/** §DISCFIX — facet block returned by GET /agent-cards/discover */
export interface DiscoverFacets {
  total: number
  live_24h: number
  paid: number
  free: number
  origins: { name: string; count: number; live_24h: number; paid: number }[]
  tags: { name: string; count: number }[]
}

export interface DiscoverParams {
  q?: string
  /** origin names; use 'local' for this registry */
  origins?: string[]
  pricing?: 'free' | 'paid' | ''
  tag?: string
  verified_only?: boolean
  active_24h?: boolean
  /** showcase subsets (server-filtered, complete on any frame size) */
  encircled_only?: boolean
  foreign_only?: boolean
  /** §CHATCOHERE D5 — only agents this registry will offer as a FIRST move: the
   *  card has described itself (not still wearing the pull-sync stub) and no
   *  health probe came back unreachable. Strictly additive; default off. */
  answerable_only?: boolean
  /** §REPBOND — only agents holding a reputation bond */
  bonded_only?: boolean
  /** §DISCMIX — lift the bond filter and show what it withheld. The view has sent this since
   *  the withheld-count line shipped; the type never learned about it, so vue-tsc refused every
   *  call to discover() from Discovery.vue. A parameter that exists on the wire and not in the
   *  type is one a refactor can drop without anything noticing. */
  include_unbonded?: boolean
  sort?: string
  limit?: number
  offset?: number
}

export interface EnrichedAgent {
  id: string                     // UUID card primary key
  did: string                    // agent DID (if known via metadata match)
  name: string
  description: string
  humanReadableId: string
  url: string
  type: string
  status: 'active' | 'inactive'
  tags: string[]
  capabilities: Record<string, any>
  authSchemes: any[]
  provider: { name: string; url?: string }
  version: string
  schemaVersion: string
  developerId: number
  developerVerified: boolean
  createdAt: string
  updatedAt: string
  rawCardData: Record<string, any>
  // Live data from /developers/me/agents
  reputation_score: number       // 0-100 real EigenTrust score
  liquid_balance: number         // AVT liquid
  staked_balance: number         // AVT staked
  // Federation
  originRegistry: string | null  // null = local, "Registry-B" = federated synced
  isFederated: boolean
  // B8 (2026-06-03) — home-frame currency for FX-aware discovery. settlement_currency
  // is the agent's native settlement token (AVT/BVT); used by useCurrency.currencyForItem
  // / isForeignItem to badge or grey cross-currency cards. Null → FE viewer-currency fallback.
  settlement_currency?: string | null
  trust_domain?: string | null
  // Pricing — normalised. `source` names which of the two legal dialects answered
  // (see cardPricing below); absent on rows that predate §DISCREFINE.
  pricing: { model: string; currency: string; base_rate: string; payment_required: boolean; source?: string } | null
  // Computed convenience
  is_paid: boolean
  // §REPBOND — the bond the home registry holds in escrow (local truth, or the mirrored card's signed extension)
  is_bonded?: boolean
  reputation?: import('./reputationBond').ReputationBlock | null
  // §CARDLINK (2026-09-08) — does the PUBLISHED ADDRESS answer? His report: *"dont provide a
  // link for them that is dead."* THREE states and the third is the point:
  //   'healthy'     the registry dialled the declared address and it is there
  //   'unhealthy' | 'unreachable'   it is not
  //   null/undefined                never probed here — which is NOT "broken" (a federated
  //                                 mirror legitimately never is), so the UI must SAY that
  //                                 rather than pick one of the other two (§RAT's law).
  // ⚠ NOT `is_live`: that is last_active_at within 24h, i.e. account activity, and it read
  // true for all thirty agents whose address answered 404.
  endpointHealth?: string | null
  endpointCheckedAt?: string | null
  // §DISCREFINE — TRUE only ever reaches an admin viewer: the rail removes
  // unlisted agents from everyone else's population, counts included.
  unlisted?: boolean
  total_balance: number
  is_online: boolean
  // Optional legal links
  termsOfServiceUrl?: string
  privacyPolicyUrl?: string
  // §28 flare composition — hoisted from card_data.flare so UserAvatar can
  // read top-level field names (matches the shape on Developer / Agent rows).
  // Federated cards carry these via federation_sync._build_flare_sidecar;
  // local cards via response-time injection in routers/agent_cards.py.
  flare_tier?: string | null
  flare_id?: string | null
  flare_display_name?: string | null
  flare_tagline?: string | null
  flare_logo_url?: string | null
  flare_link_url?: string | null
  flare_cause?: string | null
  flare_accent_color?: string | null
  flare_corner_variant?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
  selected_corner_flare?: string | null
  selected_encirclement_flare?: string | null
  bears_corner_flare?: boolean
  bears_encirclement_flare?: boolean
}

// ─── Discovery Service ──────────────────────────────────────────────────────

class DiscoveryService {
  private enrichedCache: EnrichedAgent[] = []
  private cacheTimestamp: number = 0
  /** §FESUITE (V0577): the last fetch of the whole list got no answer. fetchAllAgents answers [] either way (its other
   *  callers rely on that), so searchAgents asks this before it calls an empty result a search of the whole network. */
  private fetchAllFailed = false
  private agentMetaCache: AgentMetadata[] = []
  private metaCacheTimestamp: number = 0
  private networkStatsCache: NetworkStats | null = null
  private peerCache: FederationPeer[] = []
  private readonly CACHE_DURATION = 30000 // 30s

  // ─── Internal fetchers ─────────────────────────────────────────────

  /**
   * Fetch all agent cards (local + federated-synced) from Registry-A.
   * Enriches with full card_data and reputation metadata.
   */
  private async fetchAllAgents(): Promise<EnrichedAgent[]> {
    const now = Date.now()
    if (this.enrichedCache.length > 0 && now - this.cacheTimestamp < this.CACHE_DURATION) {
      return this.enrichedCache
    }

    try {
      import.meta.env.DEV && console.log('[Discovery] Fetching agent card list...')
      // §pass12 (2026-05-15) — N+1 elimination. Previously the list call
      // returned summaries without card_data, then per-card GETs filled in
      // the rest. At 250 cards that's 250 unique URLs per browse, which
      // tripped CrowdSec's http-crawl-non_statics scenario (capacity=40)
      // and banned legitimate logged-in users behind VPNs. The list endpoint
      // already supports `include_card_data=true` and the backend now also
      // injects `card_data.flare` in that branch, so a single request gives
      // us everything we need.
      const listResp = await apiClient.get('/agent-cards/', {
        params: { limit: 5000, include_federated: true, include_card_data: true }
      })
      const summaries = this.extractArray(listResp.data)
      import.meta.env.DEV && console.log(`[Discovery] ${summaries.length} cards from /agent-cards/ (single request)`)

      // Each summary now carries its own card_data (when include_card_data=true).
      // For remote-live cards that the local DB doesn't have, card_data may be
      // empty — synthesize a minimal stub so parseFullCard works either way.
      const fullCards = summaries.map((s: any) => {
        const cd = (s && typeof s.card_data === 'object' && s.card_data) ? s.card_data : {}
        return {
          status: 'fulfilled' as const,
          value: {
            id: s.id,
            developer_id: s.developer_id || 0,
            developer_is_verified: s.developer_is_verified || false,
            name: s.name || cd.name || 'Unknown',
            description: s.description || cd.description || '',
            is_active: s.is_active !== false,
            origin_registry_name: s.origin_registry_name ?? null,
            settlement_currency: s.settlement_currency ?? null,
            trust_domain: s.trust_domain ?? null,
            created_at: s.created_at || '',
            updated_at: s.updated_at || '',
            card_data: cd,
          } as FullAgentCard
        }
      })

      // Fetch reputation metadata
      const meta = await this.fetchAgentMetadata()
      // Build name→metadata map for merging
      const metaByName = new Map<string, AgentMetadata>()
      for (const m of meta) {
        if (m.name) metaByName.set(m.name.toLowerCase(), m)
      }

      const enriched: EnrichedAgent[] = []
      for (const result of fullCards) {
        if (result.status === 'fulfilled' && result.value) {
          enriched.push(this.parseFullCard(result.value, metaByName))
        }
      }

      // Deduplicate by name — local registry always wins over federated mirror copies.
      // Registry-B live results include agents synced FROM Registry-A, causing duplicates.
      const seenNames = new Map<string, EnrichedAgent>()
      for (const agent of enriched) {
        const key = agent.name.toLowerCase()
        const existing = seenNames.get(key)
        if (!existing || (existing.isFederated && !agent.isFederated)) {
          seenNames.set(key, agent)
        }
      }
      const deduped = Array.from(seenNames.values())
      import.meta.env.DEV && console.log(`[Discovery] Enriched ${enriched.length} agents → ${deduped.length} after dedup`)
      this.enrichedCache = deduped
      this.cacheTimestamp = now
      this.fetchAllFailed = false
      return deduped
    } catch (error) {
      console.error('[Discovery] Failed to fetch agents:', error)
      this.fetchAllFailed = true
      return []
    }
  }

  /**
   * Fetch agent metadata (DID, reputation, balance) from /developers/me/agents.
   * Requires the current developer to be authenticated.
   * Falls back to empty on error (public users don't have this).
   */
  async fetchAgentMetadata(): Promise<AgentMetadata[]> {
    const now = Date.now()
    if (this.agentMetaCache.length > 0 && now - this.metaCacheTimestamp < this.CACHE_DURATION) {
      return this.agentMetaCache
    }
    // §EMBEDGATE (2026-09-08) — A PUBLIC PAGE MUST NOT ASK A MEMBER'S QUESTION, AT ANY CALL SITE.
    // `/developers/me/agents` is owner-tier: for a visitor it can only be refused. This merge is a
    // convenience (it decorates YOUR OWN agents with balance and reputation you already have); for
    // anyone else it contributes nothing and costs a 401.
    //
    // It became reachable the moment the agent modal opened to anonymous viewers — before that the
    // landing globe rendered a sign-in teaser and never called `lookupByID`. Measured with a
    // context that never held a token: 0 refusals on load, exactly one 401 on the first agent
    // click. §DISCPUBLIC's rule, and the reason it is fixed HERE and not at the call site: gating
    // one caller closes the instance, gating the SOURCE closes the class — every future public
    // surface that looks an agent up inherits it.
    //
    // ⚠ A 401 burst is not cosmetic on this box: it is what trips CrowdSec's
    // `http-generic-401-bf` and self-bans a real person (§BATCH7's residue).
    // ⚠ ASK THE SERVICE THE CLIENT ASKS, NOT A STORAGE KEY. My first version tested
    // `localStorage.getItem('token')`, a key nothing in this app writes — it would have returned
    // `[]` for EVERYONE, silently stripping the balance and reputation merge from every signed-in
    // viewer. `authService.getAccessToken()` is what the request interceptor itself reads to decide
    // whether to attach `Authorization`, so it is the only answer that cannot disagree with the
    // request that follows.
    if (!authService.getAccessToken()) {
      this.agentMetaCache = []
      this.metaCacheTimestamp = now
      return this.agentMetaCache
    }
    try {
      const resp = await apiClient.get('/developers/me/agents')
      const agents: any[] = Array.isArray(resp.data) ? resp.data
        : Array.isArray(resp.data?.agents) ? resp.data.agents : []
      this.agentMetaCache = agents.map(a => ({
        did: a.did || '',
        name: a.name || null,
        reputation_score: typeof a.reputation_score === 'number' ? a.reputation_score : 0,
        liquid_balance: parseInt(a.liquid_balance || '0', 10),
        staked_balance: parseInt(a.staked_balance || '0', 10),
        status: a.status || 'active',
        last_active_at: a.last_active_at || null,
      }))
      this.metaCacheTimestamp = now
      log.info(`Got reputation/balance for ${this.agentMetaCache.length} agents`)
      return this.agentMetaCache
    } catch (e) {
      log.warn('Could not fetch agent metadata (auth required):', e)
      return []
    }
  }

  /**
   * Fetch network-level stats from the federation endpoint.
   * Public endpoint — no auth required.
   */
  async fetchNetworkStats(): Promise<NetworkStats> {
    if (this.networkStatsCache) return this.networkStatsCache
    try {
      const resp = await apiClient.get('/federation/network-stats')
      this.networkStatsCache = {
        totalRegistries: resp.data.totalRegistries || 1,
        activeRegistries: resp.data.activeRegistries || 1,
        totalAgents: resp.data.totalAgents || 0,
        crossRegistryAgents: resp.data.crossRegistryAgents || 0,
        activeAgents: resp.data.activeAgents || 0,
        paidServices: resp.data.paidServices || 0,
        networkAgents: resp.data.networkAgents || 0,
        localAgents: resp.data.localAgents || 0,
        activeAgents24h: resp.data.activeAgents24h || 0,
        activeAgents15m: resp.data.activeAgents15m || 0,
        networkHealth: resp.data.networkHealth || 100,
        lastGlobalSync: resp.data.lastGlobalSync || null,
      }
      return this.networkStatsCache
    } catch {
      return { totalRegistries: 1, activeRegistries: 1, totalAgents: 0, crossRegistryAgents: 0, activeAgents: 0, paidServices: 0, networkAgents: 0, localAgents: 0, activeAgents24h: 0, activeAgents15m: 0, networkHealth: 100, lastGlobalSync: null }
    }
  }

  // ─── §DISCFIX — server-side faceted discovery ───────────────────────
  //
  // The legacy browse (`fetchAllAgents` → client-side search over a
  // limit=5000 include_card_data window) measured 19.8s / 3.4MB on
  // registry-a, covered 337 of 1,970 local agents, and then deduplicated
  // by NAME — which collapses the forge lineages (83 distinct agents named
  // "forge-a-gen-1") and hid ~5,500 real agents. Discovery.vue now browses
  // through GET /agent-cards/discover: DID-deduped, filtered/sorted/paged
  // in SQL, per-origin facet counts, reputation + last_active_at joined for
  // local agents. The legacy methods below are kept for other consumers
  // (AgentDetailModal.lookupByID) — do not re-point the browse at them.

  /** Map a compact /discover item onto the search-result shape the Discovery
   *  templates already consume (flare hoisted top-level for UserAvatar, a
   *  card_data stub for iconUrl, client-side <mark> highlighting for q). */
  private discoverItemToResult(it: any, query?: string): any {
    const f = (it.flare && typeof it.flare === 'object') ? it.flare : {}
    const pricing = (it.pricing && it.pricing.base_rate) ? it.pricing : null
    return {
      id: it.id,
      did: it.did || it.agent_did || '',
      /** §AGENTDISC — the AGENT did keys the track-record attestation endpoints */
      agent_did: it.agent_did || null,
      track_record: it.track_record || null,
      // §REPBOND
      reputation: it.reputation || null,
      is_bonded: !!it.is_bonded,
      humanReadableId: it.human_readable_id || `agent:${it.id}`,
      name: it.name || 'Unnamed Agent',
      description: it.description || '',
      category: '',
      tags: Array.isArray(it.tags) ? it.tags : [],
      url: '',
      provider_name: '',
      creator_name: '',
      is_online: it.is_active !== false,
      // §DISCFIX — real liveness (agents.last_active_at within 24h; null for
      // federated mirrors whose heartbeat lives on their home frame).
      is_live: !!it.is_live,
      last_active_at: it.last_active_at || null,
      liveness_known: it.last_active_at !== null && it.last_active_at !== undefined,
      is_certified: !!it.developer_is_verified,
      developer_verified: !!it.developer_is_verified,
      created_at: it.created_at || '',
      updated_at: it.updated_at || '',
      version: '1.0',
      capabilities: {},
      auth_schemes: [],
      rating: it.reputation_score ?? 0,
      reputation_score: it.reputation_score ?? 0,
      reputation_known: it.reputation_score !== null && it.reputation_score !== undefined,
      liquid_balance: 0,
      staked_balance: 0,
      total_balance: 0,
      pricing,
      is_paid: !!it.is_paid,
      review_count: 0,
      originRegistry: it.is_local ? null : (it.origin_registry_name || 'Federated'),
      isFederated: !it.is_local,
      settlement_currency: it.settlement_currency ?? null,
      trust_domain: it.trust_domain ?? null,
      match_score: 100,
      highlights: query ? {
        name: this.highlight(it.name || '', query),
        description: this.highlight(it.description || '', query),
      } : undefined,
      card_data: { iconUrl: it.icon_url || null, flare: it.flare || null, did: it.did || null },
      flare_tier:                  f.tier                        ?? null,
      flare_id:                    f.id                          ?? null,
      flare_display_name:          f.display_name                ?? null,
      flare_tagline:               f.tagline                     ?? null,
      flare_logo_url:              f.logo_url                    ?? null,
      flare_link_url:              f.link_url                    ?? null,
      flare_cause:                 f.cause                       ?? null,
      flare_accent_color:          f.accent_color                ?? null,
      flare_corner_variant:        f.corner_variant              ?? null,
      flare_encirclement_variant:  f.encirclement_variant        ?? null,
      flare_encirclement_overlay:  f.encirclement_overlay        ?? null,
      selected_corner_flare:       f.selected_corner_flare       ?? null,
      selected_encirclement_flare: f.selected_encirclement_flare ?? null,
      bears_corner_flare:          !!f.bears_corner_flare,
      bears_encirclement_flare:    !!f.bears_encirclement_flare,
    }
  }

  /** Server-side faceted discovery search (fast: ~50ms on an 8k-card frame). */
  async discover(params: DiscoverParams = {}): Promise<{
    results: any[]
    total: number
    has_more: boolean
    facets: DiscoverFacets
    /** §AGENTDISC #191 — present when sort=proven: {sort, weights, formula, scored_agents} */
    ranking: any | null
    /** §FESUITE: what the registry applied (its `applied_filters` echo; null when it sent none). A filter it ignores
     *  still answers 200, so this is the only way to know: include_unbonded binds for the frame's admin only where
     *  the bond is enforced, and reads false here for everyone else. */
    applied: Record<string, any> | null
  }> {
    const query: Record<string, any> = {
      limit: params.limit ?? 30,
      offset: params.offset ?? 0,
      sort: params.sort || 'relevance',
    }
    if (params.q?.trim()) query.q = params.q.trim()
    if (params.origins?.length) query.origins = params.origins.join(',')
    if (params.pricing === 'free' || params.pricing === 'paid') query.pricing = params.pricing
    if (params.tag?.trim()) query.tag = params.tag.trim()
    if (params.verified_only) query.verified_only = true
    if (params.active_24h) query.active_24h = true
    if (params.encircled_only) query.encircled_only = true
    if (params.foreign_only) query.foreign_only = true
    if (params.answerable_only) query.answerable_only = true
    if (params.bonded_only) query.bonded_only = true
    // §FESUITE: the "include agents without a bond" box set this and it was never sent, for anyone (the admin included,
    // the one viewer it can widen the list for); 49-discovery found it
    if (params.include_unbonded) query.include_unbonded = true
    const resp = await apiClient.get('/agent-cards/discover', { params: query })
    const d = resp.data || {}
    const facets: DiscoverFacets = {
      total: d.facets?.total ?? 0,
      live_24h: d.facets?.live_24h ?? 0,
      paid: d.facets?.paid ?? 0,
      free: d.facets?.free ?? 0,
      origins: Array.isArray(d.facets?.origins) ? d.facets.origins : [],
      tags: Array.isArray(d.facets?.tags) ? d.facets.tags : [],
    }
    return {
      results: (Array.isArray(d.items) ? d.items : []).map((it: any) => this.discoverItemToResult(it, params.q?.trim() || undefined)),
      total: d.total ?? 0,
      has_more: !!d.has_more,
      facets,
      ranking: d.ranking ?? null,
      applied: d.applied_filters && typeof d.applied_filters === 'object' ? d.applied_filters : null,
    }
  }

  /**
   * Fetch known federation peers (admin only).
   * Requires developer JWT. Returns empty on 401/403.
   */
  /**
   * The federation strip's peers.
   *
   * §EXPLORESTRIP (2026-09-06, his report: "on refresh on /explore the the registry card strip doesnt
   * show the registries anymore"). This asked `/admin/federation/peers/all` and nothing else, so it
   * answered 401 → [] for a visitor, and Discovery had begun skipping it without a session — which ALSO
   * meant a member landing on a refresh saw an empty strip, because the auth store has not hydrated its
   * token yet when the view mounts. Two bugs, one cause: the strip's only source was a member's source.
   *
   * The PUBLIC federation table is the base for everyone (it states admission since §DIRFEED:
   * `peer_status`, `peer_type`, and the peer's own `public_url`), and the admin list is layered on top
   * only when a session actually produces one — a superset for the people who can see more, never a
   * precondition for the strip existing.
   */
  async fetchFederationPeers(opts?: { authed?: boolean }): Promise<FederationPeer[]> {
    if (this.peerCache.length > 0) return this.peerCache
    const out: FederationPeer[] = []
    try {
      const resp = await apiClient.get('/federation/registries')
      const rows: any[] = Array.isArray(resp.data) ? resp.data : (resp.data?.items || [])
      for (const p of rows) {
        out.push({
          id: p.registry_id ?? p.id,
          name: p.registry_name || p.name || 'Unknown Registry',
          base_url: p.public_url || p.registry_url || p.base_url || '',
          status: String(p.peer_status || p.federation_status || p.status || '').toUpperCase(),
          last_synced_at: p.last_polled_at || p.last_synced_at || null,
          description: p.description || null,
          // §DISCOTRUST — the field-by-field mapper is exactly where a new backend field goes to
          // die (§COCKPITA / api/auth.ts::verify). Carried here or it never reaches a card.
          trust: p.trust || null,
        })
      }
    } catch { /* fall through to whatever the admin list can add */ }
    if (opts?.authed) {
      try {
        const resp = await apiClient.get('/admin/federation/peers/all')
        const items: any[] = resp.data?.items || []
        const byName = new Map(out.map(p => [p.name, p]))
        for (const p of items) {
          const row = {
            id: p.id,
            name: p.name || 'Unknown Registry',
            base_url: p.base_url || '',
            status: (p.status || '').toUpperCase(),
            last_synced_at: p.last_synced_at || null,
            description: p.description || null,
            // ⚠ NO `trust` KEY HERE, DELIBERATELY. This row is merged over the public one with
            // Object.assign, and the admin rail does not carry the verdict — so writing
            // `trust: p.trust || null` (which I did first) ERASES the verdict the public rail
            // correctly supplied. A widening applied to the wrong mapper deletes what the right
            // one produced, and the badge renders "not told" on a frame that knows the answer.
            // Only ever add it, never blank it:
            ...(p.trust ? { trust: p.trust } : {}),
          }
          const seen = byName.get(row.name)
          if (seen) Object.assign(seen, row)
          else { out.push(row); byName.set(row.name, row) }
        }
      } catch { /* a member with no admin reach keeps the public list */ }
    }
    this.peerCache = out
    import.meta.env.DEV && console.log(`[Discovery] ${out.length} federation peer(s) found`)
    return out
  }

  // ─── Parsers ────────────────────────────────────────────────────────

  /** Extract the trust-domain host from a SPIFFE ID (spiffe://<host>/...). */
  private _spiffeTrustDomain(spiffe: string | null | undefined): string | null {
    if (typeof spiffe !== 'string') return null
    const m = spiffe.match(/^spiffe:\/\/([^/]+)/)
    return m ? m[1] : null
  }

  private parseFullCard(
    card: FullAgentCard,
    metaByName: Map<string, AgentMetadata>
  ): EnrichedAgent {
    const cd = card.card_data || {}
    const tags = Array.isArray(cd.tags) ? cd.tags : []

    const typeMap: Record<string, string> = {
      trading: 'trading', analysis: 'analysis', automation: 'automation',
      security: 'security', data: 'data', arbitration: 'security',
      governance: 'governance', validator: 'validation', attestation: 'validation',
      zkp: 'validation', eigentrust: 'trust', federation: 'federation',
    }
    let derivedType = 'custom'
    for (const tag of tags) {
      const lower = (tag || '').toLowerCase()
      if (typeMap[lower]) { derivedType = typeMap[lower]; break }
    }

    // Merge reputation by name (case-insensitive), but only for the same agent: a name is not unique, a DID is the only
    // address. The card row names its agent (`agent_did`); a name-matched row of the viewer's own agents with another
    // DID is another agent (a deleted one included), so neither its DID nor its numbers are taken (agentvault2-56,
    // 2026-10-23: a second agent named Sundial showed, and copied, the first one's DID).
    const nameLower = (card.name || '').toLowerCase()
    const cardDid: string = cd.did || (card as any).agent_did || ''
    const named = metaByName.get(nameLower)
    const meta = named && (!cardDid || !named.did || named.did === cardDid) ? named : undefined

    // Backend sets origin_registry_name='Local' for home agents when include_federated=true
    // (the LIST path, which is authoritative when present). The by-DID DETAIL endpoint does
    // NOT tag the top level → for that path fall back to the card's OWN federation_metadata
    // stamp ("show the source registry stamped in the card data"). §pass78c issue ②.
    const fm = (cd.federation_metadata && typeof cd.federation_metadata === 'object') ? cd.federation_metadata : {}
    const topOrigin = (card.origin_registry_name && card.origin_registry_name !== 'Local')
      ? card.origin_registry_name : null
    const fedOrigin = (card.origin_registry_name == null && fm.origin_registry_name && fm.origin_registry_name !== 'Local')
      ? fm.origin_registry_name : null
    // §HIRECOHERE (2026-08-24) — decide locality from a fact that KNOWS locality.
    // `origin_registry_name` is carried by LOCAL cards too (a frame-c card says
    // "Frame-C"), so `!!originRegistry` classified almost every local agent as
    // FEDERATED on the cold by-DID path — the path Pocket always takes. The modal
    // then asked for a peer card of this very registry, and a registry is never a
    // row in its own peer_registries (§SMARTLOCAL), so Source Registry answered
    // "no registry card published" for 4,815 of frame-c's 4,833 local cards.
    // `federation_metadata.source_registry` is stamped ONLY by federation_sync when
    // a card is IMPORTED, so its presence is the honest mark of a mirror. The LIST
    // path still wins where it tags (it is authoritative and already correct).
    const isMirror = typeof fm.source_registry === 'string' && fm.source_registry.length > 0
    const isFederated = card.origin_registry_name != null ? !!topOrigin : isMirror
    const originRegistry = isFederated ? (topOrigin || fedOrigin || fm.origin_registry_name || 'Federated') : null

    // Hoist card_data.flare → top-level fields (the shape UserAvatar expects).
    // Federated cards: stamped by federation_sync on the source registry's export.
    // Local cards: stamped at response-time by routers/agent_cards.py.
    // Missing block → all flare fields null → UserAvatar falls back to initials.
    const f = (cd.flare && typeof cd.flare === 'object') ? cd.flare : {}

    return {
      id: String(card.id),
      // card_data.did is the authoritative agent DID carried by the card itself
      // (§V0064 P2 — was relying solely on the name-matched metadata fallback,
      // which left .did empty when names didn't match; that also weakened
      // viewAgentByDID's by-DID resolution). Prefer the card's own DID.
      did: cardDid || meta?.did || '',
      name: card.name || cd.name || 'Unnamed Agent',
      description: card.description || cd.description || '',
      humanReadableId: cd.humanReadableId || `agent:${card.id}`,
      // §CARDLINK — carried through BOTH read paths. The discover list supplies it; the
      // single-card fallback (`/agent-cards/{id}`) does not, and `?? null` is what makes that
      // read "never probed here" instead of silently reading as reachable.
      endpointHealth: (card as any).endpoint_health ?? null,
      endpointCheckedAt: (card as any).endpoint_checked_at ?? null,
      url: cd.url || '',
      type: derivedType,
      status: card.is_active ? 'active' : 'inactive',
      tags,
      capabilities: cd.capabilities || {},
      // §CARDAUTH: both legal places, like the price below (an A2A v1.0 card declares its auth in securitySchemes)
      authSchemes: cardAuthSchemes(cd),
      provider: cd.provider || { name: 'Unknown' },
      version: cd.agentVersion || '1.0',
      schemaVersion: cd.schemaVersion || '1.0',
      developerId: card.developer_id,
      developerVerified: card.developer_is_verified || false,
      createdAt: card.created_at || '',
      updatedAt: card.updated_at || '',
      rawCardData: cd,
      // Reputation & balance (real data when available, 0 otherwise)
      reputation_score: meta?.reputation_score ?? 0,
      liquid_balance: meta?.liquid_balance ?? 0,
      staked_balance: meta?.staked_balance ?? 0,
      // Pricing — ONE brain for both dialects (§DISCREFINE). The cold path used
      // to read `card_data.pricing` only, so an agent pricing itself through the
      // A2A payment extension looked free here while the rail knew better.
      pricing: cardPricing(cd),
      is_paid: !!cardPricing(cd),
      total_balance: (meta?.liquid_balance ?? 0) + (meta?.staked_balance ?? 0),
      is_online: card.is_active ? true : false,
      // Federation
      originRegistry,
      isFederated,
      // B8 — home-frame currency. Primary = backend tag (authoritative, list path);
      // fallbacks for the untagged single-card detail path = card_data.fees.settlement_currency,
      // then the agent's own pricing.currency (a paid agent quotes in its native token).
      settlement_currency: card.settlement_currency
        ?? (cd.fees && typeof cd.fees === 'object' ? cd.fees.settlement_currency : null)
        ?? cardPricing(cd)?.currency
        ?? null,
      // Detail path leaves trust_domain null → derive the HOME-frame trust domain from the
      // SPIFFE source_registry stamp so useCurrency resolves the right currency (AVT for
      // agentvault.com / frame-b origins) instead of defaulting to the viewer's. §pass78c ②.
      trust_domain: card.trust_domain ?? this._spiffeTrustDomain(fm.source_registry || fm.first_synced_from) ?? null,
      // §28 flare hoist
      flare_tier:                  f.tier                        ?? null,
      flare_id:                    f.id                          ?? null,
      flare_display_name:          f.display_name                ?? null,
      flare_tagline:               f.tagline                     ?? null,
      flare_logo_url:              f.logo_url                    ?? null,
      flare_link_url:              f.link_url                    ?? null,
      flare_cause:                 f.cause                       ?? null,
      flare_accent_color:          f.accent_color                ?? null,
      flare_corner_variant:        f.corner_variant              ?? null,
      flare_encirclement_variant:  f.encirclement_variant        ?? null,
      flare_encirclement_overlay:  f.encirclement_overlay        ?? null,
      selected_corner_flare:       f.selected_corner_flare       ?? null,
      selected_encirclement_flare: f.selected_encirclement_flare ?? null,
      bears_corner_flare:          !!f.bears_corner_flare,
      bears_encirclement_flare:    !!f.bears_encirclement_flare,
    }
  }

  private extractArray(data: any): any[] {
    if (Array.isArray(data)) return data
    if (data?.items && Array.isArray(data.items)) return data.items
    if (data?.results && Array.isArray(data.results)) return data.results
    if (data?.agent_cards && Array.isArray(data.agent_cards)) return data.agent_cards
    return []
  }

  // ─── Public API ─────────────────────────────────────────────────────

  /**
   * Lookup a single agent by card UUID.
   */
  async lookupByID(cardId: string): Promise<EnrichedAgent> {
    const cleanId = cardId.replace(/^agent:/, '')
    const cached = this.enrichedCache.find(a =>
      a.id === cleanId || a.id === cardId || a.humanReadableId === cardId
    )
    if (cached) return cached

    try {
      const meta = await this.fetchAgentMetadata()
      const metaByName = new Map(meta.filter(m => m.name).map(m => [m.name!.toLowerCase(), m]))
      const resp = await apiClient.get(`/agent-cards/${cleanId}`)
      return this.parseFullCard({ ...resp.data, origin_registry_name: resp.data.origin_registry_name || null }, metaByName)
    } catch {
      throw new Error(`Agent card not found: ${cardId}`)
    }
  }

  async lookupByDID(did: string): Promise<EnrichedAgent> {
    return this.lookupByID(did)
  }

  /**
   * Search agents with client-side filtering.
   * Results include real reputation_score and balance data.
   */
  async searchAgents(query?: string, filters?: any): Promise<{
    results: any[]
    total: number
    facets: any
    suggestions: string[]
    has_more: boolean
  }> {
    const allAgents = await this.fetchAllAgents()
    // §FESUITE (V0577): its one caller (the bridge terminal's DISCOVERY lane) promises its zero is real ("The network is
    // searched whole, so this is a real zero."); a list that could not be read is not searched at all.
    if (this.fetchAllFailed && !allAgents.length) throw new Error('The agent list could not be read')
    let filtered = [...allAgents]

    // Registry filter (local / federated)
    if (filters?.registry === 'local') {
      filtered = filtered.filter(a => !a.isFederated)
    } else if (filters?.registry === 'federated') {
      filtered = filtered.filter(a => a.isFederated)
    }

    // Text search
    if (query?.trim()) {
      const q = query.toLowerCase().trim()
      filtered = filtered.filter(a =>
        a.name.toLowerCase().includes(q) ||
        a.description.toLowerCase().includes(q) ||
        a.humanReadableId.toLowerCase().includes(q) ||
        a.tags.some(t => t.toLowerCase().includes(q)) ||
        a.provider.name.toLowerCase().includes(q) ||
        (a.originRegistry || '').toLowerCase().includes(q)
      )
    }

    // Category filter
    if (filters?.category) filtered = filtered.filter(a => a.type === filters.category)
    // Pricing filter
    if (filters?.pricing_model === 'paid') filtered = filtered.filter(a => a.is_paid)
    else if (filters?.pricing_model === 'free') filtered = filtered.filter(a => !a.is_paid)
    // Active filter
    if (filters?.is_online) filtered = filtered.filter(a => a.status === 'active')
    // Certified filter
    if (filters?.is_certified) filtered = filtered.filter(a => a.developerVerified)
    // Tag filter
    if (filters?.tags?.length > 0) {
      filtered = filtered.filter(a => filters.tags.some((t: string) => a.tags.includes(t)))
    }

    // Sort
    const sortBy = filters?.sort_by || 'relevance'
    if (sortBy === 'created') {
      filtered.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    } else if (sortBy === 'reputation') {
      filtered.sort((a, b) => b.reputation_score - a.reputation_score)
    } else if (sortBy === 'price_low') {
      filtered.sort((a, b) => {
        const pa = a.pricing ? parseFloat(a.pricing.base_rate) : 0
        const pb = b.pricing ? parseFloat(b.pricing.base_rate) : 0
        return pa - pb
      })
    } else if (sortBy === 'price_high') {
      filtered.sort((a, b) => {
        const pa = a.pricing ? parseFloat(a.pricing.base_rate) : 0
        const pb = b.pricing ? parseFloat(b.pricing.base_rate) : 0
        return pb - pa
      })
    } else if (query && sortBy === 'relevance') {
      const q = query.toLowerCase()
      filtered.sort((a, b) => this.relevance(b, q) - this.relevance(a, q))
    }

    const limit = filters?.limit || filtered.length
    const offset = filters?.offset || 0
    const page = filtered.slice(offset, offset + limit)

    return {
      results: page.map(a => this.toSearchResult(a, query)),
      total: filtered.length,
      facets: this.buildFacets(allAgents),
      suggestions: this.buildSuggestions(query, allAgents),
      has_more: offset + limit < filtered.length,
    }
  }

  async getFeaturedAgents(category?: string, limit = 8): Promise<any> {
    const all = await this.fetchAllAgents()
    // Sort by reputation, then active status
    // Prioritize paid service agents (real marketplace value), then by reputation
    const featured = all
      .filter(a => a.status === 'active' && a.name && !a.isFederated)
      .filter(a => !category || a.type === category)
      .sort((a, b) => {
        // Paid agents first
        if (a.is_paid && !b.is_paid) return -1
        if (!a.is_paid && b.is_paid) return 1
        return b.reputation_score - a.reputation_score
      })
      .slice(0, limit)

    return {
      featured: featured.map(a => ({
        did: a.id,
        name: a.name,
        description: a.description,
        category: a.type,
        creator_name: a.provider.name,
        rating: a.reputation_score,
        badges: a.developerVerified ? ['Verified'] : [],
        reputation_score: a.reputation_score,
        pricing: a.pricing,
        is_paid: a.is_paid,
        stats: {
          total_users: 0,
          success_rate: a.reputation_score,
          uptime_percentage: a.status === 'active' ? 99 : 0,
        },
      })),
      rotation_interval: 24,
      next_rotation: new Date(Date.now() + 86400000).toISOString(),
    }
  }

  /** Parse a server `/agent-cards/` list payload (items with card_data + B8
   *  currency tags + injected flare) into EnrichedAgents — shared by the focused
   *  showcase fetchers below. Merges reputation metadata by name. */
  private async parseServerList(data: any): Promise<EnrichedAgent[]> {
    const items = this.extractArray(data)
    const meta = await this.fetchAgentMetadata().catch(() => [] as AgentMetadata[])
    const metaByName = new Map<string, AgentMetadata>()
    for (const m of meta) if (m.name) metaByName.set(m.name.toLowerCase(), m)
    return items.map((s: any) => this.parseFullCard({
      id: s.id,
      developer_id: s.developer_id || 0,
      developer_is_verified: s.developer_is_verified || false,
      name: s.name || 'Unknown',
      description: s.description || '',
      is_active: s.is_active !== false,
      origin_registry_name: s.origin_registry_name ?? null,
      settlement_currency: s.settlement_currency ?? null,
      trust_domain: s.trust_domain ?? null,
      created_at: s.created_at || '',
      updated_at: s.updated_at || '',
      // §FLARESHOP (2026-08-16): carry the agent DID through. This mapper used
      // to drop both `agent_did` and `did`, so parseFullCard's `cd.did ||
      // meta?.did` had nothing to find unless the card itself embedded one and
      // every consumer downstream fell back to the card UUID. That is why the
      // modal's signed-card link pointed at /agents/<uuid>/card-export and
      // 404'd. The row always knows the DID; keep it.
      card_data: (s && typeof s.card_data === 'object' && s.card_data)
        ? { ...s.card_data, did: s.card_data.did || s.agent_did || s.did || null }
        : { did: s.agent_did || s.did || null },
    } as FullAgentCard, metaByName))
  }

  /** Agents bearing an encirclement flare — the "Distinguished Agents" showcase
   *  (replaces the old paid/reputation "featured" grid per Commander, 2026-06-03).
   *  §DISCFIX: now rides /discover — same server filter, but items also carry
   *  real reputation + liveness, and local agents badge as Local instead of as
   *  federated mirrors of their own registry. */
  async getEncircledAgents(limit = 24): Promise<any[]> {
    try {
      // §SHOWCASE-A (2026-09-10) — this band asks the server two questions it was not asking.
      //
      // (1) `sort: 'proven'`. The chain used to be newest-from-the-server then live-to-the-front,
      // deliberately: a sort on `reputation_score` would rank every unscored flare-bearer last
      // forever, and that reasoning still holds — EigenTrust scores 0 for almost everyone here.
      // But the MARK is a different fact, and it is the one this surface is about: settled,
      // verified, receipted guild work. `proven` already ranks by exactly that (server-side,
      // `track_record_scores`, then live, then reputation, then newest) and falls back to
      // `relevance` on a frame whose ledger is empty. It has to be the SERVER's ordering, not a
      // client sort over the page: the limit truncates by the server's key, and the most-verified
      // agents are the OLDEST, so under `newest` the registry's two most-proven (SYBIL 251,
      // Glass Gerald 135) were cut from the response before any client sort could see them.
      //
      // (2) `answerable_only`. A card still wearing the pull-sync stub ("Awaiting first pull-sync
      // from agent's /.well-known/agent-card.json") has never said what it does; a flare sidecar
      // does not make it distinguished, it makes it an empty card with a cosmetic. Measured on
      // registry-a: 8 of the 38 in this band were `flareshop-fe-…-invalid-example-com` stubs
      // mirrored from three stopped cloud operators, and under the newest-first order they
      // outranked every real flare-bearer. The filter removes 9 and keeps all 17 agents carrying
      // a verified track record, so it selects for "has described itself", not for rank.
      //
      // Measured together on registry-a: 38 -> 29 rows, and the grid now opens SYBIL 251 ·
      // Glass Gerald 135 · CRUCIBLE 109 · VERIDIAN 76 instead of an auto-created fiat wallet
      // agent that led on being new. Nothing is buried: unmarked flare-bearers keep their
      // live-then-newest order directly underneath.
      const r = await this.discover({ encircled_only: true, answerable_only: true, sort: 'proven', limit })
      // (3) and then only the ones that have actually earned something. A flare is bought; the mark
      // is settled guild work with receipts, and "Distinguished" is a claim about the second. The
      // tail of this band on registry-a was an auto-created fiat wallet, an mTLS test agent, six
      // AGORA demo traders, a card whose own description begins "Throwaway agent to empirically",
      // a QATEST fixture and a sim agent: 12 of 29, every one of them wearing a flare and none of
      // them distinguished by anything. Because `proven` orders server-side, every marked row is
      // already ahead of every unmarked one, so filtering the page is exact rather than a client
      // sort over a truncation.
      //
      // §DISCMIX: a filter that removes EVERYTHING is indistinguishable from an outage, and most
      // frames have no settled guild work at all. So when nothing on the page carries a mark this
      // falls back to the flare-bearers and the surface says which of the two it is showing,
      // rather than rendering an empty band under a heading that promises agents.
      const marked = r.results.filter((x: any) =>
        Number(x?.track_record?.jobs ?? x?.trackRecord?.jobs ?? 0) > 0)
      return marked.length ? marked : r.results
    } catch { return [] }
  }

  /** Cross-currency (foreign-frame) agents relative to this registry's currency.
   *  §DISCFIX: /discover-backed (`foreign_only=true`) — server-complete on any
   *  frame size, with peer-card currency + trust-domain enrichment. */
  async getForeignAgents(limit = 24): Promise<any[]> {
    try {
      const r = await this.discover({ foreign_only: true, sort: 'reputation', limit })
      return r.results
    } catch { return [] }
  }

  async getFilters(): Promise<any> {
    const all = await this.fetchAllAgents()
    return {
      categories: this.extractCategories(all),
      tags: this.extractTags(all),
      pricing_models: [
        { model: '', label: 'All', count: all.length },
        { model: 'free', label: 'Free', count: all.filter(a => !a.is_paid).length },
        { model: 'paid', label: 'Paid', count: all.filter(a => a.is_paid).length },
      ],
      capabilities: [],
      rating_ranges: [],
      sort_options: [
        { value: 'relevance', label: 'Most Relevant', default: true },
        { value: 'reputation', label: 'Highest Trust', default: false },
        { value: 'balance', label: 'Highest Balance', default: false },
        { value: 'created', label: 'Newest First', default: false },
      ],
    }
  }

  async getLeaderboard(params?: any): Promise<any> {
    const all = await this.fetchAllAgents()
    const sorted = [...all]
      .filter(a => a.name)
      .sort((a, b) => b.reputation_score - a.reputation_score)
      .slice(0, params?.limit || 10)

    return {
      leaderboard: sorted.map((a, i) => ({
        rank: i + 1,
        did: a.humanReadableId,
        name: a.name,
        creator_name: a.provider.name,
        reputation_score: a.reputation_score,
        category: a.type,
        badges: a.developerVerified ? ['Verified'] : [],
        average_rating: a.reputation_score,
        rank_change: 0,
        originRegistry: a.originRegistry,
      })),
      total_entries: all.length,
      time_period: params?.time_period || 'all-time',
      updated_at: new Date().toISOString(),
    }
  }

  clearCache(): void {
    this.enrichedCache = []
    this.cacheTimestamp = 0
    this.agentMetaCache = []
    this.metaCacheTimestamp = 0
    this.networkStatsCache = null
    this.peerCache = []
    import.meta.env.DEV && console.log('[Discovery] Cache cleared')
  }

  // ─── Private helpers ─────────────────────────────────────────────

  private toSearchResult(a: EnrichedAgent, query?: string): any {
    return {
      id: a.id,
      did: a.did || a.humanReadableId,
      humanReadableId: a.humanReadableId,
      name: a.name,
      description: a.description,
      category: a.type,
      tags: a.tags,
      url: a.url,
      provider_name: a.provider.name,
      creator_name: a.provider.name,
      is_online: a.status === 'active',
      is_certified: a.developerVerified,
      developer_verified: a.developerVerified,
      created_at: a.createdAt,
      updated_at: a.updatedAt,
      version: a.version,
      capabilities: a.capabilities,
      auth_schemes: a.authSchemes,
      rating: a.reputation_score,
      reputation_score: a.reputation_score,
      liquid_balance: a.liquid_balance,
      staked_balance: a.staked_balance,
      total_balance: a.liquid_balance + a.staked_balance,
      pricing: a.pricing,
      is_paid: a.is_paid,
      review_count: 0,
      originRegistry: a.originRegistry,
      isFederated: a.isFederated,
      // B8 — carry home-frame currency into the search-result shape so the
      // grid/list cards (useCurrency.currencyForItem / isForeignItem) can
      // FX-badge or grey cross-currency agents. Without these the cards fall
      // back to viewer currency and never detect "foreign".
      settlement_currency: a.settlement_currency ?? null,
      trust_domain: a.trust_domain ?? null,
      match_score: query ? this.relevance(a, query.toLowerCase()) : 100,
      highlights: query ? {
        name: this.highlight(a.name, query),
        description: this.highlight(a.description, query),
      } : undefined,
      // §pass13 (2026-05-15) — Forward card_data + flare hoist to the
      // search-result shape. Discovery's grid/list cards pass these straight
      // into <UserAvatar :user="agent"/>, which needs the top-level
      // flare_* / selected_*_flare / bears_*_flare fields to render the
      // encirclement + corner. Previously toSearchResult stripped them,
      // so search cards rendered as bare initials while the
      // AgentDetailModal (which reads from agentUserShape on rawCardData
      // directly) rendered correctly.
      card_data:                   a.rawCardData,
      flare_tier:                  a.flare_tier ?? null,
      flare_id:                    a.flare_id ?? null,
      flare_display_name:          a.flare_display_name ?? null,
      flare_tagline:               a.flare_tagline ?? null,
      flare_logo_url:              a.flare_logo_url ?? null,
      flare_link_url:              a.flare_link_url ?? null,
      flare_cause:                 a.flare_cause ?? null,
      flare_accent_color:          a.flare_accent_color ?? null,
      flare_corner_variant:        a.flare_corner_variant ?? null,
      flare_encirclement_variant:  a.flare_encirclement_variant ?? null,
      flare_encirclement_overlay:  a.flare_encirclement_overlay ?? null,
      selected_corner_flare:       a.selected_corner_flare ?? null,
      selected_encirclement_flare: a.selected_encirclement_flare ?? null,
      bears_corner_flare:          !!a.bears_corner_flare,
      bears_encirclement_flare:    !!a.bears_encirclement_flare,
    }
  }

  private relevance(a: EnrichedAgent, q: string): number {
    let score = 0
    if (a.name.toLowerCase().includes(q)) score += 50
    if (a.name.toLowerCase() === q) score += 50
    if (a.description.toLowerCase().includes(q)) score += 30
    if (a.tags.some(t => t.toLowerCase().includes(q))) score += 10
    return Math.min(score, 100)
  }

  private highlight(text: string, query: string): string {
    if (!query) return text
    // Escape regex metachars in the query — user input must not break the
    // regex (or silently fail to match). Sanitize re-allowlist only `<mark>`,
    // so the wrapped tag MUST be `<mark>`; using `<strong>` here would round-
    // trip through sanitizeHighlight as escaped literal text.
    const safe = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return text.replace(new RegExp(`(${safe})`, 'gi'), '<mark>$1</mark>')
  }

  private buildFacets(agents: EnrichedAgent[]): any {
    const cats = new Map<string, number>()
    const tags = new Map<string, number>()
    agents.forEach(a => {
      cats.set(a.type, (cats.get(a.type) || 0) + 1)
      a.tags.forEach(t => tags.set(t, (tags.get(t) || 0) + 1))
    })
    return {
      categories: Array.from(cats.entries()).map(([name, count]) => ({ name, count })),
      tags: Array.from(tags.entries()).map(([name, count]) => ({ name, count })),
    }
  }

  private buildSuggestions(query?: string, agents?: EnrichedAgent[]): string[] {
    if (!query || !agents) return []
    const q = query.toLowerCase()
    const suggestions = new Set<string>()
    agents.forEach(a => {
      if (a.name.toLowerCase().includes(q) && a.name.toLowerCase() !== q) {
        suggestions.add(a.name)
      }
    })
    return Array.from(suggestions).slice(0, 5)
  }

  private extractCategories(agents: EnrichedAgent[]): any[] {
    const map = new Map<string, number>()
    agents.forEach(a => map.set(a.type, (map.get(a.type) || 0) + 1))
    const nameMap: Record<string, string> = {
      custom: 'Custom', trading: 'Trading', analysis: 'Analysis',
      automation: 'Automation', security: 'Security', data: 'Data',
      governance: 'Governance', validation: 'Validation', trust: 'Trust',
      federation: 'Federation',
    }
    return Array.from(map.entries()).map(([id, count]) => ({
      id, name: nameMap[id] || id.charAt(0).toUpperCase() + id.slice(1), count,
    }))
  }

  private extractTags(agents: EnrichedAgent[]): any[] {
    const map = new Map<string, number>()
    agents.forEach(a => a.tags.forEach(t => map.set(t, (map.get(t) || 0) + 1)))
    return Array.from(map.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 30)
      .map(([name, count]) => ({ name, count }))
  }
}

export const discoveryService = new DiscoveryService()
export default DiscoveryService
