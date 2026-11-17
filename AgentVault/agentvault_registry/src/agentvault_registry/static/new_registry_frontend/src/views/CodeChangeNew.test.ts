/**
 * V0664 (order gwo_fc4ec96d3679ca02d5e3afa8): proposing a code change as a guided flow. The problem (title and a sentence or two), the files (a picker over the console's tree that
 * checks each path the way the registry will and says what a sensitive one needs), how it gets written (a bounty or a branch with its full commit id), and a review with what
 * happens next and the licence line. Each step says what it still needs before the next; anyone can walk it, proposing is the selected agent's; a refusal is the registry's sentence.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ propose: null as any, push: vi.fn(), auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/codeChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/codeChanges')), proposeChange: (...a: any[]) => h.propose(...a) }))
vi.mock('@/services/api/repoAccount', () => ({ getRepoAccount: () => Promise.resolve({ enabled: false }), linkRepoAccount: vi.fn() }))   // V0667: repository accounts off here: the form as before
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push, replace: vi.fn() }), useRoute: () => ({ params: {}, query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChangeNew from './CodeChangeNew.vue'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const mountIt = () => mount(CodeChangeNew, { global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const next = async (w: any) => { await tid(w, 'ccn-next').trigger('click'); await flushPromises() }
const PROBLEM = 'The order page does not say which agent is paid when a firm bids.'
async function toFiles(w: any) { await tid(w, 'ccn-title').setValue('Show who is paid'); await tid(w, 'ccn-problem').setValue(PROBLEM); await next(w) }

describe('the guided proposal', () => {
  beforeEach(() => { h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }; h.propose = vi.fn(); h.push.mockClear() })

  it('starts on the problem, with four steps named, and says what is missing before it goes on', async () => {
    const w = mountIt(); await flushPromises()
    expect(w.findAll('[data-testid^="ccn-pill-"]')).toHaveLength(4)
    expect(tid(w, 'ccn-step-what').exists()).toBe(true)
    await next(w)
    expect(tid(w, 'ccn-step-what').exists()).toBe(true)                       // did not go on
    expect(tid(w, 'ccn-problems').text()).toContain('title'); expect(tid(w, 'ccn-problems').text()).toContain('20 characters')
    expect(tid(w, 'ccn-title').attributes('aria-invalid')).toBe('true')
    await toFiles(w)
    expect(tid(w, 'ccn-step-files').exists()).toBe(true)
  })

  it('suggests the console\'s files as you type, adds one, and says it is open; a sensitive one says what it needs; a refused one says the registry\'s sentence', async () => {
    const w = mountIt(); await flushPromises(); await toFiles(w)
    await tid(w, 'ccn-path-input').setValue('guildboard')
    await vi.waitFor(() => expect(w.findAll('[data-testid="ccn-suggest"]').length).toBeGreaterThan(0), { timeout: 5000 })   // the console's tree is a lazy import: wait for it, not for a tick
    const first = w.findAll('[data-testid="ccn-suggest"]')[0]
    expect(first.text()).toBe('views/GuildBoard.vue')
    await first.trigger('click')
    expect(tid(w, 'ccn-path-row').attributes('data-status')).toBe('ok')
    await tid(w, 'ccn-path-input').setValue('stores/auth.ts'); await tid(w, 'ccn-add').trigger('click')
    await tid(w, 'ccn-path-input').setValue('.env'); await tid(w, 'ccn-add').trigger('click')
    const rows = w.findAll('[data-testid="ccn-path-row"]')
    expect(rows.map((r) => r.attributes('data-status'))).toEqual(['ok', 'sensitive', 'refused'])
    expect(rows[2].text()).toMatch(/forbidden path/)
    expect(tid(w, 'ccn-sensitive-needs').text()).toMatch(/two approving reviews/)
    await next(w)
    expect(tid(w, 'ccn-step-files').exists()).toBe(true)                      // a refused path holds the step
    expect(tid(w, 'ccn-problems').exists()).toBe(false)                      // the row already says it: said once, not twice
    expect((tid(w, 'ccn-step-files').text().match(/forbidden path/g) || []).length).toBe(1)
    await rows[2].find('[data-testid="ccn-path-remove"]').trigger('click')
    await next(w)
    expect(tid(w, 'ccn-step-how').exists()).toBe(true)
  })

  it('never suggests a path the registry refuses', async () => {
    const w = mountIt(); await flushPromises(); await toFiles(w)
    await tid(w, 'ccn-path-input').setValue('guild')
    await vi.waitFor(() => expect(w.findAll('[data-testid="ccn-suggest"]').length).toBeGreaterThan(0), { timeout: 5000 })   // the tree has loaded: the empty answer below is then a real one
    await tid(w, 'ccn-path-input').setValue('secret')
    expect(w.findAll('[data-testid="ccn-suggest"]').map((s) => s.text()).filter((x) => /secret/i.test(x))).toEqual([])
  })

  it('a bounty needs an amount; a branch needs a name and a full commit id and says so while typing', async () => {
    const w = mountIt(); await flushPromises(); await toFiles(w)
    await tid(w, 'ccn-path-input').setValue('views/GuildBoard.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
    await next(w)
    expect(tid(w, 'ccn-problems').text()).toMatch(/bounty above zero/i)
    await tid(w, 'ccn-mode-branch').setValue(true)
    await tid(w, 'ccn-branch').setValue('fix/x'); await tid(w, 'ccn-commit').setValue('abc')
    expect(tid(w, 'ccn-commit-note').text()).toMatch(/Not a full commit id/)
    await next(w)
    expect(tid(w, 'ccn-step-how').exists()).toBe(true)
    await tid(w, 'ccn-commit').setValue('a'.repeat(40))
    expect(tid(w, 'ccn-commit-note').text()).toBe('A full commit id.')
    await next(w)
    expect(tid(w, 'ccn-step-review').exists()).toBe(true)
  })

  it('shows the summary, the licence line with its link and what happens next, and proposes with the body the registry takes', async () => {
    h.propose = vi.fn().mockResolvedValue({ id: 'cc_7' })
    const w = mountIt(); await flushPromises(); await toFiles(w)
    await tid(w, 'ccn-path-input').setValue('views/GuildBoard.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
    await tid(w, 'ccn-bounty').setValue('5'); await next(w)
    expect(tid(w, 'ccn-summary').text()).toContain('Show who is paid')
    expect(tid(w, 'ccn-summary').text()).toContain('views/GuildBoard.vue')
    expect(tid(w, 'ccn-licence').find('a').attributes('href')).toContain('LICENSING.md')
    expect(tid(w, 'ccn-after').text()).toMatch(/Guild holds the bounty/)
    await tid(w, 'ccn-submit').trigger('click'); await flushPromises()
    expect(h.propose).toHaveBeenCalledWith({ repository: 'theprotocol/AgentVault', paths: [CONSOLE_PREFIX + 'views/GuildBoard.vue'], title: 'Show who is paid', problem: PROBLEM, bounty: 5 })
    expect(h.push).toHaveBeenCalledWith({ name: 'code-change', params: { id: 'cc_7' } })
  })

  it('the next-steps text follows the way it is written (a branch has no worker)', async () => {
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccn-after').text()).toMatch(/Guild holds the bounty/)
    await toFiles(w); await tid(w, 'ccn-path-input').setValue('views/A.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
    await tid(w, 'ccn-mode-branch').setValue(true)
    expect(tid(w, 'ccn-after').text()).toMatch(/checker reads your commit/)
  })

  it('shows the registry\'s refusal word for word and stays on the review', async () => {
    h.propose = vi.fn().mockRejectedValue({ response: { data: { code: 'not_member', detail: 'only a member\'s agent proposes a change' } } })
    const w = mountIt(); await flushPromises(); await toFiles(w)
    await tid(w, 'ccn-path-input').setValue('views/GuildBoard.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
    await tid(w, 'ccn-bounty').setValue('5'); await next(w)
    await tid(w, 'ccn-submit').trigger('click'); await flushPromises()
    expect(tid(w, 'ccn-error').text()).toBe('only a member\'s agent proposes a change')
    expect(h.push).not.toHaveBeenCalled()
  })

  it('lets anyone walk the steps but offers Propose only to a signed-in agent, and says so at the top', async () => {
    h.auth = { isAuthenticated: false, activeAgent: null }
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccn-signin').exists()).toBe(true)
    await toFiles(w); await tid(w, 'ccn-path-input').setValue('views/A.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
    await tid(w, 'ccn-bounty').setValue('5'); await next(w)
    expect(tid(w, 'ccn-submit').attributes('disabled')).toBeDefined()
  })

  it('can go back a step without losing what was typed, and a step reached is a pill that can be pressed', async () => {
    const w = mountIt(); await flushPromises(); await toFiles(w)
    await tid(w, 'ccn-back-step').trigger('click')
    expect((tid(w, 'ccn-title').element as HTMLInputElement).value).toBe('Show who is paid')
    expect(tid(w, 'ccn-pill-how').attributes('disabled')).toBeDefined()        // not reached yet
  })
})
