/**
 * services/cardPricing.ts — §DISCREFINE (2026-08-23).
 *
 * Read a card's price, whichever way it declares one. Two dialects are legal and
 * both are in production:
 *   1. the legacy top-level `pricing` block, and
 *   2. the A2A v1.0 payment extension, which our own SDK says an agent accepting
 *      A2A payments MUST publish (`extensions[] uri=…/auth/a2a-payment`).
 *
 * The discover RAIL normalises both server-side (routers/agent_cards.py), so list
 * rows arrive ready. This module is for the COLD path, where the FE parses raw
 * `card_data` itself — a card fetched by id or DID, never through discover.
 * Without it the two paths disagree about the same agent, which is exactly how
 * SYBIL read "Free" on the feed while charging 5.0 AVT.
 *
 * PURE on purpose: no imports, so it stays node-unit-testable (the guildActions
 * rule). Importing it must never drag the api client or the router in behind it.
 *
 * Paid ⇔ the legacy block says payment_required, or the extension carries a
 * positive numeric base_rate. `required` on the extension declares extension
 * support, not a charge, so it is carried through but does not decide.
 */
import { currentOwnCurrency } from '@/composables/useFrameManifest'


export const EXT_A2A_PAYMENT = 'https://theprotocol.cloud/extensions/v1/auth/a2a-payment'

export interface CardPrice {
  model: string
  currency: string
  base_rate: string
  payment_required: boolean
  source: 'pricing-block' | 'a2a-extension'
}

export function cardPricing(cd: any): CardPrice | null {
  if (!cd || typeof cd !== 'object') return null

  const p = (cd as any).pricing
  if (p && typeof p === 'object' && (p.base_rate != null || p.payment_required === true)) {
    return {
      model: p.model || 'per_request',
      currency: p.currency || currentOwnCurrency(),
      base_rate: p.base_rate != null ? String(p.base_rate) : '',
      payment_required: p.payment_required === true,
      source: 'pricing-block',
    }
  }

  const exts = (cd as any).extensions
  const ext = Array.isArray(exts)
    ? exts.find((e: any) => e && typeof e === 'object' && e.uri === EXT_A2A_PAYMENT)
    : null
  const rate = ext?.params?.base_rate
  if (rate != null && Number.isFinite(Number(rate)) && Number(rate) > 0) {
    return {
      model: ext.params.pricing_model || 'per_request',
      currency: ext.params.currency || currentOwnCurrency(),
      base_rate: String(rate),
      payment_required: ext.required !== false,
      source: 'a2a-extension',
    }
  }

  return null
}
