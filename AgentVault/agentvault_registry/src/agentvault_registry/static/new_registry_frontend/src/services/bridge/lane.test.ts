// @vitest-environment node
import { describe, it, expect } from 'vitest'
import { laneBrightness, LANE_DECAY_MS } from './lane'

describe('learned lane brightness (§BRIDGE R8)', () => {
  it('is brightest the moment the lane is used', () => {
    const fresh = laneBrightness(0, 50)
    expect(fresh).toBeGreaterThan(0.9)
    expect(fresh).toBeLessThanOrEqual(1)
  })

  it('DECAYS with age — the whole point, and the thing the live probe could not show', () => {
    const hits = 20
    const t0 = laneBrightness(0, hits)
    const t1 = laneBrightness(LANE_DECAY_MS * 0.25, hits)
    const t2 = laneBrightness(LANE_DECAY_MS * 0.5, hits)
    const t3 = laneBrightness(LANE_DECAY_MS * 0.9, hits)
    expect(t1).toBeLessThan(t0)
    expect(t2).toBeLessThan(t1)
    expect(t3).toBeLessThan(t2)
  })

  it('reaches exactly zero at expiry, and stays there', () => {
    expect(laneBrightness(LANE_DECAY_MS, 100)).toBe(0)
    expect(laneBrightness(LANE_DECAY_MS * 3, 100)).toBe(0)
  })

  it('never leaves [0,1], whatever it is handed', () => {
    for (const [age, hits] of [[-5000, 0], [0, 0], [0, 1e6], [1e9, 1e6], [1, -3]] as const) {
      const b = laneBrightness(age, hits)
      expect(b).toBeGreaterThanOrEqual(0)
      expect(b).toBeLessThanOrEqual(1)
    }
  })

  it('a busier corridor is brighter than a quiet one of the same age', () => {
    expect(laneBrightness(1000, 40)).toBeGreaterThan(laneBrightness(1000, 4))
  })

  it('but age beats traffic: a stale busy lane is dimmer than a fresh quiet one', () => {
    expect(laneBrightness(LANE_DECAY_MS * 0.95, 1000)).toBeLessThan(laneBrightness(0, 4))
  })
})
