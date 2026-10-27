import { appLocale } from '@/services/appLocale'
// §SUMSPLIT — the formatter's law: never one unit on a mixed sum; the
// single-currency case stays byte-identical to a plain formatted number.
import { describe, it, expect } from 'vitest'
import { sumPerCurrency, formatPerCurrency } from './currencySum'

describe('sumPerCurrency', () => {
  it('splits a mixed fleet per currency', () => {
    const out = sumPerCurrency([
      { amount: 1000, currency: 'AVT' },
      { amount: 204, currency: 'AVT' },
      { amount: '310', currency: 'JDAY' },
      { amount: 12, currency: 'BVT' },
    ])
    expect(out).toEqual([
      { currency: 'AVT', total: 1204 },
      { currency: 'JDAY', total: 310 },
      { currency: 'BVT', total: 12 },
    ])
  })

  it('anchors the local currency first even when smaller', () => {
    const out = sumPerCurrency(
      [{ amount: 5, currency: 'BVT' }, { amount: 9999, currency: 'AVT' }],
      { localCurrency: 'BVT' },
    )
    expect(out.map(t => t.currency)).toEqual(['BVT', 'AVT'])
  })

  it('drops non-numeric amounts instead of flattening them to 0', () => {
    const out = sumPerCurrency([
      { amount: 'not-a-number', currency: 'AVT' },
      { amount: null, currency: 'AVT' },
      { amount: 7, currency: 'AVT' },
    ])
    expect(out).toEqual([{ currency: 'AVT', total: 7 }])
  })

  it('drops entries with no currency unless a fallback is given', () => {
    expect(sumPerCurrency([{ amount: 3, currency: '' }])).toEqual([])
    expect(sumPerCurrency([{ amount: 3, currency: null }], { fallbackCurrency: 'AVT' }))
      .toEqual([{ currency: 'AVT', total: 3 }])
  })

  it('accepts scientific-notation strings (the live balance dialect)', () => {
    expect(sumPerCurrency([{ amount: '1E+3', currency: 'AVT' }]))
      .toEqual([{ currency: 'AVT', total: 1000 }])
  })
})

describe('formatPerCurrency', () => {
  it('renders the mixed line with plus joiners, local first', () => {
    const line = formatPerCurrency(
      [
        { amount: 1204, currency: 'AVT' },
        { amount: 310, currency: 'JDAY' },
        { amount: 12, currency: 'BVT' },
      ],
      { localCurrency: 'BVT', fmt: n => n.toLocaleString(appLocale()) },
    )
    expect(line).toBe('12 BVT + 1,204 AVT + 310 JDAY')
  })

  it('single currency collapses to the single line (the control case)', () => {
    expect(formatPerCurrency([{ amount: 1204, currency: 'AVT' }],
      { fmt: n => n.toLocaleString(appLocale()) })).toBe('1,204 AVT')
  })

  it('empty input renders empty — the caller owns the empty state', () => {
    expect(formatPerCurrency([])).toBe('')
  })

  it('uses the caller\'s formatter verbatim (no rounding policy of its own)', () => {
    expect(formatPerCurrency([{ amount: 1500000, currency: 'AVT' }],
      { fmt: () => '1.5M' })).toBe('1.5M AVT')
  })
})
