/**
 * V0663, governed code, first slice (order gwo_58327a76b7e3ecf63140eb79): how the console reads a code change's record
 * (GET /code-changes/{id}): its state in words, and the one next step, named for whoever has to take it. The record is
 * the registry's (services/code_changes); this only words it, never decides it.
 * Red on a8f2c1923: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { nextStep, stateWord, canReview, canOpenBallot } from './codeChangeView'

const t = (_k: string, f: string, p?: Record<string, unknown>) =>
  p ? f.replace(/\{(\w+)\}/g, (_, k) => String(p[k] ?? '')) : f
const base = { id: 'cc_1', state: 'proposed', mode: 'bounty', order_id: 'gwo_1', commit: null, proposer_did: 'did:a:me',
  proposal_id: null, acceptance: null, review_verdict: { approvals: 0, needed: 1, blockers: [], ok: false },
  veto_window_closes_at: null, merged: null, veto: null, go: null }

describe('a code change in words', () => {
  it('names each state', () => {
    for (const s of ['proposed', 'accepted', 'balloting', 'passed', 'failed', 'vetoed', 'merged', 'withdrawn']) {
      expect(stateWord(s, t)).not.toBe(s)
    }
    expect(stateWord('something-new', t)).toBe('something-new')
  })

  it('a bounty waits for its delivery, then its checks', () => {
    expect(nextStep(base, t)).toMatch(/delivery/)
    const failed = { ...base, acceptance: { ok: false, reasons: ['CI is not green on the tip (failure)'] } }
    expect(nextStep(failed, t)).toMatch(/CI is not green/)
  })

  it('an accepted change needs its reviews, then its ballot', () => {
    const acc = { ...base, state: 'accepted', commit: 'a'.repeat(40) }
    expect(nextStep(acc, t)).toBe('Needs 1 more independent approval of the checked commit before its ballot.')
    expect(nextStep({ ...acc, review_verdict: { approvals: 0, needed: 2, blockers: [], ok: false } }, t)).toBe('Needs 2 more independent approvals of the checked commit before its ballot.')   // plural said plainly, no "approval(s)"
    const held = { ...acc, review_verdict: { approvals: 1, needed: 1, blockers: [8], ok: false } }
    expect(nextStep(held, t)).toMatch(/asks for changes/)
    expect(nextStep({ ...acc, review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true } }, t)).toMatch(/ballot/)
  })

  it('a passed change waits for the veto window or the go, then its merge', () => {
    const passed = { ...base, state: 'passed', commit: 'a'.repeat(40), proposal_id: 3,
      veto_window_closes_at: '2026-11-15T01:00:00+00:00' }
    expect(nextStep(passed, t, new Date('2026-11-14T12:00:00Z'))).toMatch(/veto window/)
    expect(nextStep(passed, t, new Date('2026-11-16T00:00:00Z'))).toMatch(/merge/)
    expect(nextStep({ ...passed, go: { by: 1 } }, t, new Date('2026-11-14T12:00:00Z'))).toMatch(/merge/)
  })

  it('a closed change says how it ended', () => {
    expect(nextStep({ ...base, state: 'merged', merged: { commit: 'a'.repeat(40), into: 'v0663/cut' } }, t)).toMatch(/v0663\/cut/)
    expect(nextStep({ ...base, state: 'vetoed', veto: { reason: 'not now' } }, t)).toMatch(/not now/)
    expect(nextStep({ ...base, state: 'failed' }, t)).toMatch(/did not pass/)
  })
})

describe('who may act', () => {
  const acc = { ...base, state: 'accepted', commit: 'a'.repeat(40) }

  it('a signed-in person reviews an accepted change; the server decides independence and membership', () => {
    expect(canReview(acc, true)).toBe(true)
    expect(canReview(acc, false)).toBe(false)
    expect(canReview({ ...acc, state: 'balloting' }, true)).toBe(false)
  })

  it('the proposer opens the ballot once the reviews are in', () => {
    const ready = { ...acc, review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true } }
    expect(canOpenBallot(ready, 'did:a:me')).toBe(true)
    expect(canOpenBallot(ready, 'did:a:other')).toBe(false)
    expect(canOpenBallot(acc, 'did:a:me')).toBe(false)
  })
})
