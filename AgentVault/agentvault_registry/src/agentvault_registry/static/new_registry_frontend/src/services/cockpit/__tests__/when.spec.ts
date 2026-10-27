/** §COCKPITDESK (2026-10-15) — the shared short form for "how long ago" and "how long until". */
import { describe, expect, it } from 'vitest'
import { agoShort, shortSpan, untilShort } from '../when'

const NOW = Date.UTC(2026, 9, 15, 1, 0, 0)

describe('the short span', () => {
  it('steps from seconds to minutes to hours to days', () => {
    expect(shortSpan(45)).toBe('45s')
    expect(shortSpan(89)).toBe('89s')
    expect(shortSpan(90)).toBe('2m')
    expect(shortSpan(5399)).toBe('90m')
    expect(shortSpan(5400)).toBe('2h')
    expect(shortSpan(172799)).toBe('48h')
    expect(shortSpan(172800)).toBe('2d')
    expect(shortSpan(-5)).toBe('0s')
  })
})

describe('ago and until', () => {
  it('reads an ISO time, an epoch and nothing', () => {
    expect(agoShort(new Date(NOW - 3 * 3600_000).toISOString(), NOW)).toBe('3h')
    expect(agoShort(NOW - 30_000, NOW)).toBe('30s')
    expect(agoShort(null, NOW)).toBe('')
    expect(agoShort('not a time', NOW)).toBe('')
  })

  it('says how long until, and that a time has passed rather than a negative span', () => {
    expect(untilShort(NOW + 2 * 3600_000, NOW)).toEqual({ span: '2h', past: false })
    expect(untilShort(NOW - 2 * 3600_000, NOW)).toEqual({ span: '2h', past: true })
    expect(untilShort(NOW, NOW)).toEqual({ span: '0s', past: true })
    expect(untilShort(undefined, NOW)).toBeNull()
  })
})
