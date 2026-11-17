/**
 * V0667 (order gwo_662c03447bcd627afa4a11e5; room seq 5040 "a button on code changes view that links your account"): the Code changes page carries the
 * "Link repository account" button in its hero, beside Propose, for a signed-in developer on a registry where repository accounts are on. A visitor is not asked
 * (the list stays public), a status that could not be read shows no button rather than a wrong one, and after a link the page reads the status again.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ status: null as any, link: null as any, auth: { isAuthenticated: true } as any }))
vi.mock('@/services/api/codeChanges', () => ({ listChanges: () => Promise.resolve([]), getBallot: () => Promise.resolve(null) }))
vi.mock('@/services/api/repoAccount', () => ({ getRepoAccount: (...a: any[]) => h.status(...a), linkRepoAccount: (...a: any[]) => h.link(...a) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))

import CodeChanges from './CodeChanges.vue'

const st = (over: Record<string, any> = {}) => ({ enabled: true, host: 'https://code.theprotocol.cloud', linked: false, username: null, state: null, shares: ['Your username is public.'], pending: null, ...over })
const mountIt = () => mount(CodeChanges, { global: { stubs: { Icon: true, CodeChangesTabs: true, ChangeStepper: true, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the Code changes page and the repository account', () => {
  beforeEach(() => { h.auth = { isAuthenticated: true }; h.link = vi.fn() })

  it('shows the link button in the hero for a signed-in developer who has none', async () => {
    h.status = vi.fn().mockResolvedValue(st())
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ccl-root').find('.ccl-hero [data-testid="ra-open"]').exists()).toBe(true)
  })

  it('never asks a visitor, and a status that could not be read shows no button', async () => {
    h.auth = { isAuthenticated: false }
    h.status = vi.fn().mockResolvedValue(st())
    const v = mountIt(); await flushPromises()
    expect(h.status).not.toHaveBeenCalled()
    expect(tid(v, 'ra-open').exists()).toBe(false)
    h.auth = { isAuthenticated: true }
    h.status = vi.fn().mockRejectedValue(new Error('Network Error'))
    const w = mountIt(); await flushPromises()
    expect(tid(w, 'ra-open').exists()).toBe(false)
  })

  it('reads the status again after a link and then names the account', async () => {
    h.status = vi.fn().mockResolvedValueOnce(st()).mockResolvedValueOnce(st({ linked: true, username: 'ada-builds', state: 'active' }))
    h.link = vi.fn().mockResolvedValue({ username: 'ada-builds', host: 'https://code.theprotocol.cloud', password: 'x', sign_in: 'https://code.theprotocol.cloud/user/login', git_config: 'git config user.email ada-builds@users.code.theprotocol.cloud' })
    const w = mountIt(); await flushPromises()
    await tid(w, 'ra-open').trigger('click')
    await tid(w, 'ra-username').setValue('ada-builds'); await tid(w, 'ra-confirm').setValue(true)
    await tid(w, 'ra-create').trigger('click'); await flushPromises()
    expect(h.status).toHaveBeenCalledTimes(2)
    await tid(w, 'ra-done').trigger('click')
    expect(tid(w, 'ra-linked').text()).toContain('ada-builds')
  })
})
