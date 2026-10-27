import { describe, it, expect } from 'vitest'
import {
  governanceMode, presenceMode, commonsEnabled, weightLabel, memberVoteFigure, tenureProgress, parseStepUp, secondsLeft,
} from './membership'

/**
 * §MEMBERSHIP (2026-10-02) — the readers every membership surface goes through. The rule they hold: a registry that
 * has not switched to member mode renders exactly as today, so an absent or unknown switch is TODAY's value.
 */
describe('the mode readers default to today', () => {
  it('absent, unknown and lock read as lock; only "member" is member mode', () => {
    expect(governanceMode(undefined)).toBe('lock')
    expect(governanceMode({})).toBe('lock')
    expect(governanceMode({ governance_weight_mode: 'lock' })).toBe('lock')
    expect(governanceMode({ governance_weight_mode: 'Member' as any })).toBe('lock')
    expect(governanceMode({ governance_weight_mode: 'member' })).toBe('member')
  })

  it('presence mode is off unless the registry names conditional or required', () => {
    expect(presenceMode(null)).toBe('off')
    expect(presenceMode({ governance_presence_mode: 'sometimes' as any })).toBe('off')
    expect(presenceMode({ governance_presence_mode: 'conditional' })).toBe('conditional')
    expect(presenceMode({ governance_presence_mode: 'required' })).toBe('required')
  })

  it('the commons exist only where the registry says true', () => {
    expect(commonsEnabled(undefined)).toBe(false)
    expect(commonsEnabled({ commons_enabled: 'true' as any })).toBe(false)
    expect(commonsEnabled({ commons_enabled: true })).toBe(true)
  })
})

describe('weight and tenure', () => {
  it('prints the weight with two decimals and never NaN', () => {
    expect(weightLabel(1.3698)).toBe('1.37')
    expect(weightLabel(2)).toBe('2.00')
    // member-mode vote totals are points on the ledger and weights on the floor
    expect(memberVoteFigure('108', 100)).toBe('1.08')
    expect(memberVoteFigure(492.8, 100)).toBe('4.93')
    expect(memberVoteFigure(4928, 100, 'de')).toBe('49,28')
    expect(memberVoteFigure(150, null)).toBe('1.50')                     // the default points per weight
    expect(memberVoteFigure(undefined, 100)).toBe('0.00')
    expect(memberVoteFigure('n/a', 100)).toBe('0.00')
    expect(weightLabel(Number.NaN)).toBe('0.00')
    expect(weightLabel(undefined)).toBe('0.00')
  })

  it('prints the weight in the reader\'s locale', () => {
    expect(weightLabel(1.3698, 'de')).toBe('1,37')
    expect(weightLabel(2, 'en')).toBe('2.00')
  })

  it('tenure grows from 0 to 1 over the full period and stops there', () => {
    expect(tenureProgress(0, 365)).toBe(0)
    expect(tenureProgress(73, 365)).toBeCloseTo(0.2)
    expect(tenureProgress(900, 365)).toBe(1)
    expect(tenureProgress(10, 0)).toBe(1)
  })
})

const STEP_UP = {
  error: 'step_up_required',
  message: 'Confirm this vote on your phone.',
  presence_mode: 'conditional',
  step_up: {
    reason: 'governance_vote', challenge_id: 'ch_123', challenge_hash: 'ab'.repeat(32),
    facts: { kind: 'governance.vote', proposal_id: 7, proposal_title: 'Lower the transfer fee', choice: 'for', weight: '1.37' },
    expires_at: '2026-10-02T12:02:00Z', ttl_seconds: 120, methods: ['device', 'totp', 42], how: 'Open Pocket, Approvals.',
  },
}

describe('the 428 step-up body', () => {
  it('is read into a typed challenge, keeping only string methods', () => {
    const ch = parseStepUp(STEP_UP)!
    expect(ch.challengeId).toBe('ch_123')
    expect(ch.facts.proposal_title).toBe('Lower the transfer fee')
    expect(ch.methods).toEqual(['device', 'totp'])
    expect(ch.ttlSeconds).toBe(120)
  })

  it('control: another error, or a body without a challenge id, is not a step-up', () => {
    expect(parseStepUp({ ...STEP_UP, error: 'not_a_member' })).toBeNull()
    expect(parseStepUp({ error: 'step_up_required', step_up: { challenge_hash: 'x' } })).toBeNull()
    expect(parseStepUp('step_up_required')).toBeNull()
    expect(parseStepUp(null)).toBeNull()
  })

  it('counts down from expires_at, falls back to the ttl, and never goes below zero', () => {
    const ch = parseStepUp(STEP_UP)!
    expect(secondsLeft(ch, Date.parse('2026-10-02T12:00:00Z'))).toBe(120)
    expect(secondsLeft(ch, Date.parse('2026-10-02T12:05:00Z'))).toBe(0)
    const noExpiry = { ...ch, expiresAt: null }
    expect(secondsLeft(noExpiry, 50_000, 20_000)).toBe(90)
    expect(secondsLeft({ ...noExpiry, ttlSeconds: null }, 50_000, 20_000)).toBe(0)
  })
})
