import { describe, expect, it } from 'vitest'
import { LOCK_PRESETS_DAYS, lockOnlyTiers } from './stakingLocks'

describe('stakingLocks', () => {
  it('offers every lock preset the engine knows, flexible first', () => {
    expect([...LOCK_PRESETS_DAYS]).toEqual([0, 30, 90, 180, 365])
    expect(lockOnlyTiers().map((t) => t.lockPeriod)).toEqual([0, 30, 90, 180, 365])
  })
  it('carries no rate at all', () => {
    for (const t of lockOnlyTiers()) {
      expect(t.apy).toBe(0)
      expect(t.lockPremium).toBe(0)
    }
  })
})
