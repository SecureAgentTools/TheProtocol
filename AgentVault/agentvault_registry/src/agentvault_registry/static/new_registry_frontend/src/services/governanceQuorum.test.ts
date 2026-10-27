import { describe, it, expect } from 'vitest'
import { failureReason, proposalUnit, quorumMarkerLeft, requiredPower, storedQuorumRequired } from './governanceQuorum'

/** §BATCH0911 item 2b — see governanceQuorum.ts. Both directions: a stored value is drawn as
 *  stored, and an absent one draws nothing rather than a literal. */
describe('the quorum line and the required figure follow the stored quorum', () => {
  it('draws the line at the stored quorum and caps it at the bar', () => {
    expect(quorumMarkerLeft(20)).toBe(20)
    expect(quorumMarkerLeft(0)).toBe(0)
    expect(quorumMarkerLeft(150)).toBe(100)
  })

  it('draws no line when no quorum is stored', () => {
    expect(quorumMarkerLeft(null)).toBeNull()
    expect(quorumMarkerLeft(undefined)).toBeNull()
  })

  it('computes the required power from the stored quorum', () => {
    expect(requiredPower('1000', 10)).toBe(100)
    expect(requiredPower('333.33', 20)).toBe(66.67)
  })

  it('has no required figure when the quorum or the network power is unknown', () => {
    expect(requiredPower('1000', null)).toBeNull()
    for (const np of ['0', '', undefined, null, 'NaN', '-5']) {
      expect(requiredPower(np, 10)).toBeNull()
    }
  })
})

describe('§MEMBERSHIP: a decided proposal keeps the numbers it was decided on', () => {
  it('its figures are in the unit its tally stored, whatever the registry runs today', () => {
    expect(proposalUnit({ tallyWeightMode: 'lock' }, true)).toBe('lock')          // decided by locked units, now members
    expect(proposalUnit({ tallyWeightMode: 'member' }, false)).toBe('member')
  })

  it('an open proposal, or one tallied before the numbers were stored, takes the registry\'s mode now', () => {
    expect(proposalUnit({ tallyWeightMode: null }, true)).toBe('member')
    expect(proposalUnit({}, false)).toBe('lock')
  })

  it('the stored quorum is used only where the tally stored it, with its unit', () => {
    expect(storedQuorumRequired({ tallyWeightMode: 'member', tallyQuorumRequired: 492.8 })).toBe(492.8)
    expect(storedQuorumRequired({ tallyWeightMode: 'member', tallyQuorumRequired: 0 })).toBe(0)        // a real value
    expect(storedQuorumRequired({ tallyWeightMode: null, tallyQuorumRequired: 492.8 })).toBeNull()     // no unit: no claim
    expect(storedQuorumRequired({ tallyWeightMode: 'lock', tallyQuorumRequired: null })).toBeNull()
    expect(storedQuorumRequired({})).toBeNull()
  })
})

describe('§MEMBERSHIP: why a decided proposal failed, as its tally stored it', () => {
  it('quorum not met, or the majority against', () => {
    expect(failureReason({ status: 'failed', tallyQuorumMet: false })).toBe('quorum_not_met')
    expect(failureReason({ status: 'FAILED', tallyQuorumMet: true })).toBe('majority_against')
  })

  it('control: no reason is claimed where the tally stored none, nor for any other status', () => {
    expect(failureReason({ status: 'failed', tallyQuorumMet: null })).toBeNull()      // tallied before 0185
    expect(failureReason({ status: 'failed' })).toBeNull()
    expect(failureReason({ status: 'passed', tallyQuorumMet: true })).toBeNull()
    expect(failureReason({ status: 'rejected', tallyQuorumMet: false })).toBeNull()
    expect(failureReason({ status: 'voting', tallyQuorumMet: false })).toBeNull()
  })
})
