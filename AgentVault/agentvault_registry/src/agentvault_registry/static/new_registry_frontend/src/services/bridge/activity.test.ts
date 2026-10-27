import { describe, it, expect } from 'vitest'
import {
  createActivityIndex, noteActivity, activeDids, coverage,
  windowFromMinutes, activityNote, ACTIVITY_MAX_DIDS,
} from './activity'

const T0 = 1_700_000_000_000

describe('activity index', () => {
  it('records and expires by window', () => {
    const ix = createActivityIndex(T0)
    noteActivity(ix, ['a'], T0)
    noteActivity(ix, ['b'], T0 + 9 * 60_000)
    const at = T0 + 10 * 60_000
    expect([...activeDids(ix, 5 * 60_000, at)]).toEqual(['b'])
    expect([...activeDids(ix, 15 * 60_000, at)].sort()).toEqual(['a', 'b'])
  })

  it('a DID that acts again REAPPEARS', () => {
    const ix = createActivityIndex(T0)
    noteActivity(ix, ['a'], T0)
    const late = T0 + 30 * 60_000
    expect(activeDids(ix, 5 * 60_000, late).has('a')).toBe(false)
    noteActivity(ix, ['a'], late)
    expect(activeDids(ix, 5 * 60_000, late).has('a')).toBe(true)
  })

  it('ignores empty dids', () => {
    const ix = createActivityIndex(T0)
    noteActivity(ix, ['', 'a'], T0)
    expect(ix.seen.size).toBe(1)
  })

  it('caps growth by RECENCY, not insertion order', () => {
    const ix = createActivityIndex(T0)
    // oldest first, then one very old DID re-acts and must survive the cull
    for (let i = 0; i < ACTIVITY_MAX_DIDS + 50; i++) noteActivity(ix, [`d${i}`], T0 + i)
    noteActivity(ix, ['d0'], T0 + 10_000_000)
    expect(ix.seen.size).toBeLessThanOrEqual(ACTIVITY_MAX_DIDS)
    expect(ix.seen.has('d0')).toBe(true)
  })

  it('reports coverage honestly and never claims a window it has not watched', () => {
    const ix = createActivityIndex(T0)
    expect(coverage(ix, 15 * 60_000, T0 + 60_000)).toEqual({ coveredMs: 60_000, full: false })
    expect(coverage(ix, 15 * 60_000, T0 + 20 * 60_000).full).toBe(true)
    const partial = activityNote(ix, 15 * 60_000, T0 + 120_000, 3, 40)
    expect(partial).toContain('3 of 40 active in the last 15m')
    expect(partial).toMatch(/cannot see the whole window yet/)
    expect(activityNote(ix, 15 * 60_000, T0 + 20 * 60_000, 3, 40)).not.toMatch(/cannot see/)
  })

  it('clamps hand-typed minutes', () => {
    expect(windowFromMinutes(0)).toBeNull()
    expect(windowFromMinutes(-5)).toBeNull()
    expect(windowFromMinutes(NaN)).toBeNull()
    expect(windowFromMinutes(15)).toBe(900_000)
    expect(windowFromMinutes(99999)).toBe(24 * 60 * 60_000)
  })
})
