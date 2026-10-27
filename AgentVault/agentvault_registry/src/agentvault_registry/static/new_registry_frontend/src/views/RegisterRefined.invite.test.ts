/**
 * §FESUITE (V0578): the registration form's invite field defaulted to shown and "(required for beta access)" (its own
 * comment said "hidden until config fetched"). Every visitor saw "required" until /api/v1/auth/registration-config
 * answered, and kept seeing it when that read failed, on frames that register without an invite (the production frames:
 * registration is open there). The field now follows the answer: none while the read is in flight (a link's code is still
 * shown), "required" only where the registry says so, and "(if you have one)" when the read failed.
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({ query: {} as Record<string, string> }))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useRoute: () => ({ query: h.query, params: {} }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ error: null, clearError: vi.fn() }) }))
vi.mock('@/services/api/client', () => ({ apiClient: { post: vi.fn() } }))

import RegisterRefined from './RegisterRefined.vue'

const REQUIRED = '(required for beta access)'
const shell = { template: '<div><slot /></div>' }
const stubs = { AuthShell: shell, NeuralCard: shell, NeuralIcon: true, RouterLink: { template: '<a><slot /></a>' }, 'router-link': { template: '<a><slot /></a>' } }
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })

async function form(fetchAnswer: unknown | 'hang', query: Record<string, string> = {}) {
  h.query = query
  vi.stubGlobal('fetch', vi.fn(() => (fetchAnswer === 'hang' ? new Promise(() => {}) : Promise.resolve(fetchAnswer))))
  const w = mount(RegisterRefined, { global: { stubs } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
// the invite input by its placeholder (the base markup has no testid on it)
const invite = (w: ReturnType<typeof mount>) => w.find('input[placeholder="TP-XXXX-XXXX-XXXX-XXXX"]')

afterEach(() => { vi.unstubAllGlobals() })

describe('the registration form says an invite is required only where the registry said so', () => {
  it('a failed registration-config read never says an invite is required', async () => {
    const w = await form({ ok: false, status: 503, json: async () => ({}) })
    expect(w.text(), 'said "required" over a registration-config read that failed').not.toContain(REQUIRED)
    expect(invite(w).exists()).toBe(true)
    expect(w.text()).toContain('(if you have one)')
  })

  it('while the read is in flight there is no invite field and no "required"', async () => {
    const w = await form('hang')
    expect(w.text(), 'said "required" before registration-config answered').not.toContain(REQUIRED)
    expect(invite(w).exists()).toBe(false)
  })

  it('an open registry shows no invite field; one that requires invites says so', async () => {
    let w = await form(ok({ beta_invite_required: false, email_verification_required: false }))
    expect(invite(w).exists()).toBe(false)
    w.unmount()
    w = await form(ok({ beta_invite_required: true, email_verification_required: true }))
    expect(invite(w).exists()).toBe(true)
    expect(w.text()).toContain(REQUIRED)
  })

  it('a code carried by the link is shown even while the read is in flight', async () => {
    const w = await form('hang', { invite: 'TP-AAAA-BBBB-CCCC-DDDD' })
    expect(w.text(), 'said "required" before registration-config answered').not.toContain(REQUIRED)
    expect(invite(w).exists()).toBe(true)
    expect((invite(w).element as HTMLInputElement).value).toBe('TP-AAAA-BBBB-CCCC-DDDD')
  })
})
