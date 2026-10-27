/** priceAlerts.test.ts — §POCKETBRIDGE3 A4. The session evaluator, pinned to
 * the same semantics as the server watcher. */
import { describe, it, expect } from 'vitest'
import { makeRule, evaluateRule, sweepRules, isExpired } from './priceAlerts'

const NOW = new Date('2026-08-22T12:00:00Z')

describe('makeRule', () => {
  it('captures baseline, uppercases, 24h expiry, unfired', () => {
    const r = makeRule('qcc', 5, 120)
    expect(r.symbol).toBe('QCC')
    expect(r.baseline).toBe(120)
    expect(r.pct).toBe(5)
    expect(r.fired_at).toBeNull()
    expect(Date.parse(r.expires_at) - Date.parse(r.created_at)).toBe(24 * 3600_000)
    expect(r.id.length).toBeGreaterThan(8)
  })
})

describe('evaluateRule', () => {
  const base = () => ({ ...makeRule('QCC', 5, 100), created_at: NOW.toISOString(), expires_at: new Date(NOW.getTime() + 3600_000).toISOString() })
  it('fires up past +pct, down past -pct, silent inside the band', () => {
    expect(evaluateRule(base(), 105.01, NOW)).toBe('up')
    expect(evaluateRule(base(), 94.99, NOW)).toBe('down')
    expect(evaluateRule(base(), 104.9, NOW)).toBeNull()
    expect(evaluateRule(base(), 95.1, NOW)).toBeNull()
    // boundary is inclusive, matching the server (>= / <=)
    expect(evaluateRule(base(), 105, NOW)).toBe('up')
    expect(evaluateRule(base(), 95, NOW)).toBe('down')
  })
  it('skips fired, expired, unpriced, malformed', () => {
    const fired = { ...base(), fired_at: NOW.toISOString() }
    expect(evaluateRule(fired, 200, NOW)).toBeNull()
    const expired = { ...base(), expires_at: new Date(NOW.getTime() - 1000).toISOString() }
    expect(evaluateRule(expired, 200, NOW)).toBeNull()
    expect(isExpired(expired, NOW)).toBe(true)
    expect(evaluateRule(base(), null, NOW)).toBeNull()
    expect(evaluateRule(base(), NaN, NOW)).toBeNull()
    expect(evaluateRule({ ...base(), baseline: 0 }, 200, NOW)).toBeNull()
    expect(evaluateRule({ ...base(), pct: -5 }, 200, NOW)).toBeNull()
  })
})

describe('sweepRules', () => {
  it('fires matching rules once, stamps fired fields, leaves others armed', () => {
    const a = { ...makeRule('QCC', 5, 100), expires_at: new Date(NOW.getTime() + 3600_000).toISOString() }
    const b = { ...makeRule('BLD0', 5, 50), expires_at: new Date(NOW.getTime() + 3600_000).toISOString() }
    const priced: Record<string, number> = { QCC: 106, BLD0: 50.5 }
    const fired = sweepRules([a, b], (s) => priced[s] ?? null, NOW)
    expect(fired.map((r) => r.symbol)).toEqual(['QCC'])
    expect(a.fired_at).toBe(NOW.toISOString())
    expect(a.fired_direction).toBe('up')
    expect(a.fired_price).toBe('106')
    expect(b.fired_at).toBeNull()
    // second sweep: already fired — never double-fires
    expect(sweepRules([a, b], (s) => priced[s] ?? null, NOW)).toEqual([])
  })
  it('venue rules only fire when the lookup can price that venue', () => {
    const v = { ...makeRule('QCC', 5, 100, 'Frame B'), expires_at: new Date(NOW.getTime() + 3600_000).toISOString() }
    expect(sweepRules([v], () => null, NOW)).toEqual([])
    expect(v.fired_at).toBeNull()
    const fired = sweepRules([v], (_s, venue) => (venue === 'Frame B' ? 110 : null), NOW)
    expect(fired.length).toBe(1)
  })
})
