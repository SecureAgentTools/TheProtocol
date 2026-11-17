/**
 * V0663 (order gwo_58327a76b7e3ecf63140eb79) and V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): the Code changes page (#/code-changes): it explains the way a change goes
 * (seven steps, what a sensitive path needs, the licence line), lists the changes as cards with their state, the step they are at, their paths (sensitive ones
 * marked), bounty or branch, author and ballot tally, filters them by state, invites the first one with an example, says so when the list could not be read
 * (never "nothing here"), and sends a V0663 link (?id=) to the change's own page. A change's record has its own page (CodeChangeView.test.ts); proposing is a
 * guided flow (CodeChangeNew.test.ts).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ list: null as any, ballot: null as any, route: { query: {} as Record<string, any> }, replace: vi.fn() }))
vi.mock('@/services/api/codeChanges', () => ({ listChanges: (...a: any[]) => h.list(...a), getBallot: (...a: any[]) => h.ballot(...a) }))
vi.mock('@/services/api/repoAccount', () => ({ getRepoAccount: () => Promise.resolve({ enabled: false }), linkRepoAccount: vi.fn() }))   // V0667: repository accounts off here: the form as before
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: false }) }))
vi.mock('vue-router', () => ({ useRoute: () => h.route, useRouter: () => ({ replace: h.replace, push: vi.fn() }) }))

import CodeChanges from './CodeChanges.vue'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const rec = (over: Record<string, any> = {}) => ({
  id: 'cc_1', repository: 'theprotocol/AgentVault', paths: [CONSOLE_PREFIX + 'views/GuildBoard.vue'], title: 'A clearer order page', problem: 'p', mode: 'bounty', branch: null, commit: null,
  order_id: 'gwo_1', order_status: 'open', proposer_did: 'did:theprotocol:eu.theprotocol.cloud:0fc15206-ca13-4257-884f-656866dd1bb1', proposer_name: "Ada's builder", proposer_gone: false, sensitive: false, state: 'proposed', acceptance: null, proposal_id: null,
  reviews: [], review_verdict: { approvals: 0, needed: 1, blockers: [], ok: false }, created_at: '2026-11-14T10:00:00Z', ...over })
const mountIt = () => mount(CodeChanges, { global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the Code changes page', () => {
  beforeEach(() => { h.route.query = {}; h.replace.mockClear(); h.list = vi.fn().mockResolvedValue([]); h.ballot = vi.fn().mockResolvedValue(null) })

  it('explains the way a change goes: the seven steps, what is open, what a sensitive path needs, the licence line with its link', async () => {
    const w = mountIt(); await flushPromises()
    expect(w.findAll('[data-testid^="cs-"][data-state]')).toHaveLength(7)
    expect(tid(w, 'ccl-open-rule').text()).toContain('console')
    expect(tid(w, 'ccl-sensitive-rule').text()).toMatch(/two approving reviews/)
    expect(tid(w, 'ccl-terms').find('a').attributes('href')).toContain('LICENSING.md')
    expect(JSON.parse(tid(w, 'ccl-propose').attributes('data-to')!)).toEqual({ name: 'code-changes-new' })
  })

  it('folds the explanation on a phone (it is three screens tall there) and the link to it opens it; on a wide screen it is open', async () => {
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'ccl-way').attributes('open')).toBeDefined()                  // no matchMedia in the test, and a wide screen: open
    ;(window as any).matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener() {}, removeEventListener() {} })
    document.body.innerHTML = ''
    w = mount(CodeChanges, { attachTo: document.body, global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } }); await flushPromises()
    const d = w.find('[data-testid="ccl-way"]')
    expect(d.attributes('open')).toBeUndefined()
    ;(Element.prototype as any).scrollIntoView = vi.fn()
    await w.find('[data-testid="ccl-way-link"]').trigger('click')
    expect((d.element as HTMLDetailsElement).open).toBe(true)
    delete (window as any).matchMedia
    w.unmount()
  })

  it('lists the changes as cards: state in words, the step it is at, the paths with a sensitive one marked, bounty with its order, the author short', async () => {
    h.list = vi.fn().mockResolvedValue([
      rec(),
      rec({ id: 'cc_2', title: 'Branch change', mode: 'branch', branch: 'fix/x', order_id: null, state: 'accepted', sensitive: true, acceptance: { ok: true }, commit: 'a'.repeat(40),
        paths: [CONSOLE_PREFIX + 'stores/auth.ts', CONSOLE_PREFIX + 'views/A.vue', CONSOLE_PREFIX + 'views/B.vue'] }),
    ])
    const w = mountIt(); await flushPromises()
    const one = tid(w, 'ccl-card-cc_1')
    expect(one.find('[data-testid="ccl-state"]').text()).toBe('Proposed')
    expect(one.find('[data-testid="ccl-where"]').text()).toContain('Contract and checks')
    expect(one.find('[data-testid="ccl-order"]').exists()).toBe(true)
    expect(one.find('[data-testid="pn-name"]').text()).toBe("Ada's builder")            // the agent's name, not its DID
    expect(one.text()).not.toContain('did:theprotocol')
    expect(one.find('[data-testid="ccl-author"]').attributes('title')).toContain('0fc15206')   // the whole DID in the title
    const two = tid(w, 'ccl-card-cc_2')
    expect(two.find('[data-testid="ccl-sensitive"]').exists()).toBe(true)
    expect(two.findAll('[data-testid="ccl-paths"] code')).toHaveLength(2)    // two shown ...
    expect(two.find('[data-testid="ccl-paths"]').text()).toContain('+1 more') // ... and the rest counted
    expect(two.find('[data-testid="ccl-paths"] code.sens').text()).toBe('stores/auth.ts')
    expect(two.text()).toContain('fix/x')
  })

  it('shows the ballot\'s tally on a change that has one', async () => {
    h.list = vi.fn().mockResolvedValue([rec({ id: 'cc_3', state: 'balloting', proposal_id: 12 })])
    h.ballot = vi.fn().mockResolvedValue({ id: 12, status: 'ACTIVE', votes_for: 6, votes_against: 2, total_voters: 8, quorum_percent: 10, pass_percent: 50, end_timestamp: '2026-11-16T10:00:00Z' })
    const w = mountIt(); await flushPromises()
    expect(h.ballot).toHaveBeenCalledWith(12)
    expect(tid(w, 'ccl-tally-cc_3').text()).toContain('6 for, 2 against')
  })

  it('filters by state and counts each group', async () => {
    h.list = vi.fn().mockResolvedValue([rec({ id: 'a', state: 'proposed' }), rec({ id: 'b', state: 'merged' }), rec({ id: 'c', state: 'failed' }), rec({ id: 'd', state: 'withdrawn' })])
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccl-filter-all').text()).toContain('4')
    expect(tid(w, 'ccl-filter-open').text()).toContain('1')
    expect(tid(w, 'ccl-filter-ended').text()).toContain('2')
    await tid(w, 'ccl-filter-merged').trigger('click')
    expect(w.findAll('[data-testid^="ccl-card-"]').map((c) => c.attributes('data-testid'))).toEqual(['ccl-card-b'])
    expect(tid(w, 'ccl-filter-merged').attributes('aria-pressed')).toBe('true')
    await tid(w, 'ccl-filter-open').trigger('click')
    expect(w.findAll('[data-testid^="ccl-card-"]')).toHaveLength(1)
  })

  it('invites the first change with an example when there is none, and does not say so over a failed read', async () => {
    let w = mountIt(); await flushPromises()
    expect(tid(w, 'ccl-empty').exists()).toBe(true)
    expect(tid(w, 'ccl-example').text()).toContain('GuildBoard.vue')
    h.list = vi.fn().mockRejectedValue(new Error('502'))
    w = mountIt(); await flushPromises()
    expect(tid(w, 'ccl-error').exists()).toBe(true)
    expect(tid(w, 'ccl-empty').exists()).toBe(false)
    h.list = vi.fn().mockResolvedValue([rec()]); await tid(w, 'ccl-retry').trigger('click'); await flushPromises()
    expect(tid(w, 'ccl-card-cc_1').exists()).toBe(true)
  })

  it('shows placeholder cards while the first read is out', async () => {
    let done: (v: any) => void = () => {}
    h.list = vi.fn().mockReturnValue(new Promise((r) => { done = r }))
    const w = mountIt(); await w.vm.$nextTick()
    expect(tid(w, 'ccl-loading').findAll('.ccl-skel-card')).toHaveLength(3)
    done([rec()]); await flushPromises()
    expect(tid(w, 'ccl-loading').exists()).toBe(false)
  })

  it('sends a V0663 link (?id=) to the change\'s own page', async () => {
    h.route.query = { id: 'cc_9' }
    mountIt(); await flushPromises()
    expect(h.replace).toHaveBeenCalledWith({ name: 'code-change', params: { id: 'cc_9' } })
    expect(h.list).not.toHaveBeenCalled()
  })
})

describe('the Senate floor names a code change', () => {
  it('marks a code_change proposal as a code change', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, './SenateFloor.vue'), 'utf8')
    expect(src).toContain("proposal.proposalType === 'code_change'")
    expect(src).toContain('sn-prop-type-pill--code')
  })
})

describe('the people on the cards (V0665)', () => {
  beforeEach(() => { h.route.query = {}; h.replace.mockClear(); h.list = vi.fn().mockResolvedValue([]); h.ballot = vi.fn().mockResolvedValue(null) })

  it('shows a tail only on the cards whose proposers share a name, and says an agent that is gone in words', async () => {
    h.list = vi.fn().mockResolvedValue([
      rec({ id: 'cc_1', proposer_name: 'Builder', proposer_did: 'did:theprotocol:eu:aaaaaa-111111' }),
      rec({ id: 'cc_2', proposer_name: 'Builder', proposer_did: 'did:theprotocol:eu:bbbbbb-222222' }),
      rec({ id: 'cc_3', proposer_name: 'Solo', proposer_did: 'did:theprotocol:eu:cccccc-333333' }),
      rec({ id: 'cc_4', proposer_name: null, proposer_gone: true, proposer_did: 'did:theprotocol:eu:dddddd-444444' }),
    ])
    const w = mountIt(); await flushPromises()
    const tails = (id: string) => tid(w, `ccl-card-${id}`).findAll('[data-testid="pn-tail"]').map((x: any) => x.text())
    expect(tails('cc_1')).toEqual(['…111111']); expect(tails('cc_2')).toEqual(['…222222'])
    expect(tails('cc_3')).toEqual([])
    expect(tid(w, 'ccl-card-cc_4').find('[data-testid="pn-name"]').text()).toBe('An agent that no longer exists')
  })

  it('the tail follows the cards on screen: filter one of two same-named proposers away and the tail goes', async () => {
    h.list = vi.fn().mockResolvedValue([
      rec({ id: 'cc_1', proposer_name: 'Builder', proposer_did: 'did:theprotocol:eu:aaaaaa-111111', state: 'proposed' }),
      rec({ id: 'cc_2', proposer_name: 'Builder', proposer_did: 'did:theprotocol:eu:bbbbbb-222222', state: 'merged' }),
    ])
    const w = mountIt(); await flushPromises()
    await tid(w, 'ccl-filter-merged').trigger('click'); await flushPromises()
    expect(tid(w, 'ccl-card-cc_2').findAll('[data-testid="pn-tail"]')).toHaveLength(0)
  })
})
