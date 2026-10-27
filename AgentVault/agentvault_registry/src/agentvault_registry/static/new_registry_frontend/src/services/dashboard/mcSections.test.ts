import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { isSectionOpen, setSectionOpen, readSections, MC_SECTIONS_KEY } from './mcSections'

class FakeStorage {
  m = new Map<string, string>()
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null }
  setItem(k: string, v: string) { this.m.set(k, String(v)) }
  removeItem(k: string) { this.m.delete(k) }
}
// vitest 5's happy-dom exposes localStorage as a getter ("Cannot set property localStorage ... which has only a getter"):
// the fake goes in through vi.stubGlobal, which redefines the property, and comes out after each test.
beforeEach(() => { vi.stubGlobal('localStorage', new FakeStorage()) })
afterEach(() => { vi.unstubAllGlobals() })

describe('§MCFOLD mcSections — folded by default, remembered per strip', () => {
  it('every strip starts FOLDED', () => {
    for (const id of ['tape', 'listings', 'ledger']) expect(isSectionOpen(id)).toBe(false)
  })
  it('opening one strip does not open the others', () => {
    setSectionOpen('ledger', true)
    expect(isSectionOpen('ledger')).toBe(true)
    expect(isSectionOpen('tape')).toBe(false)
    expect(readSections()).toEqual({ ledger: '1' })
  })
  it('folding again is remembered as an explicit choice', () => {
    setSectionOpen('tape', true); setSectionOpen('tape', false)
    expect(isSectionOpen('tape', true)).toBe(false)
  })
  it('garbage in the key is treated as no choice', () => {
    localStorage.setItem(MC_SECTIONS_KEY, '[1,2]')
    expect(isSectionOpen('ledger')).toBe(false)
    localStorage.setItem(MC_SECTIONS_KEY, '{not json')
    expect(isSectionOpen('ledger', true)).toBe(true)
  })
})
