import { describe, expect, it } from 'vitest'
import { lockSentence, stakingOpen, stakingTabShown } from './stakingTab'

// §MEMBERSHIP (V0564): production in member mode with staking off must not say a lock gives weight, and must keep the
// door to unstake for whoever still holds a position.
describe('the Senate floor staking tab', () => {
  it('opens new positions only where the registry says true (fail-closed)', () => {
    expect(stakingOpen({ staking_enabled: true } as never)).toBe(true)
    expect(stakingOpen({ staking_enabled: false } as never)).toBe(false)
    expect(stakingOpen({} as never)).toBe(false)
    expect(stakingOpen(null)).toBe(false)
  })
  it('exists where positions open, or where the person still holds some to unstake', () => {
    expect(stakingTabShown({ staking_enabled: true } as never, 0)).toBe(true)
    expect(stakingTabShown({ staking_enabled: false } as never, 0)).toBe(false)
    expect(stakingTabShown({ staking_enabled: false } as never, 2)).toBe(true)
    expect(stakingTabShown(undefined, 0)).toBe(false)
  })
  it('never says a lock gives voting weight where the registry votes by membership', () => {
    expect(lockSentence({ governance_weight_mode: 'member' } as never)).toBe('no_weight_member')
    expect(lockSentence({ governance_weight_mode: 'lock' } as never)).toBe('gives_weight')
    expect(lockSentence({} as never)).toBe('gives_weight')
  })
})
