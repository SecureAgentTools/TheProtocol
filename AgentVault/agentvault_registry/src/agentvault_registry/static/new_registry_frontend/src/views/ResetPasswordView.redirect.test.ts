/**
 * §FESUITE (V0594): after a reset, the page says "Redirecting to login in 3 seconds" and set a timer nothing cancelled.
 * A person who left at once (the button, then signing in within the 3 s) had the timer push /login over the navigation
 * the sign-in had started: the dashboard never opened and the person sat on the login form, signed in, told nothing
 * (lifecycle 85 on sbxalphaop fes-20261011T063020Z-6967: login 200, the dashboard's chunks loaded, the hash stayed
 * #/login). The timer now belongs to the page: leaving it cancels the redirect; staying still redirects.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ push: vi.fn(async () => {}), resetPassword: vi.fn(async () => true) }))
vi.mock('vue-router', () => ({
  useRoute: () => reactive({ name: 'reset-password', query: { token: 'tok' } }),
  useRouter: () => ({ push: h.push, replace: vi.fn(async () => {}) }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => reactive({ error: null, resetPassword: h.resetPassword }) }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }) }))

import ResetPasswordView from './ResetPasswordView.vue'

const STRONG = 'Aa1!aaaaaaaaaa'

async function resetDone() {
  const w = mount(ResetPasswordView, {
    global: { stubs: { AuthShell: { template: '<div><slot /></div>' }, Icon: true, RouterLink: true } },
  })
  const pw = w.findAll('input')
  expect(pw.length, 'the reset form has its two password fields').toBeGreaterThanOrEqual(2)
  await pw[0].setValue(STRONG)
  await pw[1].setValue(STRONG)
  await w.find('form').trigger('submit')
  for (let i = 0; i < 3; i++) await flushPromises()
  expect(h.resetPassword).toHaveBeenCalledWith('tok', STRONG)
  return w
}

const pushedToLogin = () => h.push.mock.calls.filter((c: unknown[]) => c[0] === '/login').length

describe('the reset page\'s redirect to login', () => {
  beforeEach(() => { h.push.mockClear(); h.resetPassword.mockClear(); vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }) })
  afterEach(() => { vi.useRealTimers() })

  it('a page left before the 3 s never pushes /login afterwards', async () => {
    const w = await resetDone()
    w.unmount() // the person left: the button, or a sign-in begun at once
    vi.advanceTimersByTime(3500)
    expect(pushedToLogin(), 'the timer of a page already left pushed /login over whatever came next').toBe(0)
  })

  it('a page still open redirects to login after 3 s', async () => {
    const w = await resetDone()
    vi.advanceTimersByTime(2900)
    expect(pushedToLogin()).toBe(0)
    vi.advanceTimersByTime(200)
    expect(pushedToLogin(), 'the redirect the page promises').toBe(1)
    w.unmount()
  })
})
