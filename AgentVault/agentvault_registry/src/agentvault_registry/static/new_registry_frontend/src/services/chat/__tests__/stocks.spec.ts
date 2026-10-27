import { describe, it, expect } from 'vitest'
import { normalizeListing, effectivePrice, fxConvert, priceLine, trim, mergeTickers, tradability } from '../stocks'

// The exact shape the live venue returns — pinned from a real
// /exchange/listings row so a field rename fails here rather than silently
// falling back to the founding price again.
const SMKD = {
  symbol: 'SMKD', display_name: 'Samarkand Freight Lines', currency: 'BVT',
  ipo_price: '2.500000000000000000', status: 'trading', total_shares: 100000,
  stats: { last: '51.000000000000000000', best_bid: '49.000000000000000000',
           best_ask: '51.000000000000000000', trades_24h: 1, change_24h: '0.00' },
}
const NEVER_TRADED = {
  symbol: 'WEYL', display_name: 'Weyl', currency: 'BVT',
  ipo_price: '1.500000000000000000', status: 'trading', stats: {},
}
const FOREIGN = {
  symbol: 'CHONK', display_name: 'Chonk', currency: 'AVT',
  ipo_price: '25.000000000000000000', status: 'trading',
  origin: 'op-london', is_local: false,
}
const RATES = { available: true, pairs: [
  { a: 'AVT', b: 'BVT', a_per_b: '0.844493', b_per_a: '1.184143' },
  { a: 'AVT', b: 'JDAY', a_per_b: '1.135382', b_per_a: '0.880761' },
  { a: 'BVT', b: 'JDAY', a_per_b: '1.344455', b_per_a: '0.743796' },
]}

describe('stocks — price truth', () => {
  it('🔴 reads the LIVE price from stats, not ipo_price (the bug that shipped)', () => {
    const r = normalizeListing(SMKD)
    expect(r.last).toBe('51')
    expect(r.bid).toBe('49')
    expect(r.ask).toBe('51')
    expect(r.ipo).toBe('2.5')          // present, but never the answer
    expect(effectivePrice(r)).toEqual({ value: '51', basis: 'ask' })
  })

  it('names the basis honestly when a listing has never traded', () => {
    const r = normalizeListing(NEVER_TRADED)
    expect(r.last).toBeNull()
    expect(effectivePrice(r)).toEqual({ value: '1.5', basis: 'ipo' })
    expect(priceLine(r, 'BVT', RATES)).toContain('never traded')
  })

  it('trims insignificant zeros without rounding anything real', () => {
    expect(trim('2.500000000000000000')).toBe('2.5')
    expect(trim('1000')).toBe('1000')
    expect(trim('0.000001')).toBe('0.000001')
    expect(trim('51.000000000000000000')).toBe('51')
  })

  it('converts across the triangle in BOTH directions', () => {
    expect(fxConvert('10', 'AVT', 'BVT', RATES)).toBe('11.84143')
    expect(fxConvert('10', 'BVT', 'AVT', RATES)).toBe('8.44493')
    expect(fxConvert('10', 'BVT', 'BVT', RATES)).toBe('10')
  })

  it('🔴 yields NO converted figure when the rate is unpublished — never a guess', () => {
    expect(fxConvert('10', 'AVT', 'XXX', RATES)).toBeNull()
    expect(fxConvert('10', 'AVT', 'BVT', null)).toBeNull()
    expect(fxConvert('10', 'AVT', 'BVT', { available: false })).toBeNull()
  })

  it('offers the converted price ALONGSIDE the native one, never instead', () => {
    const r = normalizeListing(FOREIGN)
    const line = priceLine(r, 'BVT', RATES)
    expect(line).toContain('25 AVT')       // the listing's own unit, first
    expect(line).toContain('BVT')          // the viewer's, as an aside
    expect(line).toContain('op-london')    // and where it lives
  })

  it('omits the aside entirely when no rate exists, keeping the native price', () => {
    const line = priceLine(normalizeListing(FOREIGN), 'ZZZ', RATES)
    expect(line).toContain('25 AVT')
    expect(line).not.toContain('≈')
  })

  it('marks foreign listings as foreign', () => {
    expect(normalizeListing(FOREIGN).isLocal).toBe(false)
    expect(normalizeListing(SMKD).isLocal).toBe(true)
  })
})

// ─────────────────────────────────────────────────────────────────────────────
// §SHOWCASESTOCKS-2 — the foreign half, which was still lying.
const TICKERS = { venues: [
  { venue: 'registry-a', currency: 'AVT', listings: [
    { symbol: 'SYBIL', last: '105.100000000000000000' },
    { symbol: 'GRLD', last: '53.420000000000000000' },
  ]},
  { venue: 'frame-b', currency: 'JDAY', listings: [
    { symbol: 'BSEA', last: '27.060000000000000000' },
  ]},
]}
const HALTED = { symbol: 'HLT', display_name: 'Halted Co', currency: 'BVT',
                 ipo_price: '2.000000000000000000', status: 'halted', origin: 'Frame-C', is_local: true,
                 stats: { last: '9.000000000000000000' } }

describe('stocks — the FOREIGN half', () => {
  it('🔴 a foreign row with no stats is priced from the founding float — the bug', () => {
    const r = normalizeListing({ symbol: 'SYBIL', currency: 'AVT', ipo_price: '5.0',
                                 status: 'trading', origin: 'Registry-A', is_local: false })
    // This is what shipped, and what made the venue answer
    // "price outside ±25% band around 105.1".
    expect(effectivePrice(r)).toEqual({ value: '5', basis: 'ipo' })
  })

  it('…and mergeTickers gives it the LIVE price instead', () => {
    const r = normalizeListing({ symbol: 'SYBIL', currency: 'AVT', ipo_price: '5.0',
                                 status: 'trading', origin: 'Registry-A', is_local: false })
    const [m] = mergeTickers([r], TICKERS)
    expect(m.last).toBe('105.1')
    expect(effectivePrice(m)).toEqual({ value: '105.1', basis: 'last' })
  })

  it('🔴 BSEA is NOT "never traded" — the assertion that ratified the defect', () => {
    const r = normalizeListing({ symbol: 'BSEA', currency: 'JDAY', ipo_price: '1.25',
                                 status: 'trading', origin: 'Frame-B', is_local: false })
    const [m] = mergeTickers([r], TICKERS)
    expect(priceLine(m, 'BVT', RATES)).toContain('27.06')
    expect(priceLine(m, 'BVT', RATES)).not.toContain('never traded')
  })

  it('never lets a cached ticker overwrite a LOCAL live book', () => {
    const local = normalizeListing(SMKD)                      // stats.last = 51
    const [m] = mergeTickers([local], { venues: [{ venue: 'x', listings: [{ symbol: 'SMKD', last: '999' }] }] })
    expect(m.last).toBe('51')
  })

  it('says WHY something cannot be bought, rather than failing on click', () => {
    expect(tradability(normalizeListing(HALTED))).toEqual({ ok: false, reason: 'halted by the market' })
    expect(priceLine(normalizeListing(HALTED), 'BVT', RATES)).toContain('NOT TRADEABLE')
    expect(tradability(normalizeListing(SMKD)).ok).toBe(true)
    const noPrice = normalizeListing({ symbol: 'ZZZ', currency: 'BVT', status: 'trading' })
    expect(tradability(noPrice)).toEqual({ ok: false, reason: 'no price on the book yet' })
  })
})

describe('stocks — what cannot be bought, and why (measured by buying all 19)', () => {
  const foreignNoLive = normalizeListing({ symbol: 'NEKO', currency: 'JDAY', ipo_price: '8.0',
                                           status: 'trading', origin: 'op-newyork', is_local: false })
  it('🔴 refuses to relay a FOSSIL price to a foreign venue', () => {
    // Sending ipo_price got "price outside ±25% band around 134.81" from
    // op-newyork. The refusal names the venue instead.
    const t = tradability(foreignNoLive)
    expect(t.ok).toBe(false)
    expect(t.reason).toContain('op-newyork')
    expect(priceLine(foreignNoLive, 'BVT', RATES)).toContain('NOT TRADEABLE')
  })
  it('…but a foreign row WITH a live ticker price is tradeable', () => {
    const [m] = mergeTickers([normalizeListing({ symbol: 'SYBIL', currency: 'AVT', ipo_price: '5.0',
                                                 status: 'trading', origin: 'Registry-A', is_local: false })], TICKERS)
    expect(tradability(m).ok).toBe(true)
  })
  it('names the per-payment cap rather than failing on click', () => {
    const [m] = mergeTickers([normalizeListing({ symbol: 'SYBIL', currency: 'AVT', ipo_price: '5.0',
                                                 status: 'trading', origin: 'Registry-A', is_local: false })], TICKERS)
    expect(tradability(m, { maxPerTx: 100 })).toEqual({ ok: false, reason: 'above your 100 per-payment cap' })
    expect(tradability(m, { maxPerTx: 600 }).ok).toBe(true)
  })
  it('names an unaffordable listing rather than failing on click', () => {
    const slg = normalizeListing({ symbol: 'SLG', currency: 'BVT', ipo_price: '26.74', status: 'trading',
                                   is_local: true, stats: { last: '1069.60' } })
    expect(tradability(slg, { balance: 1000 })).toEqual({ ok: false, reason: 'costs more than your balance' })
  })
})
