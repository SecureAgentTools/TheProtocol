/**
 * §COCKPITUP U5 — the spread is a DISTRIBUTION, and a canary cannot see one.
 *
 * A browser battery can prove the desk still polls; it cannot prove that six panes in the
 * 60s cohort no longer fire together, because observing that needs many mounts and a clock.
 * So the band, the floor and the once-per-mount draw are pinned here, with an injected
 * `rand` so the assertions are exact rather than probabilistic.
 */
import { describe, it, expect, vi } from 'vitest'
import { jitterMs, setJitteredInterval, JITTER_LO, JITTER_HI, MIN_POLL_MS } from '../pollJitter'

describe('pollJitter', () => {
  it('maps the extremes of rand() to the declared band', () => {
    expect(jitterMs(60_000, () => 0)).toBe(Math.round(60_000 * JITTER_LO))   // 51000
    expect(jitterMs(60_000, () => 1)).toBe(Math.round(60_000 * JITTER_HI))   // 69000
  })

  it('never leaves the band for any rand() in [0,1)', () => {
    for (let i = 0; i <= 100; i++) {
      const ms = jitterMs(60_000, () => i / 100)
      expect(ms).toBeGreaterThanOrEqual(60_000 * JITTER_LO)
      expect(ms).toBeLessThanOrEqual(60_000 * JITTER_HI)
    }
  })

  it('actually spreads a cohort — six panes on 60s do not share a deadline', () => {
    // The measured defect: 6 panes, one interval, one burst. With the real RNG the
    // spread must produce a range wide enough to matter (>4s across six draws is the
    // browser leg's own threshold).
    const draws = Array.from({ length: 6 }, () => jitterMs(60_000))
    expect(new Set(draws).size).toBeGreaterThan(1)
    expect(Math.max(...draws) - Math.min(...draws)).toBeGreaterThan(0)
  })

  it('refuses to turn a bad base into a request storm', () => {
    // setInterval(fn, NaN) fires as fast as the browser allows. A non-finite or
    // non-positive base must land on the floor, never on 0 or NaN.
    for (const bad of [NaN, 0, -1, undefined as any, null as any, 'x' as any]) {
      expect(jitterMs(bad)).toBe(MIN_POLL_MS)
    }
  })

  it('never returns below the floor even when the base is tiny', () => {
    expect(jitterMs(10, () => 0)).toBe(MIN_POLL_MS)
  })

  it('draws ONCE per interval, not once per tick', () => {
    // The contract that makes a pane's cadence predictable: setJitteredInterval consumes
    // exactly one random draw and hands a fixed period to setInterval.
    const rand = vi.spyOn(Math, 'random')
    const si = vi.spyOn(globalThis, 'setInterval').mockReturnValue(7 as any)
    try {
      const h = setJitteredInterval(() => {}, 60_000)
      expect(h).toBe(7 as any)
      expect(rand).toHaveBeenCalledTimes(1)
      expect(si).toHaveBeenCalledTimes(1)
      const period = si.mock.calls[0][1] as number
      expect(period).toBeGreaterThanOrEqual(60_000 * JITTER_LO)
      expect(period).toBeLessThanOrEqual(60_000 * JITTER_HI)
    } finally { rand.mockRestore(); si.mockRestore() }
  })
})
