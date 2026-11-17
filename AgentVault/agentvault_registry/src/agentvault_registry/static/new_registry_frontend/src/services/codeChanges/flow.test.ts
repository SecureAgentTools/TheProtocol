import { describe, it, expect } from 'vitest'
import { STEP_KEYS, stepper, FILTERS, matchesFilter, timeline, ballotTally, shortPath, pathSummary, sensitiveNeeds } from './flow'
import { CONSOLE_PREFIX } from './pathRules'

/** V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the way a code change goes, as a stepper and a timeline, from the record the registry answers
 *  (GET /code-changes/{id}). Pure: the words come through a translate function, the structure is tested here. */
const t = (_k: string, fb: string, p?: Record<string, unknown>) => fb.replace(/\{(\w+)\}/g, (_m, k) => String(p?.[k] ?? ''))
const rec = (o: Record<string, any> = {}) => ({ id: 'cc_1', state: 'proposed', mode: 'branch', title: 'T', paths: [CONSOLE_PREFIX + 'views/X.vue'], repository: 'theprotocol/AgentVault',
  proposer_did: 'did:a:p', created_at: '2026-11-14T10:00:00Z', reviews: [], review_verdict: { approvals: 0, needed: 1, blockers: [], ok: false }, ...o })
const states = (r: any) => stepper(r, t).map((s) => s.state)

describe('the stepper: seven steps, one current, the rest done or to come', () => {
  it('names the seven steps in the order a change goes', () => {
    expect(STEP_KEYS).toEqual(['propose', 'checks', 'review', 'ballot', 'veto', 'merge', 'release'])
  })
  it('a new proposal waits at the checks', () => {
    expect(states(rec())).toEqual(['done', 'current', 'todo', 'todo', 'todo', 'todo', 'todo'])
  })
  it('a change whose last checks failed is stopped at the checks and says why', () => {
    const s = stepper(rec({ acceptance: { ok: false, reasons: ['CI is not green on the tip (failure)'] } }), t)
    expect(s[1].state).toBe('stopped')
    expect(s[1].note).toContain('CI is not green')
  })
  it('accepted waits for reviews, then for the ballot to be opened', () => {
    expect(states(rec({ state: 'accepted', acceptance: { ok: true } }))).toEqual(['done', 'done', 'current', 'todo', 'todo', 'todo', 'todo'])
    const ready = stepper(rec({ state: 'accepted', acceptance: { ok: true }, review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true } }), t)
    expect(ready[2].state).toBe('done'); expect(ready[3].state).toBe('current')
  })
  it('a reviewer asking for changes holds the review step', () => {
    const s = stepper(rec({ state: 'accepted', acceptance: { ok: true }, review_verdict: { approvals: 1, needed: 2, blockers: [4], ok: false } }), t)
    expect(s[2].state).toBe('stopped')
  })
  it('balloting, then the veto window, then merged; production is never "done" by a merge', () => {
    expect(states(rec({ state: 'balloting' }))).toEqual(['done', 'done', 'done', 'current', 'todo', 'todo', 'todo'])
    expect(states(rec({ state: 'passed' }))).toEqual(['done', 'done', 'done', 'done', 'current', 'todo', 'todo'])
    const m = stepper(rec({ state: 'merged', merged: { into: 'main', commit: 'c' } }), t)
    expect(m.map((x) => x.state)).toEqual(['done', 'done', 'done', 'done', 'done', 'done', 'todo'])
    expect(m[6].note).toMatch(/only through a release/i)
  })
  it('a ballot that fails, a veto and a withdrawal stop the line where it ended', () => {
    expect(states(rec({ state: 'failed' }))).toEqual(['done', 'done', 'done', 'stopped', 'todo', 'todo', 'todo'])
    expect(states(rec({ state: 'vetoed' }))).toEqual(['done', 'done', 'done', 'done', 'stopped', 'todo', 'todo'])
    expect(states(rec({ state: 'withdrawn' }))[0]).toBe('stopped')
    expect(states(rec({ state: 'withdrawn', acceptance: { ok: true }, commit: 'c' }))[2]).toBe('stopped')
  })
  it('names who acts at each step in the note of the current one', () => {
    expect(stepper(rec({ state: 'accepted', acceptance: { ok: true }, review_verdict: { approvals: 0, needed: 2, blockers: [], ok: false }, sensitive: true }), t)[2].note).toContain('2')
  })
})

describe('the filters', () => {
  const all = ['proposed', 'accepted', 'balloting', 'passed', 'merged', 'failed', 'vetoed', 'withdrawn'].map((s) => rec({ id: s, state: s }))
  it('lists a filter per group of states', () => {
    expect(FILTERS.map((f) => f.key)).toEqual(['all', 'open', 'merged', 'ended'])
  })
  it('open = being decided, merged, ended = did not pass, vetoed or withdrawn', () => {
    const pick = (k: string) => all.filter((r) => matchesFilter(r, k)).map((r) => r.id)
    expect(pick('all')).toHaveLength(8)
    expect(pick('open')).toEqual(['proposed', 'accepted', 'balloting', 'passed'])
    expect(pick('merged')).toEqual(['merged'])
    expect(pick('ended')).toEqual(['failed', 'vetoed', 'withdrawn'])
  })
})

// V0666 (the maintainer's word, room seq 4404, 4424 and 4431): while the frame has few members, a ballot that missed its quorum can pass on the maintainer's go; the record says it
describe('passed on the maintainer\'s go while members are few', () => {
  const boot = { members: 3, threshold: 10, by: 99, at: '2026-11-14T16:00:00Z', voted: [{ developer_id: 7, vote: true }, { developer_id: 8, vote: false }], sentence: 'x' }
  const passed = (o: Record<string, any> = {}) => rec({ state: 'passed', commit: 'a'.repeat(40), proposal_id: 12, passed_at: '2026-11-14T16:00:00Z', go: { at: '2026-11-14T16:00:00Z', bootstrap: boot }, bootstrap: boot, ...o })
  it('says it in words at the veto step', () => {
    const note = stepper(passed(), t)[4].note
    expect(note).toContain('maintainer\'s go')
    expect(note).toContain('3 members, fewer than 10')
  })
  it('a normal pass keeps its own words', () => {
    expect(stepper(rec({ state: 'passed' }), t)[4].note).toMatch(/waiting for the veto window or the go/i)
  })
  it('the timeline says the ballot ended without a quorum, then that the go passed it, and never that the ballot passed', () => {
    const ev = timeline(passed(), t)
    const keys = ev.map((e) => e.key)
    expect(keys).toContain('failed'); expect(keys).toContain('passed'); expect(keys).not.toContain('go')
    expect(ev.find((e) => e.key === 'failed')!.title).toMatch(/without a quorum/i)
    const p = ev.find((e) => e.key === 'passed')!
    expect(p.title).toContain('maintainer\'s go'); expect(p.title).toContain('3 members, fewer than 10')
    expect(p.detail).toBe('2 members voted: 1 for, 1 against')
    expect(ev.map((e) => e.title).join(' | ')).not.toMatch(/The ballot passed/)
  })
  it('a normal pass and its go are unchanged', () => {
    const ev = timeline(rec({ state: 'passed', proposal_id: 12, passed_at: '2026-11-14T15:00:00Z', go: { at: '2026-11-14T16:00:00Z' } }), t)
    expect(ev.map((e) => e.key)).toEqual(expect.arrayContaining(['passed', 'go']))
    expect(ev.find((e) => e.key === 'passed')!.title).toBe('The ballot passed')
  })
})

describe('the timeline', () => {
  it('starts with the proposal, its time and who made it', () => {
    const ev = timeline(rec(), t)
    expect(ev[0]).toMatchObject({ key: 'proposed', at: '2026-11-14T10:00:00Z' })
    expect(ev[0].title).toContain('proposed')
  })
  it('lists a check (ok or not, with every reason), each review, the ballot, the pass, the go or veto and the merge, in order', () => {
    const ev = timeline(rec({ state: 'merged', commit: 'a'.repeat(40), proposal_id: 12, passed_at: '2026-11-14T15:00:00Z', go: { at: '2026-11-14T16:00:00Z' },
      acceptance: { ok: true, at: '2026-11-14T11:00:00Z', record: { commit: 'a'.repeat(40), touched: ['x'], ci: { status: 'success' }, secret_findings: 0 } },
      reviews: [{ reviewer_developer_id: 3, verdict: 'approve', commit: 'a'.repeat(40), findings: 'read it', at: Date.parse('2026-11-14T12:00:00Z') / 1000 }],
      merged: { into: 'main', commit: 'a'.repeat(40), at: '2026-11-14T17:00:00Z' } }), t)
    expect(ev.map((e) => e.key)).toEqual(['proposed', 'checks', 'review', 'ballot', 'passed', 'go', 'merged'])
    expect(ev.find((e) => e.key === 'review')).toMatchObject({ kind: 'ok', at: '2026-11-14T12:00:00.000Z', detail: 'read it' })
    expect(ev.find((e) => e.key === 'merged')!.title).toContain('main')
  })
  it('a failed check is bad and carries every reason', () => {
    const ev = timeline(rec({ acceptance: { ok: false, at: '2026-11-14T11:00:00Z', reasons: ['CI is not green on the tip (failure)', 'x is outside the declared paths'] } }), t)
    const c = ev.find((e) => e.key === 'checks')!
    expect(c.kind).toBe('bad')
    expect(c.detail).toContain('CI is not green'); expect(c.detail).toContain('outside the declared paths')
  })
  it('a change asking for reviews, still waiting, ends the timeline with what it waits for (no time)', () => {
    const ev = timeline(rec({ state: 'accepted', acceptance: { ok: true, at: '2026-11-14T11:00:00Z' }, commit: 'a'.repeat(40) }), t)
    expect(ev[ev.length - 1]).toMatchObject({ kind: 'wait', at: null })
  })
  it('a veto and a withdrawal say who and why', () => {
    const v = timeline(rec({ state: 'vetoed', veto: { reason: 'not now', at: '2026-11-14T16:00:00Z' } }), t).find((e) => e.key === 'veto')!
    expect(v).toMatchObject({ kind: 'bad', detail: 'not now' })
    expect(timeline(rec({ state: 'withdrawn', updated_at: '2026-11-14T13:00:00Z' }), t).some((e) => e.key === 'withdrawn')).toBe(true)
  })
})

describe('the ballot tally', () => {
  it('reads the proposal: votes, voters, the two thresholds, the end', () => {
    expect(ballotTally({ id: 3, status: 'ACTIVE', votes_for: 6, votes_against: 2, total_voters: 8, quorum_percent: 20, pass_percent: 66, end_timestamp: '2026-11-16T10:00:00Z' }))
      .toMatchObject({ id: 3, forVotes: 6, against: 2, voters: 8, quorumPct: 20, passPct: 66, forShare: 75, open: true })
  })
  it('has no share with no votes, and is closed when the status says so', () => {
    expect(ballotTally({ id: 3, status: 'PASSED', votes_for: 0, votes_against: 0 })).toMatchObject({ forShare: null, open: false })
  })
})

describe('paths', () => {
  it('shows a path relative to the console and summarizes a long list', () => {
    expect(shortPath(CONSOLE_PREFIX + 'views/X.vue')).toBe('views/X.vue')
    expect(shortPath('README.md')).toBe('README.md')
    expect(pathSummary(['a', 'b', 'c', 'd'], 2)).toEqual({ shown: ['a', 'b'], more: 2 })
    expect(pathSummary(['a'], 2)).toEqual({ shown: ['a'], more: 0 })
  })
  it('says what a sensitive change needs', () => {
    expect(sensitiveNeeds(t)).toMatch(/two approving reviews/i)
    expect(sensitiveNeeds(t)).toMatch(/two thirds|66/i)
  })
})
