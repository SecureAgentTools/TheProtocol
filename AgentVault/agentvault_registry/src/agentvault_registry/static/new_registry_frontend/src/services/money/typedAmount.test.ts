import { describe, expect, it } from 'vitest'
import { AMOUNT_PLACES, typedAmount } from './typedAmount'

describe('typedAmount', () => {
  it('takes plain amounts and normalises them', () => {
    expect(typedAmount('5')).toBe('5')
    expect(typedAmount(' 1.5 ')).toBe('1.5')
    expect(typedAmount('0.25')).toBe('0.25')
    expect(typedAmount('.5')).toBe('0.5')
    expect(typedAmount('007')).toBe('7')
    expect(typedAmount(2)).toBe('2')
  })
  it('reads a single comma as the decimal separator', () => {
    expect(typedAmount('1,5')).toBe('1.5')
    expect(typedAmount('1,000.5')).toBeNull()  // a thousands separator is not guessed at
    expect(typedAmount('1,2,3')).toBeNull()
  })
  it('refuses what Number() and parseFloat() wave through', () => {
    for (const bad of ['', '   ', '0', '0.0', '-1', '+1', 'abc', '1abc', '1e3', '1e309', '0x10', 'Infinity', 'NaN', '1.2.3', '.', ','])
      expect(typedAmount(bad), JSON.stringify(bad)).toBeNull()
    expect(typedAmount(null)).toBeNull()
    expect(typedAmount(undefined)).toBeNull()
  })
  it('holds the ledger precision', () => {
    expect(typedAmount('0.' + '1'.repeat(AMOUNT_PLACES))).toBe('0.' + '1'.repeat(AMOUNT_PLACES))
    expect(typedAmount('0.' + '1'.repeat(AMOUNT_PLACES + 1))).toBeNull()
    expect(typedAmount('9'.repeat(400))).toBeNull()  // finite as text, Infinity as a number
  })
})
