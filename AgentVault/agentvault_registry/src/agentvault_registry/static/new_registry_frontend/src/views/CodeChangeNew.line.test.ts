/**
 * V0666 D2 (order gwo_f565ebd0575703f199dd9200): proposing into an organization's release line reuses the Code changes proposal with the line chosen
 * (#/code-changes/new?line=<slug>). The page names the line, holds the files inside its open paths (D1: paths_inside_line) and names it in the body
 * (code_distribution); a line that cannot be read, or a registry where code distributions are off, says so and proposes nothing. The main line's proposal is
 * unchanged (CodeChangeNew.test.ts). Red before D2: the page takes no line.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ propose: null as any, push: vi.fn(), getLine: null as any, cfg: null as any, auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/codeChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/codeChanges')), proposeChange: (...a: any[]) => h.propose(...a) }))
vi.mock('@/services/api/codeDistributions', () => ({ getLine: (...a: any[]) => h.getLine(...a) }))
vi.mock('@/composables/useRegistryConfig', () => ({ useRegistryConfig: () => h.cfg }))
vi.mock('@/services/api/repoAccount', () => ({ getRepoAccount: () => Promise.resolve({ enabled: false }), linkRepoAccount: vi.fn() }))   // V0667: repository accounts off here: the form as before
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push, replace: vi.fn() }), useRoute: () => ({ params: {}, query: { line: 'lyceum' } }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChangeNew from './CodeChangeNew.vue'
import { CONSOLE_PREFIX } from '@/services/codeChanges/pathRules'

const LINE = { slug: 'lyceum', organization_id: 'org-a', organization_name: 'Lyceum Labs', title: 'Lyceum', release_name: 'V0666_lyceum', open_paths: [CONSOLE_PREFIX + 'views'], state: 'active' }
const mountIt = () => mount(CodeChangeNew, { global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const next = async (w: any) => { await tid(w, 'ccn-next').trigger('click'); await flushPromises() }
const PROBLEM = 'The order page does not say which agent is paid when a firm bids.'
const setCfg = (on: boolean) => { h.cfg = { codeDistributionsEnabled: ref(on), load: vi.fn().mockResolvedValue({}) } }

describe('proposing into a release line', () => {
  beforeEach(() => { setCfg(true); h.getLine = vi.fn().mockResolvedValue(LINE); h.propose = vi.fn().mockResolvedValue({ id: 'cc_9' }); h.push.mockClear() })

  it('names the line, refuses a file outside its open paths, and sends the change with the line named', async () => {
    const w = mountIt(); await flushPromises()
    expect(h.getLine).toHaveBeenCalledWith('lyceum')
    expect(tid(w, 'ccn-line').text()).toContain('V0666_lyceum')
    expect(tid(w, 'ccn-line').text()).toContain('of Lyceum Labs')                                             // the organization by name
    expect(JSON.parse(tid(w, 'ccn-back').attributes('data-to')!)).toEqual({ name: 'contributions', query: { org: 'org-a', line: 'lyceum' } })   // pass 5: back to the line, not the main list
    await tid(w, 'ccn-title').setValue('Show who is paid'); await tid(w, 'ccn-problem').setValue(PROBLEM); await next(w)
    await tid(w, 'ccn-path-input').setValue('stores/guild.ts'); await tid(w, 'ccn-add').trigger('click')
    const row = w.findAll('[data-testid="ccn-path-row"]')[0]
    expect(row.attributes('data-status')).toBe('refused')
    expect(row.text()).toContain('stores/guild.ts is not open in this line (open: views)')
    await tid(w, 'ccn-path-input').setValue('views/AdminPanel.vue'); await tid(w, 'ccn-add').trigger('click')
    expect(tid(w, 'ccn-sensitive-needs').text()).toMatch(/the line's own ballot rule/)                     // never the main line's stricter ballot
    expect(tid(w, 'ccn-sensitive-needs').text()).not.toMatch(/two thirds/)
    await w.findAll('[data-testid="ccn-path-row"]')[1].find('button').trigger('click')                     // pass 3: readable, not the raw prefixes
    await next(w)
    expect(tid(w, 'ccn-step-files').exists()).toBe(true)                    // did not go on with a file outside the line
    await row.find('button').trigger('click')
    await tid(w, 'ccn-path-input').setValue('views/GuildBoard.vue'); await tid(w, 'ccn-add').trigger('click')
    expect(w.findAll('[data-testid="ccn-path-row"]')[0].text()).toContain('Open in this line.')
    await next(w)
    await tid(w, 'ccn-bounty').setValue('5'); await next(w)
    expect(tid(w, 'ccn-after').text()).toMatch(/the line's deciders vote/)                                    // pass 4: a line's steps, not the main line's
    expect(tid(w, 'ccn-after').text()).not.toMatch(/Senate|the members vote/)
    await tid(w, 'ccn-submit').trigger('click'); await flushPromises()
    expect(h.propose).toHaveBeenCalledWith({ repository: 'theprotocol/AgentVault', paths: [CONSOLE_PREFIX + 'views/GuildBoard.vue'], title: 'Show who is paid', problem: PROBLEM,
      code_distribution: 'lyceum', bounty: 5 })
  })

  it('says when the line cannot be read, and proposes nothing', async () => {
    h.getLine = vi.fn().mockRejectedValue({ response: { data: { code: 'not_found', detail: 'no code distribution with that name' } } })
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccn-line-error').text()).toBe('no code distribution with that name')
    expect(tid(w, 'ccn-signin').exists()).toBe(true)
  })

  it('says code distributions are off on this registry, and asks for no line', async () => {
    setCfg(false)
    const w = mountIt(); await flushPromises()
    expect(h.getLine).not.toHaveBeenCalled()
    expect(tid(w, 'ccn-line-error').text()).toBe('Code distributions are off on this registry.')
  })
})
