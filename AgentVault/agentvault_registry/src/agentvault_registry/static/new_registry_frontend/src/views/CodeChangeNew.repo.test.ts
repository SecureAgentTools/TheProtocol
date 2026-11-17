/**
 * V0667 (order gwo_662c03447bcd627afa4a11e5; session-lead seq 5047 #2: "Submit grey until linked"): with repository accounts on, Propose stays grey until the
 * developer's repository account is linked and active, and the review says why with the link button in place (the same one the Code changes page shows). Linking
 * there reads the status again and Propose turns on. With the switch off the form is as before; a status that could not be read greys nothing (the registry
 * decides, and its refusal sentence is shown as any other).
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ propose: null as any, status: null as any, link: null as any, push: vi.fn(), auth: { isAuthenticated: true, activeAgent: { did: 'did:a:me' } as any } }))
vi.mock('@/services/api/codeChanges', async () => ({ ...(await vi.importActual<any>('@/services/api/codeChanges')), proposeChange: (...a: any[]) => h.propose(...a) }))
vi.mock('@/services/api/repoAccount', () => ({ getRepoAccount: (...a: any[]) => h.status(...a), linkRepoAccount: (...a: any[]) => h.link(...a) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: h.push, replace: vi.fn() }), useRoute: () => ({ params: {}, query: {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChangeNew from './CodeChangeNew.vue'

const st = (over: Record<string, any> = {}) => ({ enabled: true, host: 'https://code.theprotocol.cloud', linked: false, username: null, state: null, shares: ['Your username is public.'], pending: null, ...over })
const mountIt = () => mount(CodeChangeNew, { global: { stubs: { Icon: true, CodeChangesTabs: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const next = async (w: any) => { await tid(w, 'ccn-next').trigger('click'); await flushPromises() }
async function toReview(w: any) {
  await tid(w, 'ccn-title').setValue('Show who is paid'); await tid(w, 'ccn-problem').setValue('The order page does not say which agent is paid when a firm bids.'); await next(w)
  await tid(w, 'ccn-path-input').setValue('views/GuildBoard.vue'); await tid(w, 'ccn-add').trigger('click'); await next(w)
  await tid(w, 'ccn-bounty').setValue('5'); await next(w)
}

describe('Propose and the repository account', () => {
  beforeEach(() => { h.auth = { isAuthenticated: true, activeAgent: { did: 'did:a:me' } }; h.propose = vi.fn().mockResolvedValue({ id: 'cc_7' }); h.link = vi.fn(); h.push.mockClear() })

  it('greys Propose while the account is not linked, says why and shows the link button; linking turns it on', async () => {
    h.status = vi.fn().mockResolvedValueOnce(st()).mockResolvedValueOnce(st({ linked: true, username: 'ada-builds', state: 'active' }))
    h.link = vi.fn().mockResolvedValue({ username: 'ada-builds', host: 'https://code.theprotocol.cloud', password: 'x', sign_in: 'https://code.theprotocol.cloud/user/login', git_config: 'git config user.email ada-builds@users.code.theprotocol.cloud' })
    const w = mountIt(); await flushPromises(); await toReview(w)
    expect(tid(w, 'ccn-submit').attributes('disabled')).toBeDefined()
    expect(tid(w, 'ccn-repo-needed').text()).toMatch(/repository account/)
    await tid(w, 'ra-open').trigger('click')
    await tid(w, 'ra-username').setValue('ada-builds'); await tid(w, 'ra-confirm').setValue(true)
    await tid(w, 'ra-create').trigger('click'); await flushPromises()
    expect(h.status).toHaveBeenCalledTimes(2)
    expect(tid(w, 'ccn-repo-needed').exists()).toBe(false)
    expect(tid(w, 'ccn-submit').attributes('disabled')).toBeUndefined()
    await tid(w, 'ccn-submit').trigger('click'); await flushPromises()
    expect(h.propose).toHaveBeenCalledTimes(1)
  })

  it('a paused account greys Propose and says it is paused', async () => {
    h.status = vi.fn().mockResolvedValue(st({ linked: true, username: 'ada-builds', state: 'paused' }))
    const w = mountIt(); await flushPromises(); await toReview(w)
    expect(tid(w, 'ccn-submit').attributes('disabled')).toBeDefined()
    expect(tid(w, 'ccn-repo-needed').text()).toMatch(/paused/)
  })

  it('with repository accounts off, Propose is as before', async () => {
    h.status = vi.fn().mockResolvedValue(st({ enabled: false }))
    const w = mountIt(); await flushPromises(); await toReview(w)
    expect(tid(w, 'ccn-repo-needed').exists()).toBe(false)
    expect(tid(w, 'ccn-submit').attributes('disabled')).toBeUndefined()
  })

  it('a status that could not be read greys nothing: the registry decides and its sentence is shown', async () => {
    h.status = vi.fn().mockRejectedValue(new Error('Network Error'))
    h.propose = vi.fn().mockRejectedValue({ response: { status: 409, data: { code: 'repo_account_required', detail: 'a code change needs your repository account: press Link repository account on the Code changes page first' } } })
    const w = mountIt(); await flushPromises(); await toReview(w)
    expect(tid(w, 'ccn-submit').attributes('disabled')).toBeUndefined()
    await tid(w, 'ccn-submit').trigger('click'); await flushPromises()
    expect(tid(w, 'ccn-error').text()).toMatch(/press Link repository account/)
  })

  it('a visitor who is not signed in is never asked about a repository account', async () => {
    h.auth = { isAuthenticated: false, activeAgent: null }
    h.status = vi.fn().mockResolvedValue(st())
    const w = mountIt(); await flushPromises()
    expect(h.status).not.toHaveBeenCalled()
    expect(tid(w, 'ccn-repo-needed').exists()).toBe(false)
  })
})
