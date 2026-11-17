/**
 * V0666 D2 (order gwo_f565ebd0575703f199dd9200): an organization's code distributions (release lines) in words. The queue's lanes, who decides and who may act
 * (D1's deciders()), the checker, reviews and the line's own ballot in sentences, the line form (D1's SLUG, RELEASE, quorum bounds and pass rule) and the
 * admin inbox's order and filters. Red before D2: services/codeDistributions/lines.ts does not exist.
 */
import { describe, expect, it } from 'vitest'
import {
  LANES, ballotWords, canManage, canPropose, checkerWords, draftOf, emptyLine, filterInbox, groupByLane, inboxRows, isDecider, isOrgOwner, laneOf,
  lineBody, linePatch, lineProblems, lineStateWord, maintainerOffer, pathLabel, noFilter, ownerOffer, pathsInsideLine, pauseProblem, platformOpenPaths, releaseOf, reviewWords, voteOffer,
  type Me,
} from './lines'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const tr = (_k: string, f: string, p?: Record<string, unknown>) => (p ? f.replace(/\{(\w+)\}/g, (_, k) => String(p[k])) : f)
const SHA = 'a'.repeat(40)
const ch = (over: Record<string, any> = {}) => ({ id: 'cc_1', state: 'proposed', commit: SHA, reviews: [], created_at: '2026-11-15T10:00:00Z',
  code_distribution: { slug: 'lyceum', state: 'active' }, ...over })
const me = (over: Partial<Me> = {}): Me => ({ developerId: 7, orgRole: 'member', teamLead: false, orgOwnerId: 1, ...over })

describe('the queue', () => {
  it('puts each state in its lane: checked until a review of the commit is in, then in review; failed, vetoed and withdrawn are ended, never dropped', () => {
    expect(laneOf(ch())).toBe('proposed')
    expect(laneOf(ch({ state: 'accepted' }))).toBe('checked')
    expect(laneOf(ch({ state: 'accepted', reviews: [{ commit: 'b'.repeat(40), verdict: 'approve' }] }))).toBe('checked')   // a review of another commit
    expect(laneOf(ch({ state: 'accepted', reviews: [{ commit: SHA, verdict: 'approve' }] }))).toBe('review')
    for (const s of ['balloting', 'passed', 'merged']) expect(laneOf(ch({ state: s }))).toBe(s)
    for (const s of ['failed', 'vetoed', 'withdrawn']) expect(laneOf(ch({ state: s }))).toBe('ended')
    expect(laneOf(ch({ state: 'something-new' }))).toBe('other')
  })
  it('groups every change into exactly one lane, every lane present', () => {
    const g = groupByLane([ch(), ch({ id: 'b', state: 'failed' }), ch({ id: 'c', state: 'merged' })])
    expect(Object.keys(g)).toEqual([...LANES])
    expect(Object.values(g).flat()).toHaveLength(3)
    expect(g.ended.map((c) => c.id)).toEqual(['b'])
  })
})

describe('a line\'s words (pass 1: a balloting line change said "Members voting")', () => {
  it('says the deciders vote on a line, and keeps the main line\'s word for every other state', () => {
    const main = (s: string) => `main:${s}`
    expect(lineStateWord('balloting', main, tr)).toBe('Deciders voting')
    for (const s of ['proposed', 'accepted', 'passed', 'failed']) expect(lineStateWord(s, main, tr)).toBe(`main:${s}`)
  })
  it('names a path the way a person reads it, the console itself by name (pass 1: the raw prefix filled a phone)', () => {
    expect(pathLabel(CONSOLE_PREFIX, tr)).toBe('The whole console')
    expect(pathLabel(CONSOLE_PREFIX + 'views/Library', tr)).toBe('views/Library')
    expect(pathLabel('docs/x.md', tr)).toBe('docs/x.md')
  })
})

describe('who may act (D1: owners and admins, and the deciding team\'s non-guest leads)', () => {
  it('decides as an owner, an admin or a lead of the team who is a member; never as a guest, a plain member or a stranger', () => {
    expect(isDecider(me({ orgRole: 'owner' }))).toBe(true)
    expect(isDecider(me({ orgRole: 'admin' }))).toBe(true)
    expect(isDecider(me({ orgRole: 'member', teamLead: true }))).toBe(true)
    expect(isDecider(me({ orgRole: 'guest', teamLead: true }))).toBe(false)
    expect(isDecider(me({ orgRole: 'member' }))).toBe(false)
    expect(isDecider(me({ orgRole: null, teamLead: true }))).toBe(false)
    expect(isDecider(me({ developerId: null, orgRole: 'owner' }))).toBe(false)
  })
  it('proposes as any non-guest member; manages lines as an owner or admin; the owner is the organization\'s owner_id', () => {
    expect([canPropose(me()), canPropose(me({ orgRole: 'guest' })), canPropose(me({ orgRole: null }))]).toEqual([true, false, false])
    expect([canManage(me({ orgRole: 'admin' })), canManage(me())]).toEqual([true, false])
    expect([isOrgOwner(me({ developerId: 1 })), isOrgOwner(me()), isOrgOwner(me({ developerId: 1, orgOwnerId: null }))]).toEqual([true, false, false])
  })
  it('offers the vote to a decider while the ballot is open, says why to anyone else, and takes none while the line is paused', () => {
    expect(voteOffer(ch({ state: 'balloting' }), me({ orgRole: 'admin' }), tr)).toEqual({ offer: true, why: '' })
    expect(voteOffer(ch({ state: 'balloting' }), me(), tr).why).toMatch(/owners and admins and the deciding team/)
    expect(voteOffer(ch({ state: 'balloting', code_distribution: { state: 'paused' } }), me({ orgRole: 'admin' }), tr).why).toMatch(/paused/)
    expect(voteOffer(ch({ state: 'passed' }), me({ orgRole: 'admin' }), tr)).toEqual({ offer: false, why: '' })
  })
  it('offers the owner\'s go and veto, and the maintainer\'s, on a passed change inside its veto window only', () => {
    const now = new Date('2026-11-15T12:00:00Z')
    const open = ch({ state: 'passed', veto_window_closes_at: '2026-11-16T12:00:00Z' })
    const shut = ch({ state: 'passed', veto_window_closes_at: '2026-11-15T11:00:00Z' })
    expect(ownerOffer(open, me({ developerId: 1 }), now)).toBe(true)
    expect(ownerOffer(open, me({ developerId: 2, orgRole: 'admin' }), now)).toBe(false)     // an admin is not the owner
    expect(ownerOffer(shut, me({ developerId: 1 }), now)).toBe(false)
    expect(ownerOffer(ch({ state: 'balloting' }), me({ developerId: 1 }), now)).toBe(false)
    expect([maintainerOffer(open, now), maintainerOffer(shut, now), maintainerOffer(ch({ state: 'merged' }), now)]).toEqual([true, false, false])
  })
})

describe('the record in words', () => {
  it('says the checker\'s record: none yet, passed, or failed with its reasons', () => {
    expect(checkerWords(ch(), tr).state).toBe('none')
    expect(checkerWords(ch({ acceptance: { ok: true } }), tr)).toEqual({ state: 'ok', text: 'The signed checks passed for this commit.' })
    expect(checkerWords(ch({ acceptance: { ok: false, reasons: ['ci_red', 'secret_found'] } }), tr).text).toBe('The signed checks did not pass: ci_red; secret_found')
  })
  it('counts the reviews of the commit and says when one asks for changes', () => {
    expect(reviewWords(ch(), tr)).toBe('No review yet')
    expect(reviewWords(ch({ reviews: [{ commit: SHA }], review_verdict: { approvals: 1, needed: 2, blockers: [] } }), tr)).toBe('1 of 2 approving reviews')
    expect(reviewWords(ch({ reviews: [{ commit: SHA }], review_verdict: { approvals: 0, needed: 1, blockers: [9] } }), tr)).toMatch(/asks for changes/)
  })
  it('words the line\'s own ballot: open with its count and close, the deciders\' note, and the result once written, failed said as failed', () => {
    expect(ballotWords(ch({ state: 'balloting', line_ballot: { votes: 1, deciders_now: 3, ends: '2026-11-17T09:30:00Z' } }), tr))
      .toBe('1 of 3 deciders voted; it closes at 2026-11-17 09:30 UTC, or once every decider has voted')
    expect(ballotWords(ch({ state: 'balloting', line_ballot: { votes: 0, deciders_now: 0, deciders_note: 'the line\'s deciding team is gone or inactive, so nobody can decide its changes' } }), tr))
      .toMatch(/deciding team is gone/)
    expect(ballotWords(ch({ state: 'passed', line_ballot: { result: { status: 'PASSED', sentence: '2 for, 0 against, of 2 deciders: passed' } } }), tr)).toBe('Passed: 2 for, 0 against, of 2 deciders: passed')
    expect(ballotWords(ch({ state: 'failed', line_ballot: { result: { status: 'FAILED', sentence: 'the line has no deciders at the close, so nobody decided: the change fails' } } }), tr))
      .toBe('Failed: the line has no deciders at the close, so nobody decided: the change fails')
    expect(ballotWords(ch(), tr)).toBe('')
  })
  it('V0668: a closed line ballot says when it closed', () => {
    expect(ballotWords(ch({ state: 'failed', line_ballot: { result: { status: 'FAILED', closed_at: '2026-11-17T09:26:15+00:00',
      sentence: '1 of 3 deciders voted, below the quorum of 50 percent' } } }), tr))
      .toBe('Failed: 1 of 3 deciders voted, below the quorum of 50 percent (closed 2026-11-17 09:26 UTC)')
  })
})

describe('the line form (D1\'s rules)', () => {
  const ok = { ...emptyLine('V0666'), slug: 'lyceum', title: 'Lyceum', open_paths: [CONSOLE_PREFIX + 'views'] }
  it('takes a good line and says each problem in its own field', () => {
    expect(lineProblems(ok, 'create', tr)).toEqual([])
    const fields = (d: any, mode: 'create' | 'edit' = 'create') => lineProblems(d, mode, tr).map((p) => p.field)
    expect(fields({ ...ok, slug: 'Bad' })).toEqual(['slug'])
    expect(fields({ ...ok, slug: 'l' })).toEqual(['slug'])
    expect(fields({ ...ok, base_release: 'v666' })).toEqual(['base_release'])
    expect(fields({ ...ok, title: ' ' })).toEqual(['title'])
    expect(fields({ ...ok, open_paths: [] })).toEqual(['open_paths'])
    expect(fields({ ...ok, open_paths: ['agentvault_registry/src/agentvault_registry/routers'] })).toEqual(['open_paths'])   // wider than the platform opens
    expect(fields({ ...ok, open_paths: [CONSOLE_PREFIX + 'secret/x.ts'] })).toEqual(['open_paths'])
    for (const q of [49, 101, 50.5, 'x']) expect(fields({ ...ok, quorum_percent: q })).toEqual(['quorum_percent'])
    expect(fields({ ...ok, quorum_percent: 100 })).toEqual([])
    expect(fields({ ...ok, pass_rule: 'two_thirds' })).toEqual(['pass_rule'])
    expect(fields({ ...ok, slug: 'Bad', base_release: 'x' }, 'edit')).toEqual([])           // the name and base release do not change on an edit
  })
  it('offers the platform\'s open paths and nothing wider', () => {
    expect(platformOpenPaths()).toEqual([CONSOLE_PREFIX])
  })
  it('reads the base release out of a software version', () => {
    expect(releaseOf('TheProtocolReleaseV0666')).toBe('V0666')
    expect(releaseOf('MoreCompliantThenYourWholeComplianceFrameworkV0548')).toBe('V0548')
    expect([releaseOf(''), releaseOf(null), releaseOf('dev')]).toEqual(['', '', ''])
  })
  it('sends the create body, and on an edit only what changed', () => {
    expect(lineBody({ ...ok, decider_team_id: '' }, 'org-1')).toEqual({ organization_id: 'org-1', slug: 'lyceum', title: 'Lyceum', base_release: 'V0666',
      open_paths: [CONSOLE_PREFIX + 'views'], decider_team_id: null, quorum_percent: 50, pass_rule: 'simple' })
    const before = draftOf({ slug: 'lyceum', title: 'Lyceum', base_release: 'V0666', open_paths: [CONSOLE_PREFIX + 'views'], decider_team_id: null, quorum_percent: 50, pass_rule: 'simple' })
    expect(linePatch(before, before)).toEqual({})
    expect(linePatch(before, { ...before, title: ' Lyceum 2 ', quorum_percent: '60', decider_team_id: 'team-1' })).toEqual({ title: 'Lyceum 2', quorum_percent: 60, decider_team_id: 'team-1' })
  })
  it('checks a change\'s paths inside the line and the platform (D1\'s paths_inside_line)', () => {
    const open = [CONSOLE_PREFIX + 'views']
    expect(pathsInsideLine([CONSOLE_PREFIX + 'views/A.vue'], open)).toBeNull()
    expect(pathsInsideLine([CONSOLE_PREFIX + 'views'], open)).toBeNull()
    expect(pathsInsideLine([CONSOLE_PREFIX + 'viewsX/A.vue'], open)).toMatch(/is not open in this line/)
    expect(pathsInsideLine(['agentvault_registry/x.py'], open)).toMatch(/not open in this phase/)
  })
})

describe('the admin inbox', () => {
  const lines = [{ slug: 'lyceum', organization_id: 'org-a' }, { slug: 'agora-x', organization_id: 'org-b' }]
  const by = {
    lyceum: [ch({ id: 'cc_old', created_at: '2026-11-14T10:00:00Z' }), ch({ id: 'cc_new', created_at: '2026-11-15T10:00:00Z', state: 'failed', sensitive: true })],
    'agora-x': [ch({ id: 'cc_mid', created_at: '2026-11-14T12:00:00Z', state: 'balloting' })],
  }
  it('puts every line\'s changes in one queue, newest first, an equal instant ordered by id', () => {
    expect(inboxRows(lines, by).map((r) => r.change.id)).toEqual(['cc_new', 'cc_mid', 'cc_old'])
    const tie = inboxRows([lines[0]], { lyceum: [ch({ id: 'a' }), ch({ id: 'b' })] })
    expect(tie.map((r) => r.change.id)).toEqual(['b', 'a'])
    expect(inboxRows(lines, {})).toEqual([])
  })
  it('filters by organization, line, lane and sensitive, each alone and together; the failed one stays in the queue', () => {
    const rows = inboxRows(lines, by)
    const ids = (f: any) => filterInbox(rows, { ...noFilter(), ...f }).map((r) => r.change.id)
    expect(ids({})).toEqual(['cc_new', 'cc_mid', 'cc_old'])
    expect(ids({ organization: 'org-b' })).toEqual(['cc_mid'])
    expect(ids({ line: 'lyceum' })).toEqual(['cc_new', 'cc_old'])
    expect(ids({ lane: 'ended' })).toEqual(['cc_new'])
    expect(ids({ sensitive: 'yes' })).toEqual(['cc_new'])
    expect(ids({ sensitive: 'no', line: 'lyceum' })).toEqual(['cc_old'])
  })
  it('refuses a pause without a reason', () => {
    expect(pauseProblem('  ', tr)).toMatch(/Say why/)
    expect(pauseProblem('x'.repeat(501), tr)).toMatch(/500/)
    expect(pauseProblem('a vote is being bought', tr)).toBeNull()
  })
})
