/**
 * services/api/fiatOnramp.ts — PB-1 Stripe Fiat → AVT on-ramp.
 *
 * Backend: routers/fiat_onramp.py (mainframe-only, env-gated).
 * Two flows:
 *   - Logged-in: dev JWT + agent_did → AVT lands in selected agent
 *   - Anonymous: customer_email only → webhook auto-creates Dev + Agent
 *     and emails a magic-link login.
 *
 * Auth tier: NONE for /tiers, /quote, /purchase/{session_id} (public);
 *            DEV JWT for /checkout-session (logged-in flow), /my-purchases.
 *            /checkout-session in anonymous mode requires NO auth.
 */
import { apiClient } from './client'
import axios from 'axios'

const FIAT_BASE = '/fiat'

export interface TierInfo {
  floor_eur: string
  avt_per_eur: string
  tier_label: string
}

export interface TiersResponse {
  min_eur: string
  max_eur: string
  currency: string
  tiers: TierInfo[]
  note: string
}

export interface QuoteResponse {
  eur_amount: string
  avt_amount: string
  avt_per_eur_rate: string
  tier_label: string
}

export interface CheckoutResponse {
  fiat_purchase_id: string
  stripe_session_id: string
  checkout_url: string
  eur_amount: string
  avt_amount: string
  tier_label: string
  expires_at: string
  anonymous_flow: boolean
}

export interface PurchaseStatusResponse {
  fiat_purchase_id: string
  stripe_session_id: string
  status: 'pending' | 'completed' | 'failed' | 'refunded'
  eur_amount: string
  avt_amount: string
  tier_label: string
  agent_did: string | null
  avt_transfer_tx_id: string | null
  anonymous_flow: boolean
  created_at: string
  completed_at: string | null
  /** Earned flare tier — 'sentinel' | 'architect' | 'founder' (PB-1 cosmetic). */
  flare_tier: 'sentinel' | 'architect' | 'founder' | null
}

export interface FlareInfo {
  flare_tier: 'sentinel' | 'architect' | 'founder' | null
  flare_granted_at: string | null
  // PB-1 hardening (2026-05-09): unique id + customization.
  flare_id?: string | null
  display_name?: string | null
  tagline?: string | null
  logo_url?: string | null
  link_url?: string | null
  cause?: string | null
  accent_color?: string | null
}

/**
 * PATCH /flare/customize semantics:
 *   • Omit a field         → leave unchanged on the server
 *   • Pass null/undefined  → backend uses Pydantic exclude_unset; null = no-op
 *   • Pass "__clear__"     → wipe the field back to null
 *   • Pass a string value  → set the new value (after sanitization)
 */
export interface FlareCustomizeRequest {
  display_name?: string | null
  tagline?: string | null
  logo_url?: string | null
  link_url?: string | null
  cause?: string | null
  accent_color?: string | null
}

export interface MoveFlareResponse {
  moved_from_did: string | null
  moved_to_did: string
  flare_tier: 'sentinel' | 'architect' | 'founder'
  flare_granted_at: string
}

export interface PublicStatsResponse {
  total_backers: number
  total_avt_distributed: string
  sentinel_count: number
  architect_count: number
  founder_count: number
  founder_slots_total: number
  founder_slots_remaining: number
  recent_backers: Array<{
    flare_tier: 'sentinel' | 'architect' | 'founder'
    tier_label: string
    minutes_ago: number
    seconds_ago: number
    amount_avt: string
    /** 2026-05-10 — Founders Wall personalization (Migration 0039). Null if buyer skipped. */
    display_name?: string | null
    display_country?: string | null
  }>
}

export interface PurchaseListItem {
  fiat_purchase_id: string
  status: string
  eur_amount: string
  avt_amount: string
  agent_did: string | null
  created_at: string
  completed_at: string | null
}

// Public endpoints — use a bare axios instance to avoid the auth-cascade
// (a 401 from /tiers should NOT log the user out — same pattern as Leaderboard).
const publicAxios = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
})

export const fiatOnrampService = {
  /** Public — tier breakpoints + min/max for the buy page. */
  async getTiers(): Promise<TiersResponse> {
    const r = await publicAxios.get<TiersResponse>(`${FIAT_BASE}/tiers`)
    return r.data
  },

  /** Public — compute AVT for an EUR amount (for live preview). */
  async quote(eur_amount: string): Promise<QuoteResponse> {
    const r = await publicAxios.post<QuoteResponse>(`${FIAT_BASE}/quote`, { eur_amount })
    return r.data
  },

  /**
   * Create a Stripe Checkout Session.
   *
   * Logged-in flow: omit customer_email, supply agent_did. apiClient
   * attaches the dev JWT automatically.
   *
   * Anonymous flow: omit agent_did, supply customer_email. We use the
   * publicAxios instance so the missing dev JWT doesn't trigger a 401
   * cascade if the caller is logged in but wants to use the anon path.
   */
  async createCheckoutSession(payload: {
    eur_amount: string
    agent_did?: string
    customer_email?: string
    /** Optional buyer-supplied developer name (anonymous flow only). */
    developer_name?: string
    /** Optional buyer-supplied first-agent name (anonymous flow only). */
    agent_name?: string
    return_path?: string
    cancel_path?: string
    /** W1 (2026-05-09) — REQUIRED: explicit Terms-of-Service consent. */
    tos_accepted?: boolean
    /** W1 (2026-05-09) — REQUIRED: version of Terms accepted (e.g. '1.4'). */
    tos_version?: string
    /** 2026-05-10 — Founders Wall personalization (Migration 0039). All optional. */
    display_name?: string | null
    display_country?: string | null
    show_on_wall?: boolean
  }): Promise<CheckoutResponse> {
    if (payload.agent_did && !payload.customer_email) {
      // Logged-in flow uses authed apiClient
      const r = await apiClient.post<CheckoutResponse>(`${FIAT_BASE}/checkout-session`, payload)
      return r.data
    }
    // Anonymous flow uses bare axios
    const r = await publicAxios.post<CheckoutResponse>(`${FIAT_BASE}/checkout-session`, payload)
    return r.data
  },

  /** Public-by-session-id — used by the success page to poll AVT credit completion. */
  async getPurchase(stripe_session_id: string): Promise<PurchaseStatusResponse> {
    const r = await publicAxios.get<PurchaseStatusResponse>(
      `${FIAT_BASE}/purchase/${encodeURIComponent(stripe_session_id)}`,
    )
    return r.data
  },

  /** Logged-in dev's purchase history. */
  async listMyPurchases(limit = 50): Promise<PurchaseListItem[]> {
    const r = await apiClient.get<PurchaseListItem[]>(`${FIAT_BASE}/my-purchases`, {
      params: { limit },
    })
    return r.data
  },

  /** Public — anonymized aggregate stats for the BuyAVT page. */
  async getPublicStats(): Promise<PublicStatsResponse> {
    const r = await publicAxios.get<PublicStatsResponse>(`${FIAT_BASE}/stats/public`)
    return r.data
  },

  /**
   * Public — fetch agent flare by DID. Returns nulls if no flare.
   *
   * `originBase` fetches from the agent's OWN registry (§OWNEDHOMES 2026-08-21).
   * Cosmetics live where the agent lives: measured, Hypervisor Hagrid reads
   * `flare_tier: sovereign` at api.theprotocol.cloud and **404 Not Found** for
   * the same DID on frame-c, so an agent acting away from home rendered bare.
   * The endpoint is public and answers `access-control-allow-origin: *`, so
   * this needs no relay, no token and no new route — the same "ask the origin"
   * seam the foreign agent-token mint already uses.
   */
  async getAgentFlare(did: string, originBase?: string | null): Promise<FlareInfo> {
    const r = await publicAxios.get<FlareInfo>(
      `${FIAT_BASE}/flare/agent/${encodeURIComponent(did)}`,
      originBase ? { baseURL: `${originBase}/api/v1` } : undefined,
    )
    return r.data
  },

  /** Public — fetch developer flare by id. Returns nulls if no flare. */
  async getDeveloperFlare(developerId: number): Promise<FlareInfo> {
    const r = await publicAxios.get<FlareInfo>(
      `${FIAT_BASE}/flare/developer/${developerId}`,
    )
    return r.data
  },

  /** Logged-in — move the dev's earned agent flare to another agent they own. */
  async moveAgentFlare(toAgentDid: string): Promise<MoveFlareResponse> {
    const r = await apiClient.post<MoveFlareResponse>(
      `${FIAT_BASE}/flare/move/${encodeURIComponent(toAgentDid)}`,
    )
    return r.data
  },

  /**
   * Logged-in — customize the caller's flare presentation.
   * Returns the full updated FlareInfo. Per-field semantics in the
   * FlareCustomizeRequest doc.
   */
  async customizeFlare(payload: FlareCustomizeRequest): Promise<FlareInfo> {
    const r = await apiClient.patch<FlareInfo>(`${FIAT_BASE}/flare/customize`, payload)
    return r.data
  },
}

// ── Admin types ──

export interface PricingConfigRow {
  id: string
  version: number
  config: {
    tiers: Array<{ floor_eur: string; avt_per_eur: string; tier_label: string; bonus_label?: string }>
    min_eur: string
    max_eur: string
    currency: string
  }
  is_active: boolean
  note: string | null
  created_at: string
  created_by_developer_id: number | null
  deactivated_at: string | null
}

export interface PricingResponse {
  active: PricingConfigRow | null
  history: PricingConfigRow[]
  fallback_in_use: boolean
}

export interface PricingValidationResponse {
  valid: boolean
  errors: string[]
}

export interface SimulationSummary {
  total_eur: string
  total_avt_distributed: string
  fee_collector_consumed: string
  treasury_consumed: string
  fee_collector_remaining: string
  treasury_remaining: string
  purchases_settled: number
  purchases_partial_or_failed: number
  exhaustion_at_purchase: number | null
  waterfall: string[]
}

export interface SimulationTierRow {
  tier_label: string
  count: number
  total_eur: string
  total_avt: string
}

export interface SimulationResponse {
  summary: SimulationSummary
  tier_breakdown: SimulationTierRow[]
  warnings: string[]
}

const ADMIN_BASE = '/admin/fiat'

export const fiatPricingAdminService = {
  /** Read active pricing + history. */
  async getPricing(): Promise<PricingResponse> {
    const r = await apiClient.get<PricingResponse>(`${ADMIN_BASE}/pricing`)
    return r.data
  },

  /** Dry-run validation — no DB write. */
  async validatePricing(config: PricingConfigRow['config'], note: string): Promise<PricingValidationResponse> {
    const r = await apiClient.post<PricingValidationResponse>(
      `${ADMIN_BASE}/pricing/validate`,
      { config, note },
    )
    return r.data
  },

  /** Install new config — atomic. Increments version; current row is archived. */
  async putPricing(config: PricingConfigRow['config'], note: string): Promise<PricingResponse> {
    const r = await apiClient.put<PricingResponse>(
      `${ADMIN_BASE}/pricing`,
      { config, note },
    )
    return r.data
  },

  /** Pure-math simulation — no DB writes. */
  async simulate(payload: {
    config?: PricingConfigRow['config']
    purchases_eur: string[]
    starting_treasury_avt: string
    starting_fee_collector_avt: string
    waterfall?: string[]
  }): Promise<SimulationResponse> {
    const r = await apiClient.post<SimulationResponse>(
      `${ADMIN_BASE}/pricing/simulate`,
      payload,
    )
    return r.data
  },
}

// ── Admin types — purchase explorer + stats + manual ops ──

export type FiatPurchaseStatus = 'pending' | 'completed' | 'failed' | 'refunded'

export interface AdminPurchaseRow {
  id: string
  stripe_session_id: string
  stripe_event_id: string | null
  stripe_payment_intent_id: string | null
  developer_id: number | null
  agent_did: string | null
  customer_email: string | null
  amount_eur: string
  amount_avt: string
  avt_per_eur_rate: string
  tier_label: string
  status: FiatPurchaseStatus
  failure_reason: string | null
  avt_transfer_tx_id: string | null
  anonymous_flow: boolean
  created_at: string
  completed_at: string | null
  refunded_at: string | null
}

export interface AdminPurchaseListResponse {
  total: number
  limit: number
  offset: number
  rows: AdminPurchaseRow[]
}

export interface AdminPurchaseDetail {
  purchase: AdminPurchaseRow
  developer: {
    id: number
    name: string
    email: string
    is_verified: boolean
    must_change_password: boolean
    has_password_reset_token: boolean
    created_at: string
  } | null
  agent: {
    id: number
    did: string
    client_id: string
    status: string
    creator_developer_id: number
    liquid_balance: string
    staked_balance: string
    created_at: string
  } | null
  stripe_session: {
    id: string
    status: string
    payment_status: string
    amount_total: number
    currency: string
    customer_email: string
    payment_intent: string
    url?: string
    [k: string]: unknown
  } | null
  has_magic_link: boolean
}

export interface FiatStatsResponse {
  window_days: number
  total_eur: string
  total_avt: string
  completed_count: number
  pending_count: number
  failed_count: number
  refunded_count: number
  success_rate_pct: string
  anonymous_devs_created: number
  avg_purchase_eur: string
  status_breakdown: Array<{ status: string; count: number }>
  daily_revenue: Array<{ day: string; eur: string; avt: string; purchases: number }>
  tier_share: Array<{ tier_label: string; count: number; total_eur: string; total_avt: string }>
  treasury_consumed_estimate_avt: string
}

export interface AdminPurchaseActionResponse {
  purchase_id: string
  action: string
  status: string
  detail: string | null
}

export const fiatOpsAdminService = {
  async listPurchases(params: {
    status?: string  // csv: pending,completed,failed,refunded
    email?: string
    agent_did?: string
    session_id?: string
    days?: number
    limit?: number
    offset?: number
  } = {}): Promise<AdminPurchaseListResponse> {
    const r = await apiClient.get<AdminPurchaseListResponse>(`${ADMIN_BASE}/purchases`, {
      params: {
        status_filter: params.status,
        email: params.email,
        agent_did: params.agent_did,
        session_id: params.session_id,
        days: params.days,
        limit: params.limit,
        offset: params.offset,
      },
    })
    return r.data
  },

  async getPurchase(id: string): Promise<AdminPurchaseDetail> {
    const r = await apiClient.get<AdminPurchaseDetail>(`${ADMIN_BASE}/purchases/${encodeURIComponent(id)}`)
    return r.data
  },

  async getStats(days = 30): Promise<FiatStatsResponse> {
    const r = await apiClient.get<FiatStatsResponse>(`${ADMIN_BASE}/stats`, { params: { days } })
    return r.data
  },

  async replayPurchase(id: string): Promise<AdminPurchaseActionResponse> {
    const r = await apiClient.post<AdminPurchaseActionResponse>(
      `${ADMIN_BASE}/purchases/${encodeURIComponent(id)}/replay`,
    )
    return r.data
  },

  async resendMagicLink(id: string): Promise<AdminPurchaseActionResponse> {
    const r = await apiClient.post<AdminPurchaseActionResponse>(
      `${ADMIN_BASE}/purchases/${encodeURIComponent(id)}/resend-magic-link`,
    )
    return r.data
  },

  async refund(id: string): Promise<AdminPurchaseActionResponse> {
    const r = await apiClient.post<AdminPurchaseActionResponse>(
      `${ADMIN_BASE}/purchases/${encodeURIComponent(id)}/refund`,
    )
    return r.data
  },
}
