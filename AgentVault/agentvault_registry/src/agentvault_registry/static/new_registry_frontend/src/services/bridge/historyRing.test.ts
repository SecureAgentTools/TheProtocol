import { describe, it, expect } from 'vitest'
import { createHistoryRing, DEFAULT_RING_CAP } from './historyRing'

describe('historyRing', () => {
  it('keeps newest first across batches', () => {
    const r = createHistoryRing<number>(10)
    r.push([1, 2, 3])
    r.push([4, 5])
    expect(r.all()).toEqual([5, 4, 3, 2, 1])
  })

  it('bounds itself at cap and COUNTS what it dropped', () => {
    const r = createHistoryRing<number>(3)
    r.push([1, 2, 3, 4, 5])
    expect(r.size()).toBe(3)
    expect(r.all()).toEqual([5, 4, 3])
    // The honesty requirement: a panel must be able to say what it forgot.
    expect(r.dropped()).toBe(2)
  })

  it('windows without copying the whole ring', () => {
    const r = createHistoryRing<number>(100)
    r.push(Array.from({ length: 50 }, (_, i) => i)) // 49 is newest
    expect(r.window(3)).toEqual([49, 48, 47])
    expect(r.window(3, 10)).toEqual([39, 38, 37])
    expect(r.window(5, 48)).toEqual([1, 0])
    expect(r.window(0)).toEqual([])
  })

  it('a window can never exceed what was asked for — the DOM bound', () => {
    const r = createHistoryRing<number>(2000)
    for (let b = 0; b < 40; b++) r.push(Array.from({ length: 100 }, (_, i) => b * 100 + i))
    expect(r.size()).toBe(2000)
    // 4,000 pushed, ring holds 2,000, and a panel rendering 14 still gets 14.
    expect(r.window(14).length).toBe(14)
    expect(r.dropped()).toBe(2000)
  })

  it('push([]) is a no-op and does not disturb order', () => {
    const r = createHistoryRing<number>(5)
    r.push([1, 2])
    r.push([])
    expect(r.all()).toEqual([2, 1])
  })

  it('clear resets the drop counter too', () => {
    const r = createHistoryRing<number>(2)
    r.push([1, 2, 3])
    expect(r.dropped()).toBe(1)
    r.clear()
    expect(r.size()).toBe(0)
    expect(r.dropped()).toBe(0)
  })

  it('an absurd cap falls back to the default rather than throwing', () => {
    expect(createHistoryRing<number>(0).cap).toBe(DEFAULT_RING_CAP)
    expect(createHistoryRing<number>(Number.NaN).cap).toBe(DEFAULT_RING_CAP)
  })
})
