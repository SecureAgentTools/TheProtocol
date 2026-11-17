/**
 * V0666 (the Firms page counts the work of a firm's own agents): the one reading of `member_work` (services/firmCounts.ts).
 * Unknown is not zero; two counts are kept apart; a malformed number never becomes NaN on a page.
 */
import { describe, expect, it } from 'vitest'
import { agentsWork, agentsWorkIsNone } from '@/services/firmCounts'

describe('the firm\'s agents\' work, as the registry states it', () => {
  it('reads delivered and commissioned apart', () => {
    expect(agentsWork({ jobs: 9, commissioned: 4 })).toEqual({ jobs: 9, commissioned: 4 })
  })
  it('an answer that carries nothing is unknown (null), never a zero', () => {
    for (const none of [undefined, null, {}, 'x', 3, [], { other: 1 }]) expect(agentsWork(none), JSON.stringify(none)).toBeNull()
  })
  it('an older registry that answers jobs alone reads commissioned as 0, not unknown', () => {
    expect(agentsWork({ jobs: 3 })).toEqual({ jobs: 3, commissioned: 0 })
  })
  it('a number that is not a count becomes 0, never NaN or a negative on the page', () => {
    expect(agentsWork({ jobs: Number.NaN, commissioned: -2 })).toEqual({ jobs: 0, commissioned: 0 })
    expect(agentsWork({ jobs: 2.9, commissioned: Infinity })).toEqual({ jobs: 2, commissioned: 0 })
  })
  it('an answered zero is none; unknown is not none', () => {
    expect(agentsWorkIsNone(agentsWork({ jobs: 0, commissioned: 0 }))).toBe(true)
    expect(agentsWorkIsNone(agentsWork({ jobs: 0, commissioned: 1 }))).toBe(false)
    expect(agentsWorkIsNone(null)).toBe(false)
  })
})
