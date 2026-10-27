import { describe, it, expect } from 'vitest'
import { readPassDepth, PASS_DEPTH_ORDER, PASS_DEPTH_TEXT } from '../passDepth'
import en from '@/i18n/locales/en.json'
import de from '@/i18n/locales/de.json'

describe('§MCPTEST30 V0549: how deep a run\'s passes were checked', () => {
  it('reads round 15\'s strict run: 474 of 705 passes against a written contract, the four kinds in order', () => {
    const d = readPassDepth({ success_contract: 374, success_default: 132, refusal_contract: 100, refusal_default: 99 })
    expect(d).not.toBeNull()
    expect(d!.total).toBe(705)
    expect(d!.contract).toBe(474)
    expect(d!.parts.map((p) => [p.key, p.n])).toEqual([
      ['success_contract', 374], ['success_default', 132], ['refusal_contract', 100], ['refusal_default', 99]])
  })

  it('keeps the order fixed whatever order the summary lists the keys in', () => {
    const d = readPassDepth({ refusal_default: 4, refusal_contract: 3, success_default: 2, success_contract: 1 })
    expect(d!.parts.map((p) => p.key)).toEqual([...PASS_DEPTH_ORDER])
  })

  it('shows nothing for a run before V0549, never four zeros', () => {
    expect(readPassDepth(undefined)).toBeNull()
    expect(readPassDepth(null)).toBeNull()
    // a run with no passing tool rows (a federation run) has nothing to break down
    expect(readPassDepth({ success_contract: 0, success_default: 0, refusal_contract: 0, refusal_default: 0 })).toBeNull()
  })

  it('refuses a value that is not four non-negative counts rather than guessing', () => {
    expect(readPassDepth({ success_contract: 1, success_default: 2, refusal_contract: 3 })).toBeNull()
    expect(readPassDepth({ success_contract: 1, success_default: '2', refusal_contract: 3, refusal_default: 4 })).toBeNull()
    expect(readPassDepth({ success_contract: -1, success_default: 2, refusal_contract: 3, refusal_default: 4 })).toBeNull()
    expect(readPassDepth({ success_contract: NaN, success_default: 2, refusal_contract: 3, refusal_default: 4 })).toBeNull()
    expect(readPassDepth([374, 132, 100, 99])).toBeNull()
    expect(readPassDepth('374/132/100/99')).toBeNull()
  })

  it('says every kind in English and German, from the key the page asks for', () => {
    const lookup = (bundle: Record<string, unknown>, key: string): unknown =>
      key.split('.').reduce<unknown>((o, k) => (o && typeof o === 'object' ? (o as Record<string, unknown>)[k] : undefined), bundle)
    for (const k of PASS_DEPTH_ORDER) {
      const { key, fallback } = PASS_DEPTH_TEXT[k]
      expect(lookup(en as Record<string, unknown>, key)).toBe(fallback)
      expect(typeof lookup(de as Record<string, unknown>, key)).toBe('string')
      expect(lookup(de as Record<string, unknown>, key)).not.toBe(fallback)
    }
    expect(typeof lookup(en as Record<string, unknown>, 'mcpTester.depth.summary')).toBe('string')
    expect(typeof lookup(de as Record<string, unknown>, 'mcpTester.depth.summary')).toBe('string')
  })
})
