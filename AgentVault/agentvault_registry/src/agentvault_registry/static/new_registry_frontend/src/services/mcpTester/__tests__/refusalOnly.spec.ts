import { describe, it, expect } from 'vitest'
import { readRefusalOnly, isRefusalOnly } from '../runReading'
import en from '@/i18n/locales/en.json'

/**
 * §MCPTEST30 (V0636): a tool whose only pass in a run was a refusal counts as not measured (the router moves the row
 * to the not-measured class, routers/mcp_tester._apply_refusal_only). The page reads how many it moved and what the
 * target itself counted; a run before V0636 carries neither key and shows nothing.
 */
function lookup(obj: Record<string, unknown>, dotted: string): unknown {
  return dotted.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), obj)
}

describe('readRefusalOnly', () => {
  it('reads the count and the target\'s own rate', () => {
    expect(readRefusalOnly({ refusal_only: 192, target_counts: { passed: 1188, skipped: 34, pass_pct: 95.65 } }))
      .toEqual({ n: 192, targetPct: 95.65 })
  })
  it('keeps the count when the target\'s rate cannot be read', () => {
    expect(readRefusalOnly({ refusal_only: 3, target_counts: null })).toEqual({ n: 3, targetPct: null })
    expect(readRefusalOnly({ refusal_only: 3, target_counts: [95] })).toEqual({ n: 3, targetPct: null })
    expect(readRefusalOnly({ refusal_only: 3, target_counts: { pass_pct: 'x' } })).toEqual({ n: 3, targetPct: null })
  })
  it('shows nothing for a run before V0636, a run that moved none, or a value that is not a count', () => {
    expect(readRefusalOnly(null)).toBeNull()
    expect(readRefusalOnly({})).toBeNull()
    expect(readRefusalOnly({ refusal_only: 0, target_counts: { pass_pct: 100 } })).toBeNull()
    expect(readRefusalOnly({ refusal_only: -1 })).toBeNull()
    expect(readRefusalOnly({ refusal_only: Number.NaN })).toBeNull()
    expect(readRefusalOnly({ refusal_only: '5' })).toBeNull()
  })
})

describe('isRefusalOnly', () => {
  it('is true only for a row the router moved', () => {
    expect(isRefusalOnly({ refusal_only: true })).toBe(true)
    expect(isRefusalOnly({ refusal_only: false })).toBe(false)
    expect(isRefusalOnly({ refusal_only: null })).toBe(false)
    expect(isRefusalOnly({})).toBe(false)
  })
})

describe('the words the page asks for', () => {
  it('are in the English bundle', () => {
    for (const k of ['mcpTester.outcome.refusalOnly', 'mcpTester.outcome.refusalOnlyTip', 'mcpTester.pass.tipRefusalOnly',
      'mcpTester.pass.tipRefusalOnlyPct']) {
      expect(typeof lookup(en as Record<string, unknown>, k), k).toBe('string')
    }
  })
})
