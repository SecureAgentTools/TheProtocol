/**
 * §FLARESHOP (2026-08-16) — the local-currency cosmetic-flare lane.
 *
 * The euro on-ramp is off on every frame, so this is how a cosmetic flare (and
 * with shadow_chancellor, the 37 encirclement variants + 21 broken-machine
 * overlays) actually reaches anyone: the buyer's own agent pays the registry in
 * AVT / JDAY / BVT.
 *
 * The catalog endpoint is PUBLIC and always answers 200, even where the lane is
 * disabled — `enabled` is the honest signal the view gates on, so an operator
 * who has not turned it on still sees exactly what they would be offering.
 */
import { apiClient } from './client'

export interface FlareShopTier {
  tier: string
  rank: number
  price: string
  currency: string
  unlocks_corner_flares: string[]
  unlocks_encirclements: boolean
  encirclement_variant_count: number
  overlay_count: number
  capped: boolean
  cap_total: number | null
  cap_taken: number | null
  cap_full: boolean
}

export interface FlareShopCatalog {
  enabled: boolean
  currency: string
  tiers: FlareShopTier[]
  encirclement_variants: string[]
  encirclement_overlays: string[]
  corner_variants: string[]
  encirclement_unlock_tier: string
  earned_marks_notice: string
}

export interface FlareShopPurchaseResult {
  purchase_id: string
  resumed: boolean
  tier: string
  granted: string
  founder_cap_fallback: boolean
  price: string
  currency: string
  transaction_id: string
  buyer_agent_did: string
  target_agent_did: string
  unlocks: {
    tier: string
    unlocks_corner_flares: string[]
    unlocks_encirclements: boolean
    encirclement_variant_count: number
    overlay_count: number
  }
}

export interface FlareShopReceipt {
  purchase_id: string
  tier: string
  price: string
  currency: string
  status: string
  failure_reason: string | null
  buyer_agent_did: string
  target_agent_did: string | null
  transaction_id: string | null
  created_at: string | null
  completed_at: string | null
}

export const flareShopApi = {
  async getCatalog(): Promise<FlareShopCatalog> {
    const { data } = await apiClient.get('/flare-shop/catalog')
    return data
  },

  async purchase(body: {
    tier: string
    buyer_agent_did: string
    target_agent_did?: string
  }): Promise<FlareShopPurchaseResult> {
    const { data } = await apiClient.post('/flare-shop/purchase', body)
    return data
  },

  async myPurchases(): Promise<{ currency: string; current_flare_tier: string | null; purchases: FlareShopReceipt[] }> {
    const { data } = await apiClient.get('/flare-shop/my-purchases')
    return data
  },
}
