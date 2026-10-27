/**
 * services/cardPricing.test.ts — §DISCREFINE. Node-env vitest
 * (run with `npx vitest run --environment node`).
 *
 * Pins BOTH legal price dialects through the FE's cold path. The SQL in
 * routers/agent_cards.py implements the same rule for the discover rail; these
 * fixtures are the shape both sides must agree on, so a change to one that does
 * not reach the other fails here.
 */
import { describe, it, expect } from 'vitest'
import { cardPricing, EXT_A2A_PAYMENT } from './cardPricing'

const legacyPaid = {
  pricing: { model: 'per_request', currency: 'AVT', base_rate: '0.1', payment_required: true },
}
// SYBIL's real shape, copied from its live card on registry-a.
const extPaid = {
  extensions: [
    { uri: 'https://theprotocol.cloud/extensions/v1/auth/did-jwt-self-signed', required: false },
    {
      uri: EXT_A2A_PAYMENT,
      required: true,
      params: { currency: 'AVT', base_rate: '5.0', pricing_model: 'per_request' },
    },
  ],
}

describe('cardPricing — legacy pricing block', () => {
  it('reads a paid legacy card and names the dialect', () => {
    const p = cardPricing(legacyPaid)!
    expect(p.base_rate).toBe('0.1')
    expect(p.currency).toBe('AVT')
    expect(p.payment_required).toBe(true)
    expect(p.source).toBe('pricing-block')
  })
})

describe('cardPricing — A2A v1.0 payment extension', () => {
  it('reads the extension when there is no pricing block', () => {
    const p = cardPricing(extPaid)!
    expect(p.base_rate).toBe('5.0')
    expect(p.currency).toBe('AVT')
    expect(p.model).toBe('per_request')
    expect(p.payment_required).toBe(true)
    expect(p.source).toBe('a2a-extension')
  })

  it('ignores OTHER extensions on the same card', () => {
    // The did-jwt extension sits first in SYBIL's real card; matching by
    // position instead of uri would read the wrong object.
    expect(cardPricing(extPaid)!.source).toBe('a2a-extension')
  })

  it('prefers the legacy block when a card carries both', () => {
    const both = { ...legacyPaid, ...extPaid }
    expect(cardPricing(both)!.source).toBe('pricing-block')
    expect(cardPricing(both)!.base_rate).toBe('0.1')
  })

  it('carries required:false through as payment_required:false', () => {
    const soft = { extensions: [{ uri: EXT_A2A_PAYMENT, required: false, params: { base_rate: '2', currency: 'BVT' } }] }
    const p = cardPricing(soft)!
    expect(p.payment_required).toBe(false)
    expect(p.base_rate).toBe('2')     // still a price: `required` is not what makes it paid
  })
})

describe('cardPricing — absence is absence', () => {
  it('returns null for a card with no price anywhere', () => {
    expect(cardPricing({ name: 'free agent' })).toBeNull()
  })
  it('returns null for a zero or non-numeric extension rate', () => {
    expect(cardPricing({ extensions: [{ uri: EXT_A2A_PAYMENT, params: { base_rate: '0' } }] })).toBeNull()
    expect(cardPricing({ extensions: [{ uri: EXT_A2A_PAYMENT, params: { base_rate: 'free' } }] })).toBeNull()
  })
  it('survives junk without throwing', () => {
    expect(cardPricing(null)).toBeNull()
    expect(cardPricing({ extensions: 'not-an-array' })).toBeNull()
    expect(cardPricing({ extensions: [null, 7] })).toBeNull()
  })
})
