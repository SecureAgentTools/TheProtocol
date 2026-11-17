/**
 * V0667 (order gwo_662c03447bcd627afa4a11e5; room seq 5040 "the flow should be no automatically triggered. Maybe a button on code changes view that links
 * your account", session-lead seq 5047 and 5097): the developer's repository account on the public code host, as the Code changes pages show it.
 *
 *   - nothing on a registry where repository accounts are off, or before the status is known (the parent reads it)
 *   - not linked: one button, "Link repository account". Mounting it or opening it never creates anything; the press shows WHAT THE ACCOUNT SHARES first (the
 *     registry's list, every sentence), then the username and a confirmation, and "Create the account" stays grey until both are there
 *   - the create answers the one-time password, where to sign in and the one git line for the author e-mail, shown once; closing the panel forgets the password
 *   - a refusal is the registry's sentence, word for word, and creates nothing on screen
 *   - linked: the username on the host; paused or closed says so; a leg that waits says its reason and next try
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ link: null as any }))
vi.mock('@/services/api/repoAccount', () => ({ linkRepoAccount: (...a: any[]) => h.link(...a) }))

import RepoAccountLink from './RepoAccountLink.vue'

const SHARES = [
  'Your username on code.theprotocol.cloud, which you choose here.',
  'The forks and branches you push are public.',
  'Your git writes its configured e-mail into every commit.',
]
const status = (over: Record<string, any> = {}) => ({ enabled: true, host: 'https://code.theprotocol.cloud', linked: false, username: null, state: null, shares: SHARES, pending: null, terms_version: '2.6', ...over })
const LINKED = { username: 'ada-builds', host: 'https://code.theprotocol.cloud', password: 'one-time-Pw-1', sign_in: 'https://code.theprotocol.cloud/user/login',
  change_password_on_first_sign_in: true, git_config: 'git config user.email ada-builds@users.code.theprotocol.cloud' }
const mountIt = (st: any) => mount(RepoAccountLink, { props: { status: st }, global: { stubs: { Icon: true, RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' } } } })
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

describe('the repository account link', () => {
  beforeEach(() => { h.link = vi.fn() })

  it('shows nothing while the status is unknown or where repository accounts are off', async () => {
    expect(mountIt(null).find('[data-testid="ra-root"]').exists()).toBe(false)
    expect(mountIt(status({ enabled: false })).find('[data-testid="ra-root"]').exists()).toBe(false)
  })

  it('not linked: one button; mounting or opening creates nothing, and the press shows every sentence of what is shared before the username and the confirmation', async () => {
    const w = mountIt(status()); await flushPromises()
    expect(tid(w, 'ra-open').text()).toBe('Link repository account')
    expect(tid(w, 'ra-panel').exists()).toBe(false)
    await tid(w, 'ra-open').trigger('click')
    expect(h.link).not.toHaveBeenCalled()
    const panel = tid(w, 'ra-panel')
    expect(w.findAll('[data-testid="ra-share"]').map((s) => s.text())).toEqual(SHARES)
    const html = panel.html()
    expect(html.indexOf('data-testid="ra-shares"')).toBeLessThan(html.indexOf('data-testid="ra-username"'))
    expect(html.indexOf('data-testid="ra-username"')).toBeLessThan(html.indexOf('data-testid="ra-confirm"'))
  })

  it('"Create the account" stays grey until a valid username and the confirmation are both there, and says what the username lacks', async () => {
    const w = mountIt(status()); await tid(w, 'ra-open').trigger('click')
    expect(tid(w, 'ra-create').attributes('disabled')).toBeDefined()
    await tid(w, 'ra-username').setValue('Ada_Builds')
    expect(tid(w, 'ra-username-note').text()).toMatch(/3 to 39 lowercase letters, digits and single hyphens/)
    await tid(w, 'ra-confirm').setValue(true)
    expect(tid(w, 'ra-create').attributes('disabled')).toBeDefined()
    await tid(w, 'ra-username').setValue('ada-builds')
    expect(tid(w, 'ra-username-note').exists()).toBe(false)
    expect(tid(w, 'ra-create').attributes('disabled')).toBeUndefined()
    await tid(w, 'ra-confirm').setValue(false)
    expect(tid(w, 'ra-create').attributes('disabled')).toBeDefined()
    await tid(w, 'ra-create').trigger('click')
    expect(h.link).not.toHaveBeenCalled()
  })

  it('creates on the press: the one-time password, where to sign in and the git line, once; it tells the page; closing forgets the password', async () => {
    h.link = vi.fn().mockResolvedValue(LINKED)
    const w = mountIt(status()); await tid(w, 'ra-open').trigger('click')
    await tid(w, 'ra-username').setValue('ada-builds'); await tid(w, 'ra-confirm').setValue(true)
    await tid(w, 'ra-create').trigger('click'); await flushPromises()
    expect(h.link).toHaveBeenCalledWith('ada-builds', '2.6')
    expect(tid(w, 'ra-password').text()).toBe('one-time-Pw-1')
    expect(tid(w, 'ra-once').text()).toMatch(/shown once/)
    expect(tid(w, 'ra-signin').attributes('href')).toBe('https://code.theprotocol.cloud/user/login')
    expect(tid(w, 'ra-git').text()).toBe('git config user.email ada-builds@users.code.theprotocol.cloud')
    expect(w.emitted('linked')).toHaveLength(1)
    await tid(w, 'ra-done').trigger('click')
    expect(w.html()).not.toContain('one-time-Pw-1')
  })

  it('a refusal is the registry\'s sentence, word for word, and no password is shown', async () => {
    h.link = vi.fn().mockRejectedValue({ response: { status: 409, data: { code: 'username_taken', detail: 'that username is taken: choose another' } } })
    const w = mountIt(status()); await tid(w, 'ra-open').trigger('click')
    await tid(w, 'ra-username').setValue('ada-builds'); await tid(w, 'ra-confirm').setValue(true)
    await tid(w, 'ra-create').trigger('click'); await flushPromises()
    expect(tid(w, 'ra-error').text()).toBe('that username is taken: choose another')
    expect(tid(w, 'ra-password').exists()).toBe(false)
    expect(w.emitted('linked')).toBeUndefined()
  })

  it('linked: the username on the host, with no button; paused and closed say so; a waiting leg says its reason and next try', async () => {
    const w = mountIt(status({ linked: true, username: 'ada-builds', state: 'active' }))
    expect(tid(w, 'ra-open').exists()).toBe(false)
    expect(tid(w, 'ra-linked').text()).toContain('ada-builds')
    expect(tid(w, 'ra-linked').find('a').attributes('href')).toBe('https://code.theprotocol.cloud/ada-builds')
    const p = mountIt(status({ linked: true, username: 'ada-builds', state: 'paused' }))
    expect(tid(p, 'ra-state').text()).toMatch(/paused while your developer account is suspended/)
    const c = mountIt(status({ linked: true, username: 'ada-builds', state: 'closed' }))
    expect(tid(c, 'ra-state').text()).toMatch(/closed/)
    const q = mountIt(status({ linked: true, username: 'ada-builds', state: 'active',
      pending: { op: 'pause', attempts: 2, last_error: 'the code host did not answer', last_attempt_at: '2026-11-16T01:00:00Z', next_attempt_at: '2026-11-16T01:02:00Z', stuck: false } }))
    expect(tid(q, 'ra-pending').text()).toContain('the code host did not answer')
    expect(tid(q, 'ra-pending').text()).toContain('2026-11-16 01:02')
  })

  it('the press accepts the Terms served now: the panel names the version beside the confirmation and links to them', async () => {
    // session-lead room seq 5175 (Terms § 10.2): whoever presses Link repository account accepts the Terms at the press
    const w = mountIt(status()); await tid(w, 'ra-open').trigger('click')
    expect(tid(w, 'ra-terms').text()).toMatch(/accepts the Terms, version 2\.6/)
    expect(JSON.parse(tid(w, 'ra-terms').find('a').attributes('data-to'))).toEqual({ name: 'legal', params: { page: 'terms' } })
    const html = tid(w, 'ra-panel').html()
    expect(html.indexOf('data-testid="ra-terms"')).toBeLessThan(html.indexOf('data-testid="ra-create"'))
  })
})

describe('the repository account link, given its link by the parent (V0667 the passport: a contributor links through their home)', () => {
  beforeEach(() => { h.link = vi.fn() })

  it('calls the given link with the username and the Terms version, never the member link', async () => {
    const given = vi.fn(async () => LINKED)
    const w = mount(RepoAccountLink, { props: { status: status(), link: given }, global: { stubs: { Icon: true } } })
    await flushPromises()
    await tid(w, 'ra-open').trigger('click')
    await tid(w, 'ra-username').setValue('ada-builds')
    await tid(w, 'ra-confirm').setValue(true)
    await tid(w, 'ra-create').trigger('click'); await flushPromises()
    expect(given).toHaveBeenCalledWith('ada-builds', status().terms_version)
    expect(h.link).not.toHaveBeenCalled()
    expect(w.emitted('linked')).toBeTruthy()
  })
})
