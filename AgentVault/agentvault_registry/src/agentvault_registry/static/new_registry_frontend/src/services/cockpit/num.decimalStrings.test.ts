/**
 * The amounts the API sends as str(Decimal) (agentvault2-5b, 2026-10-25, from agentvault2-69's EU gallery, V0638: a v2
 * contract's total_amount "0E-10" printed raw on Contracts' strip, 47 of 50 rows; "2.0000000000" beside them). The
 * strip and the "Contract offered" notice read them through fmt, which takes such a string as the number it is, in the
 * app's locale, and never shows a value it cannot read as 0.
 */
import { describe, expect, it } from 'vitest'
import { fmt, NO_VALUE } from './num'

describe('fmt and the decimal strings the API sends', () => {
  it.each([
    ['0E-10', 4, '0'],
    ['2.0000000000', 4, '2'],
    ['1E+3', 2, '1,000'],
    ['12.34567', 4, '12.3457'],
    ['0.5', 4, '0.5'],
  ])('"%s" at %d places reads %s', (value, dp, want) => {
    expect(fmt(value, dp)).toBe(want)
  })

  it('a value it cannot read is no value, never 0', () => {
    expect(fmt('n/a', 4)).toBe(NO_VALUE)
    expect(fmt(null, 4)).toBe(NO_VALUE)
    expect(fmt('', 4)).toBe(NO_VALUE)
  })
})
