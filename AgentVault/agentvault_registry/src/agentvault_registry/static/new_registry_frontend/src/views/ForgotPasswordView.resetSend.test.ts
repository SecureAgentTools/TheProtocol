import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-10, lifecycle 85): Forgot password said "TRANSMISSION DISPATCHED" for a request that got no answer
 * and for the registry's own limit (3 a minute, a 429): nothing was sent and the person waited for a mail that could
 * not come. The registry answers every address alike (200), so a failure reveals nothing about an account. Now: no
 * answer says it could not be sent, the limit says to wait; the answered request is the control (still "dispatched").
 */
const h = vi.hoisted(() => ({ reset: vi.fn() }))
vi.mock('@/services/api/auth', () => ({ authApi: { requestPasswordReset: h.reset } }))
vi.mock('@/services/api/client', () => ({ apiClient: { post: vi.fn(), get: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({}) }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {} }), useRouter: () => ({ push: vi.fn() }) }))

import ForgotPasswordView from './ForgotPasswordView.vue'

const opts = { global: { stubs: { AuthShell: { template: '<div><slot /></div>' }, NeuralIcon: true, RouterLink: true, 'router-link': true } } }
const answered = (status: number, data: unknown = {}) =>
  Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data } })

async function ask(w: ReturnType<typeof mount>) {
  await w.find('input[placeholder="agent@example.com"]').setValue('person@example.com')
  await w.find('form').trigger('submit')
  await flushPromises()
}

describe('a reset request that was not answered is not called sent', () => {
  beforeEach(() => { h.reset.mockReset() })

  it('no answer: it could not be sent, try again', async () => {
    h.reset.mockRejectedValue(new Error('Network Error'))
    const w = mount(ForgotPasswordView, opts)
    await ask(w)
    expect(w.text()).not.toMatch(/dispatched|a reset link has been sent/i)
    expect(w.find('.nc-field-error').text()).toMatch(/could not be sent.*try again/i)
  })

  it('the registry\'s limit: wait a minute', async () => {
    h.reset.mockRejectedValue(answered(429, { error: 'Rate limit exceeded: 3 per 1 minute' }))
    const w = mount(ForgotPasswordView, opts)
    await ask(w)
    expect(w.text()).not.toMatch(/dispatched/i)
    expect(w.find('.nc-field-error').text()).toMatch(/too many reset requests.*wait a minute/i)
  })

  it('control: an answered request is dispatched, whatever the address', async () => {
    h.reset.mockResolvedValue({ message: 'If that email is registered, a password reset link has been sent.' })
    const w = mount(ForgotPasswordView, opts)
    await ask(w)
    expect(w.text()).toMatch(/a reset link has been sent/i)
  })
})
