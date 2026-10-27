import { describe, it, expect, vi, beforeEach } from 'vitest'

// The app locale, controlled by the test. `formatNumber` in @/i18n resolves getLocale()
// at CALL time, which is exactly the property under test: the cockpit must follow the
// locale the UI renders in, never the operating system's.
let appLocale = 'en'
vi.mock('@/i18n', () => ({
  formatNumber: (value: number, options?: Intl.NumberFormatOptions) =>
    new Intl.NumberFormat(appLocale, options).format(value),
}))

import { fmt, fmtCount, fmtCompact, fmtAuto, isCompacted, toNum, NO_VALUE } from '../num'

beforeEach(() => { appLocale = 'en' })

describe('cockpit number formatting', () => {
  it('groups an exact figure in the app locale', () => {
    expect(fmt(515473.61)).toBe('515,473.61')
  })

  it('follows the APP locale, not the host — the defect this module exists for', () => {
    // 3,330 refusals rendered as "3.330" on a German OS running the English UI.
    expect(fmtCount(3330)).toBe('3,330')
    appLocale = 'de'
    expect(fmtCount(3330)).toBe('3.330')
    appLocale = 'en'
    expect(fmtCount(3330)).toBe('3,330')
  })

  it('compacts a headline and says so consistently', () => {
    expect(fmtCompact(134985596)).toBe('135M')
    expect(isCompacted(134985596)).toBe(true)
    expect(isCompacted(999)).toBe(false)
  })

  it('fmtAuto compacts only above the threshold', () => {
    expect(fmtAuto(101.06)).toBe('101.06')
    expect(fmtAuto(22100000)).toBe('22.1M')
  })

  it('renders a non-number as a dash, never as zero', () => {
    // §RAT: "0" is a claim about the world; "—" is a claim about our knowledge of it.
    expect(fmt(null)).toBe(NO_VALUE)
    expect(fmt(undefined)).toBe(NO_VALUE)
    expect(fmt('not a number')).toBe(NO_VALUE)
    expect(fmtCount(NaN)).toBe(NO_VALUE)
    expect(fmt(0)).toBe('0')
  })

  it('accepts the scientific notation the TEG answers with', () => {
    expect(toNum('1E+3')).toBe(1000)
    expect(fmt('1E+3', 0)).toBe('1,000')
  })

  it('keeps decimals where money needs them', () => {
    expect(fmt(0.009864, 6)).toBe('0.009864')
    expect(fmt(1.5, 2, 2)).toBe('1.50')
  })
})
