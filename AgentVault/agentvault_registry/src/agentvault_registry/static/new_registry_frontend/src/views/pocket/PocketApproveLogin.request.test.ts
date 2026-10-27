import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { reactive } from 'vue'

/**
 * §FESUITE (2026-10-10, lifecycle 84): the phone's approve-sign-in screen.
 *  - The next sign-in's notification, tapped while the screen still shows the last one, changes only the query (the
 *    service worker navigates the open window; vue-router keeps the component). The screen read its request once, so
 *    the new request opened on the last one's "Approved" with both buttons disabled. It follows the query now.
 *  - A fingerprint the person does not give (declined, cancelled, timed out: NotAllowedError) sent nothing and showed
 *    the browser's own sentence, logged as a console error. It says so in words and the person can ask again.
 *  - The control: a refusal from the registry is still shown as the registry's words, and logged.
 */
const h = vi.hoisted(() => ({ challenge: vi.fn(), approveDirect: vi.fn(), deny: vi.fn(), sign: vi.fn() }))
const route = reactive({ query: { id: 'lgn_first' } as Record<string, string> })
vi.mock('vue-router', () => ({ useRoute: () => route }))
vi.mock('@/services/api/pushLogin', () => ({ pushLoginApi: { challenge: h.challenge, approveDirect: h.approveDirect, deny: h.deny } }))
vi.mock('@/composables/useDeviceSigner', () => ({ useDeviceSigner: () => ({ supported: true, sign: h.sign }) }))

import PocketApproveLogin from './PocketApproveLogin.vue'

const opts = { global: { stubs: { Icon: true } } }
const soon = () => new Date(Date.now() + 90_000).toISOString()
const assertion = { credential_id: 'c', authenticator_data: 'a', client_data_json: 'j', signature: 's' }

describe('the phone approves the request it is opened for, and says a fingerprint it did not get in words', () => {
  let consoleError: ReturnType<typeof vi.spyOn>
  beforeEach(() => {
    route.query = { id: 'lgn_first' }
    h.challenge.mockReset().mockImplementation(async (id: string) => ({ challenge_hash: `hash-${id}`, requested_ip: '198.51.100.7', expires_at: soon() }))
    h.approveDirect.mockReset().mockResolvedValue({ ok: true, status: 'approved' })
    h.deny.mockReset().mockResolvedValue({ ok: true, status: 'denied' })
    h.sign.mockReset().mockResolvedValue(assertion)
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
  })
  afterEach(() => { consoleError.mockRestore() })

  it('the next request, opened over an approved one, is the one shown and approvable', async () => {
    const w = mount(PocketApproveLogin, opts)
    await flushPromises()
    await w.find('.pal-ok').trigger('click')
    await flushPromises()
    expect(w.find('.pal-msg').text()).toMatch(/approved\. you are signed in on the other device/i)
    expect((w.find('.pal-ok').element as HTMLButtonElement).disabled).toBe(true)

    route.query = { id: 'lgn_second' }          // the next notification, tapped on the open screen
    await flushPromises()
    expect(h.challenge).toHaveBeenLastCalledWith('lgn_second')
    expect(w.find('.pal-msg').exists(), 'nothing of the last request is said').toBe(false)
    expect((w.find('.pal-ok').element as HTMLButtonElement).disabled, 'the new request can be approved').toBe(false)
    await w.find('.pal-ok').trigger('click')
    await flushPromises()
    expect(h.sign).toHaveBeenLastCalledWith('hash-lgn_second')
    expect(h.approveDirect).toHaveBeenLastCalledWith('lgn_second', assertion)
    w.unmount()
  })

  it('a fingerprint not given sends nothing, says so in words, and the person can ask again', async () => {
    h.sign.mockRejectedValueOnce(new DOMException('The operation either timed out or was not allowed. See: https://www.w3.org/TR/webauthn-2/#sec-assertion-privacy.', 'NotAllowedError'))
    const w = mount(PocketApproveLogin, opts)
    await flushPromises()
    await w.find('.pal-ok').trigger('click')
    await flushPromises()
    const said = w.find('.pal-msg').text()
    expect(said).toMatch(/fingerprint was not confirmed, so nothing was sent/i)
    expect(said).not.toMatch(/operation|w3\.org/i)
    expect(h.approveDirect).not.toHaveBeenCalled()
    expect(consoleError, 'the person\'s choice is not a console error').not.toHaveBeenCalled()
    expect((w.find('.pal-ok').element as HTMLButtonElement).disabled).toBe(false)
    await w.find('.pal-ok').trigger('click')
    await flushPromises()
    expect(h.approveDirect).toHaveBeenCalledWith('lgn_first', assertion)
    w.unmount()
  })

  it('control: a refusal from the registry is shown in its words and logged', async () => {
    h.approveDirect.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 401'),
      { response: { status: 401, data: { detail: 'Biometric verification failed (uv_not_set)' } } }))
    const w = mount(PocketApproveLogin, opts)
    await flushPromises()
    await w.find('.pal-ok').trigger('click')
    await flushPromises()
    expect(w.find('.pal-msg').text()).toBe('Biometric verification failed (uv_not_set)')
    expect(consoleError).toHaveBeenCalled()
    w.unmount()
  })
})
