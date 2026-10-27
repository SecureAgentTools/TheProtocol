import { describe, expect, it } from 'vitest'
import { hiddenUntilBonded } from './reputationBond'

describe('hiddenUntilBonded: what discovery shows of an agent, said to its owner', () => {
  it('is hidden on a registry that enforces the bond while the agent holds none', () => {
    for (const status of ['none', 'pending', 'released', 'forfeited', 'voided', undefined]) {
      expect(hiddenUntilBonded({ mode: 'enforce', bond: { status } }), String(status)).toBe(true)
    }
  })

  it('shows once the bond is locked or matured, as services/reputation_bond.sql_card_is_bonded counts it', () => {
    expect(hiddenUntilBonded({ mode: 'enforce', bond: { status: 'locked' } })).toBe(false)
    expect(hiddenUntilBonded({ mode: 'enforce', bond: { status: 'matured' } })).toBe(false)
  })

  it('never hides where the bond is in shadow or off, or when the bond could not be read', () => {
    expect(hiddenUntilBonded({ mode: 'shadow', bond: { status: 'none' } })).toBe(false)
    expect(hiddenUntilBonded({ mode: 'off', bond: { status: 'none' } })).toBe(false)
    expect(hiddenUntilBonded(null)).toBe(false)
  })
})
