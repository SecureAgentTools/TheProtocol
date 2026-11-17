/**
 * V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): one code change's page. Its stepper and what it waits for, its problem and paths (sensitive ones marked), the timeline with times,
 * the checker's signed record (what it read, the files it touched against the named paths, that this frame verified it), the reviews, the ballot's tally and veto window,
 * and the steps this person may take: a signed-in member reviews an accepted change, the proposer's agent opens the ballot and withdraws. A refusal is the registry's
 * own sentence, in place. (Ported from the V0663 page's record tests.)
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ upstream: null as any, push: null as any, get: null as any, ballot: null as any, review: null as any, open: null as any, withdraw: null as any, route: { params: { id: 'cc_1' } as Record<string, any> },
  auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/codeChanges', async () => {
  const real = await vi.importActual<any>('@/services/api/codeChanges')
  return { ...real, proposeUpstream: (...a: any[]) => h.upstream(...a), getChange: (...a: any[]) => h.get(...a), getBallot: (...a: any[]) => h.ballot(...a), reviewChange: (...a: any[]) => h.review(...a), openBallot: (...a: any[]) => h.open(...a), withdrawChange: (...a: any[]) => h.withdraw(...a) }
})
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ push: (...a: any[]) => h.push(...a), replace: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChangeView from './CodeChangeView.vue'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const SHA = 'a'.repeat(40)
const rec = (over: Record<string, any> = {}) => ({
  id: 'cc_1', repository: 'theprotocol/AgentVault', paths: [CONSOLE_PREFIX + 'views/GuildBoard.vue'], title: 'A clearer order page', problem: 'The order page hides who is paid.', mode: 'bounty', branch: null,
  commit: null, order_id: 'gwo_1', order_status: 'open', proposer_did: 'did:a:me', sensitive: false, state: 'proposed', acceptance: null, proposal_id: null, passed_at: null, veto: null, go: null, merged: null,
  reviews: [], reviews_needed: 1, review_verdict: { approvals: 0, needed: 1, blockers: [], ok: false }, veto_window_hours: 24, veto_window_closes_at: null, created_at: '2026-11-14T10:00:00Z', ...over })
const accepted = (over: Record<string, any> = {}) => rec({ state: 'accepted', commit: SHA, acceptance: { ok: true, at: '2026-11-14T11:00:00Z', reasons: [],
  record: { commit: SHA, ci: { status: 'success' }, touched: [CONSOLE_PREFIX + 'views/GuildBoard.vue', CONSOLE_PREFIX + 'views/Other.vue'], secret_findings: 0, base: 'main', checker_kid: 'kid-0123456789abcdef', issued_at: '2026-11-14T10:59:00Z' } }, ...over })
const mountIt = () => mount(CodeChangeView, { global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('one code change', () => {
  beforeEach(() => {
    h.route.params = { id: 'cc_1' }; h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }
    h.get = vi.fn().mockResolvedValue(rec()); h.ballot = vi.fn().mockResolvedValue(null)
    h.review = vi.fn(); h.open = vi.fn(); h.withdraw = vi.fn(); h.upstream = vi.fn(); h.push = vi.fn()
  })

  it('shows the change: its state, its stepper, what it waits for, its problem, its paths with a sensitive one marked and what that needs', async () => {
    h.get = vi.fn().mockResolvedValue(rec({ sensitive: true, paths: [CONSOLE_PREFIX + 'stores/auth.ts', CONSOLE_PREFIX + 'views/A.vue'] }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-title').text()).toBe('A clearer order page')
    expect(tid(w, 'ccv-state').text()).toBe('Proposed')
    expect(tid(w, 'ccv-sensitive').exists()).toBe(true)
    expect(w.findAll('[data-testid^="cs-"][data-state]')).toHaveLength(7)
    expect(tid(w, 'ccv-next').text()).toMatch(/delivery/i)
    expect(tid(w, 'ccv-problem').text()).toContain('who is paid')
    expect(tid(w, 'ccv-paths').find('li.sens code').text()).toBe('stores/auth.ts')
    expect(tid(w, 'ccv-needs').text()).toMatch(/two approving reviews/)
    expect(h.get).toHaveBeenCalledWith('cc_1')
  })

  it('says plainly when the maintainer\'s go passed it while members are few, with the members who did vote', async () => {
    const boot = { members: 3, threshold: 10, by: 99, at: '2026-11-14T16:00:00Z', voted: [{ developer_id: 7, vote: true }, { developer_id: 8, vote: false }], sentence: 'x' }
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'passed', proposal_id: 12, passed_at: '2026-11-14T16:00:00Z', veto_window_closes_at: '2026-11-15T16:00:00Z', go: { at: '2026-11-14T16:00:00Z', bootstrap: boot }, bootstrap: boot }))
    const w = mountIt(); await flushPromises()
    const note = tid(w, 'ccv-bootstrap')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('Passed on the maintainer\'s go: the frame has 3 members, fewer than 10')
    expect(note.text()).toContain('2 members voted: 1 for, 1 against')
  })

  it('shows no such note for a change the ballot passed', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'passed', proposal_id: 12, passed_at: '2026-11-14T16:00:00Z', veto_window_closes_at: '2026-11-15T16:00:00Z' }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-bootstrap').exists()).toBe(false)
  })

  it('says so when there is no such change (a 404), and when it could not be read, with a way to try again', async () => {
    h.get = vi.fn().mockRejectedValue({ response: { status: 404 } })
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-missing').exists()).toBe(true)
    h.get = vi.fn().mockRejectedValue(new Error('502'))
    w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-error').exists()).toBe(true); expect(tid(w, 'ccv-missing').exists()).toBe(false)
    h.get = vi.fn().mockResolvedValue(rec()); await tid(w, 'ccv-retry').trigger('click'); await flushPromises()
    expect(tid(w, 'ccv-title').exists()).toBe(true)
  })

  it('shows the checker\'s signed record: CI, the secret scan, the base, who signed and that this frame verified it, and each touched file against the named paths', async () => {
    h.get = vi.fn().mockResolvedValue(accepted())
    const w = mountIt(); await flushPromises()
    const r = tid(w, 'ccv-record').text()
    expect(r).toContain('success'); expect(r).toContain('clean'); expect(r).toContain('main'); expect(r).toContain('kid-01234567'); expect(r).toMatch(/verified by this frame/)
    const files = w.findAll('[data-testid="ccv-touched"] li')
    expect(files).toHaveLength(2)
    expect(files[0].classes()).not.toContain('out')
    expect(files[1].classes()).toContain('out')                                 // views/Other.vue is outside the named path
    expect(files[1].text()).toMatch(/outside the named paths/)
  })

  it('a failed check lists each reason', async () => {
    h.get = vi.fn().mockResolvedValue(rec({ acceptance: { ok: false, at: '2026-11-14T11:00:00Z', reasons: ['CI is not green on the tip (failure)', 'x is outside the declared paths'] } }))
    const w = mountIt(); await flushPromises()
    expect(w.findAll('[data-testid="ccv-acceptance-reason"]').map((x) => x.text())).toEqual(['CI is not green on the tip (failure)', 'x is outside the declared paths'])
    expect(tid(w, 'ccv-acceptance').attributes('data-ok')).toBe('false')
    expect(tid(w, 'ccv-ev-checks').classes()).toContain('bad')
  })

  it('the timeline lists what happened in order, with times, and ends with what it waits for', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ reviews: [{ reviewer_developer_id: 3, verdict: 'approve', commit: SHA, findings: 'read it', at: Date.parse('2026-11-14T12:00:00Z') / 1000 }] }))
    const w = mountIt(); await flushPromises()
    const keys = w.findAll('[data-testid^="ccv-ev-"]').map((e) => e.attributes('data-testid'))
    expect(keys).toEqual(['ccv-ev-proposed', 'ccv-ev-checks', 'ccv-ev-review', 'ccv-ev-waiting'])
    expect(tid(w, 'ccv-ev-review').text()).toContain('read it')
    expect(tid(w, 'ccv-ev-review').find('time').exists()).toBe(true)
  })

  it('shows the reviews with their findings, each by a member number, and the approvals needed', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ sensitive: true, reviews_needed: 2, review_verdict: { approvals: 1, needed: 2, blockers: [], ok: false },
      reviews: [{ reviewer_developer_id: 3, verdict: 'approve', commit: SHA, findings: 'fine', at: 1 }] }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-reviews').find('h2').text()).toBe('Reviews (1 of 2 approvals)')
    expect(tid(w, 'ccv-review').text()).toContain('Member #3')
    expect(tid(w, 'ccv-review').text()).toContain('fine')
  })

  it('a signed-in person reviews an accepted change, and the registry answers', async () => {
    h.auth.activeAgent = { did: 'did:a:reviewer' }
    h.get = vi.fn().mockResolvedValue(accepted())
    h.review = vi.fn().mockResolvedValue(accepted({ reviews: [{ reviewer_developer_id: 9, verdict: 'approve', commit: SHA, findings: 'ok', at: 5 }], review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true } }))
    const w = mountIt(); await flushPromises()
    await tid(w, 'ccv-review-findings').setValue('ok')
    await tid(w, 'ccv-review-approve').trigger('click'); await flushPromises()
    expect(h.review).toHaveBeenCalledWith('cc_1', { verdict: 'approve', commit: SHA, findings: 'ok' })
    expect(tid(w, 'ccv-reviews').find('h2').text()).toContain('1 of 1')
  })

  it('shows the registry\'s refusal word for word, in place', async () => {
    h.auth.activeAgent = { did: 'did:a:reviewer' }
    h.get = vi.fn().mockResolvedValue(accepted())
    h.review = vi.fn().mockRejectedValue({ response: { data: { code: 'not_independent', detail: 'the proposer and the worker do not review their own change' } } })
    const w = mountIt(); await flushPromises()
    await tid(w, 'ccv-review-changes').trigger('click'); await flushPromises()
    expect(tid(w, 'ccv-action-error').text()).toBe('the proposer and the worker do not review their own change')
  })

  it('the proposer is told others review their change, and is not offered a review form', async () => {
    h.get = vi.fn().mockResolvedValue(accepted())                                  // proposer_did is the acting agent in the fixture
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-own').text()).toMatch(/other members review/)
    expect(tid(w, 'ccv-review-form').exists()).toBe(false)
  })

  it('the proposer opens the ballot once the reviews are in, and nobody else is offered it', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true } }))
    h.open = vi.fn().mockResolvedValue(accepted({ state: 'balloting', proposal_id: 12, review_verdict: { approvals: 1, needed: 1, blockers: [], ok: true } }))
    h.ballot = vi.fn().mockResolvedValue({ id: 12, status: 'ACTIVE', votes_for: 0, votes_against: 0, total_voters: 0, quorum_percent: 10, pass_percent: 50 })
    let w = mountIt(); await flushPromises()
    await tid(w, 'ccv-open-ballot').trigger('click'); await flushPromises()
    expect(h.open).toHaveBeenCalledWith('cc_1')
    expect(tid(w, 'ccv-ballot').exists()).toBe(true)
    expect(tid(w, 'ccv-ballot-link').exists()).toBe(true)
    h.auth.activeAgent = { did: 'did:a:other' }
    w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-open-ballot').exists()).toBe(false)
  })

  it('shows the ballot\'s tally, its thresholds and the veto window of a passed change', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'passed', proposal_id: 12, passed_at: '2026-11-14T15:00:00Z', veto_window_closes_at: '2026-11-15T15:00:00Z' }))
    h.ballot = vi.fn().mockResolvedValue({ id: 12, status: 'PASSED', votes_for: 6, votes_against: 2, total_voters: 8, quorum_percent: 10, pass_percent: 50 })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-tally').text()).toContain('6 for, 2 against')
    expect(tid(w, 'ccv-thresholds').text()).toContain('Quorum 10%')
    expect(tid(w, 'ccv-window').text()).toContain('2026-11-15 15:00 UTC')
  })

  it('the proposer withdraws before the ballot, with a reason, and sees the change withdrawn', async () => {
    h.get = vi.fn().mockResolvedValue(rec())
    h.withdraw = vi.fn().mockResolvedValue(rec({ state: 'withdrawn' }))
    const w = mountIt(); await flushPromises()
    await tid(w, 'ccv-withdraw-reason').setValue('superseded')
    await tid(w, 'ccv-withdraw').trigger('click'); await flushPromises()
    expect(h.withdraw).toHaveBeenCalledWith('cc_1', 'superseded')
    expect(tid(w, 'ccv-state').text()).toBe('Withdrawn')
    expect(tid(w, 'ccv-withdraw').exists()).toBe(false)
  })

  it('a merged change says where, and that production is a release\'s', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'merged', merged: { into: 'main', commit: SHA, at: '2026-11-14T17:00:00Z' } }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-next').text()).toMatch(/only through a release/i)
    expect(tid(w, 'ccv-ev-merged').text()).toContain('main')
  })

  // --- V0665 (order gwo_fbadffa68e593603d0c59b66): the people, named ---
  const NAMED = { proposer_name: "Ada's builder", proposer_gone: false }
  const review = (id: number, name: string | null, verdict = 'approve') => ({ reviewer_developer_id: id, reviewer_name: name, verdict, commit: SHA, findings: 'f', at: 1700000000 + id })

  it('names the proposer by the agent\'s name, the whole DID in the title and behind Copy', async () => {
    h.get = vi.fn().mockResolvedValue(rec({ ...NAMED }))
    const w = mountIt(); await flushPromises()
    const a = tid(w, 'ccv-author')
    expect(a.find('[data-testid="pn-name"]').text()).toBe("Ada's builder")
    expect(a.attributes('title')).toContain('did:')
    expect(a.find('[data-testid="pn-copy"]').exists()).toBe(true)
  })

  it('says an agent that is gone in words, with its DID still behind Copy', async () => {
    h.get = vi.fn().mockResolvedValue(rec({ proposer_name: null, proposer_gone: true }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-author').find('[data-testid="pn-name"]').text()).toBe('An agent that no longer exists')
    expect(tid(w, 'ccv-author').find('[data-testid="pn-copy"]').exists()).toBe(true)
  })

  it('names each reviewer by public name, and falls back to Member #n when there is none', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ ...NAMED, reviews: [review(3, 'Grace'), review(4, null)] }))
    const w = mountIt(); await flushPromises()
    const rs = w.findAll('[data-testid="ccv-review"]')
    expect(rs[0].find('[data-testid="pn-name"]').text()).toBe('Grace')
    expect(rs[1].find('[data-testid="pn-name"]').text()).toBe('Member #4')
    expect(rs[0].find('[data-testid="pn-copy"]').exists()).toBe(false)                    // a member has no DID
  })

  it('puts a tail on two reviewers who share a name, by member number, and on nobody else', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ ...NAMED, reviews: [review(3, 'Sam'), review(9, 'Sam'), review(5, 'Grace')] }))
    const w = mountIt(); await flushPromises()
    const tails = w.findAll('[data-testid="ccv-review"]').map((r) => r.findAll('[data-testid="pn-tail"]').map((t) => t.text()))
    expect(tails).toEqual([['#3'], ['#9'], []])
  })

  it('tells the proposer apart from a reviewer who has the same name', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ proposer_name: 'Sam', proposer_gone: false, reviews: [review(3, 'Sam')] }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-author').findAll('[data-testid="pn-tail"]')).toHaveLength(1)
    expect(tid(w, 'ccv-review').findAll('[data-testid="pn-tail"]')).toHaveLength(1)
  })

  it('names who acted on the timeline: the proposer on the first line, each reviewer on theirs', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ ...NAMED, reviews: [review(3, 'Grace'), review(4, 'Linus', 'changes')] }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-by-proposed').text()).toContain("Ada's builder")
    const by = w.findAll('[data-testid="ccv-by-review"]').map((e) => e.text())
    expect(by).toEqual(['Grace', 'Linus'].map((n) => expect.stringContaining(n)))
    expect(tid(w, 'ccv-by-checks').exists()).toBe(false)                                  // the checker is not a person: no name there
  })

  it('an older registry that sends no names reads as before: nothing broken, the agent unnamed', async () => {
    h.get = vi.fn().mockResolvedValue(rec())
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-author').find('[data-testid="pn-name"]').text()).toBe('An agent with no name')
  })
})

// --- V0667 D4: upstream ---------------------------------------------------------------------------------------------------------------------------------------------------------
describe('upstream (V0667 D4)', () => {
  const lineChange = (over: Record<string, any> = {}) => rec({ id: 'cc_1', state: 'merged', mode: 'branch', branch: 'lyceum/x', commit: SHA, code_distribution: { slug: 'lyceum', title: 'Lyceum', organization_name: 'Lyceum Labs' },
    line_ballot: { i_decide: true, votes: 3, deciders_now: 3 }, upstream: null, ...over })
  beforeEach(() => {
    h.route.params = { id: 'cc_1' }; h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }
    h.ballot = vi.fn().mockResolvedValue(null); h.review = vi.fn(); h.open = vi.fn(); h.withdraw = vi.fn(); h.upstream = vi.fn(); h.push = vi.fn()
  })

  it('offers "Propose upstream" to a decider on a merged line change, and a press goes to the new change on the main code', async () => {
    h.get = vi.fn().mockResolvedValue(lineChange())
    h.upstream = vi.fn().mockResolvedValue({ id: 'cc_new', upstream_of: 'cc_1' })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'up-propose').exists()).toBe(true)
    await tid(w, 'up-propose').trigger('click'); await flushPromises()
    expect(h.upstream).toHaveBeenCalledWith('cc_1')
    expect(h.push).toHaveBeenCalledWith({ name: 'code-change', params: { id: 'cc_new' } })
  })

  it('shows the registry\'s own sentence in place when it refuses, and does not leave the page', async () => {
    h.get = vi.fn().mockResolvedValue(lineChange())
    h.upstream = vi.fn().mockRejectedValue({ response: { status: 409, data: { code: 'already_upstream', detail: 'this change went upstream as cc_x (proposed): a line change goes upstream once' } } })
    const w = mountIt(); await flushPromises()
    await tid(w, 'up-propose').trigger('click'); await flushPromises()
    expect(tid(w, 'up-error').text()).toContain('a line change goes upstream once')
    expect(h.push).not.toHaveBeenCalled()
  })

  it('says where a line change stands once it went upstream, and offers nothing more', async () => {
    h.get = vi.fn().mockResolvedValue(lineChange({ upstream: { change_id: 'cc_new', state: 'balloting', since: null } }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'up-status').text()).toContain('Proposed upstream as cc_new')
    expect(tid(w, 'up-propose').exists()).toBe(false)
  })

  it('shows a change that was carried upstream with its provenance and a way back', async () => {
    h.get = vi.fn().mockResolvedValue(rec({ id: 'cc_1', state: 'proposed', upstream_of: 'cc_line', provenance: { line: { title: 'Lyceum', organization_name: 'Lyceum Labs', base_release: 'V0666' }, line_change: { id: 'cc_line', title: 'T' },
      ballot: { result: { status: 'PASSED' } }, reviews: [], checker: null } }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'up-provenance').exists()).toBe(true)
    expect(tid(w, 'up-back').exists()).toBe(true)
  })

  it('shows no upstream panel on a change that is neither', async () => {
    h.get = vi.fn().mockResolvedValue(rec())
    const w = mountIt(); await flushPromises()
    expect(w.find('[data-testid="up-root"]').exists()).toBe(false)
  })
})

// V0668 (order gwo_2d51e1af1b2a21a0bcdff5e7): the record says why its ballot did not pass and when it was tallied
describe('the ballot\'s outcome (V0668)', () => {
  beforeEach(() => {
    h.route.params = { id: 'cc_1' }; h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }
    h.ballot = vi.fn().mockResolvedValue(null); h.review = vi.fn(); h.open = vi.fn(); h.withdraw = vi.fn(); h.upstream = vi.fn(); h.push = vi.fn()
  })
  const OUTCOME = { status: 'FAILED', reason: 'quorum_not_met', unit: 'member', took_part: 300, required: 330.6, quorum_percent: 10, for: 300, against: 0,
    share_for: 100, pass_percent: 50, pass_rule: null, tallied_at: '2026-11-17T09:26:15Z', ended_at: '2026-11-17T09:25:00Z', sentence: 's' }

  it('a failed ballot says why and when it was tallied, beside its tally, and the timeline dates the failure by the tally', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'failed', proposal_id: 12, updated_at: '2026-11-16T09:25:00Z', ballot_outcome: OUTCOME }))
    h.ballot = vi.fn().mockResolvedValue({ id: 12, status: 'FAILED', votes_for: 300, votes_against: 0, total_voters: 3, quorum_percent: 10, pass_percent: 50 })
    const w = mountIt(); await flushPromises()
    const o = tid(w, 'ccv-outcome')
    expect(o.attributes('data-reason')).toBe('quorum_not_met')
    expect(o.text()).toContain('The quorum was not met: 300 of the 330.6 members\' points required took part')
    expect(o.text()).toContain('2026-11-17 09:26 UTC')
    expect(tid(w, 'ccv-ev-failed').find('time').attributes('datetime')).toBe('2026-11-17T09:26:15Z')
    expect(tid(w, 'ccv-ev-failed').text()).toContain('330.6')
  })

  it('a rejected ballot says the share in favour against the pass rule', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'failed', proposal_id: 12, ballot_outcome: { ...OUTCOME, reason: 'rejected', for: 100, against: 200, share_for: 33.3 } }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-outcome').text()).toContain('The members decided against it: 33.3% in favour, 50% needed to pass')
  })

  it('no outcome line while the ballot is open', async () => {
    h.get = vi.fn().mockResolvedValue(accepted({ state: 'balloting', proposal_id: 12 }))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccv-outcome').exists()).toBe(false)
  })
})
