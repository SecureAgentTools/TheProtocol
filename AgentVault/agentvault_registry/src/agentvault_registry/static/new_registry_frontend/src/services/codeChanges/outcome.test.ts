import { describe, it, expect } from 'vitest'
import { outcomeWords, stepper, timeline } from './flow'
import { CONSOLE_PREFIX } from './pathRules'

/** V0668 (order gwo_2d51e1af1b2a21a0bcdff5e7): a change's record says WHY its ballot did not pass and WHEN it was tallied, from the
 *  registry's `ballot_outcome` (services/code_changes.ballot_outcome and line_ballot_outcome). Found on journal 55's hero: the page read
 *  DID NOT PASS beside "300 for, 0 against · 3 voted", and "What happened" dated the failure at the ballot's opening. */
const t = (_k: string, fb: string, p?: Record<string, unknown>) => fb.replace(/\{(\w+)\}/g, (_m, k) => String(p?.[k] ?? ''))
const TALLIED = '2026-11-17T09:26:15Z'
const OPENED = '2026-11-16T09:25:00Z'
const QUORUM = { status: 'FAILED', reason: 'quorum_not_met', unit: 'member', took_part: 300, required: 330.6, quorum_percent: 10, for: 300, against: 0,
  share_for: 100, pass_percent: 50, pass_rule: null, tallied_at: TALLIED, ended_at: '2026-11-17T09:25:00Z', sentence: 's' }
const REJECTED = { ...QUORUM, reason: 'rejected', took_part: 300, for: 100, against: 200, share_for: 33.3 }
const rec = (o: Record<string, any> = {}) => ({ id: 'cc_1', state: 'failed', mode: 'branch', title: 'T', paths: [CONSOLE_PREFIX + 'views/X.vue'],
  proposer_did: 'did:a:p', created_at: '2026-11-14T10:00:00Z', updated_at: OPENED, proposal_id: 12, acceptance: { ok: true }, reviews: [],
  review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true }, ...o })

describe('why a ballot did not pass, in words', () => {
  it('a missed quorum names the weight that took part and the weight required, in the ballot\'s unit', () => {
    expect(outcomeWords(QUORUM, t)).toBe('The quorum was not met: 300 of the 330.6 members\' points required took part (quorum 10%).')
    expect(outcomeWords({ ...QUORUM, unit: 'lock' }, t)).toBe('The quorum was not met: 300 of the 330.6 voting power required took part (quorum 10%).')
  })
  it('a rejection names the share in favour against the pass rule', () => {
    expect(outcomeWords(REJECTED, t)).toBe('The members decided against it: 33.3% in favour, 50% needed to pass.')
  })
  it('a line\'s ballot speaks of its deciders and its simple majority', () => {
    const line = { status: 'FAILED', unit: 'deciders', quorum_percent: 50, pass_rule: 'simple', pass_percent: null, tallied_at: TALLIED }
    expect(outcomeWords({ ...line, reason: 'quorum_not_met', took_part: 1, required: 2, for: 1, against: 0, share_for: 100 }, t))
      .toBe('The quorum was not met: 1 of the 2 deciders required voted (quorum 50%).')
    expect(outcomeWords({ ...line, reason: 'rejected', took_part: 3, required: 2, for: 1, against: 2, share_for: 33.3 }, t))
      .toBe('The deciders decided against it: 1 for, 2 against (more for than against is needed).')
    expect(outcomeWords({ ...line, reason: 'no_deciders', took_part: 0, required: null, for: 0, against: 0, share_for: null }, t))
      .toBe('Nobody decided: the line had no deciders at the close.')
  })
  it('a pass says its share and that the quorum was met; a tally that kept no reason claims none', () => {
    expect(outcomeWords({ ...QUORUM, status: 'PASSED', reason: 'passed', for: 400, took_part: 400, share_for: 100 }, t)).toBe('Passed: 100% in favour, the quorum met.')
    expect(outcomeWords({ ...QUORUM, reason: 'unknown', tallied_at: null }, t)).toBe('The tally kept no reason (it ran before the registry stored one).')
  })
  it('nothing to say without an outcome', () => {
    expect(outcomeWords(null, t)).toBe('')
    expect(outcomeWords(undefined, t)).toBe('')
  })
})

describe('the record\'s timeline and stepper', () => {
  it('dates the failure by the tally, not by the ballot\'s opening, and says why under it', () => {
    const f = timeline(rec({ ballot_outcome: QUORUM }), t).find((e) => e.key === 'failed')!
    expect(f.at).toBe(TALLIED)
    expect(f.detail).toContain('300 of the 330.6 members\' points required took part')
  })
  it('a tally that kept no time falls back to the ballot\'s end, then to the record\'s time', () => {
    expect(timeline(rec({ ballot_outcome: { ...QUORUM, reason: 'unknown', tallied_at: null } }), t).find((e) => e.key === 'failed')!.at).toBe('2026-11-17T09:25:00Z')
    expect(timeline(rec(), t).find((e) => e.key === 'failed')!.at).toBe(OPENED)
  })
  it('the maintainer\'s go keeps the ballot\'s own line, dated and explained', () => {
    const ev = timeline(rec({ state: 'passed', ballot_outcome: QUORUM, passed_at: '2026-11-17T10:00:00Z',
      bootstrap: { at: '2026-11-17T10:00:00Z', members: 3, threshold: 10, voted: [] } }), t)
    const f = ev.find((e) => e.key === 'failed')!
    expect(f.at).toBe(TALLIED); expect(f.detail).toContain('330.6')
  })
  it('the stopped step says why the ballot did not pass', () => {
    expect(stepper(rec({ ballot_outcome: QUORUM }), t)[3].note).toBe('The ballot did not pass: it missed its quorum.')
    expect(stepper(rec({ ballot_outcome: REJECTED }), t)[3].note).toBe('The ballot did not pass: the members decided against it.')
    expect(stepper(rec(), t)[3].note).toBe('The ballot did not pass.')
  })
})
