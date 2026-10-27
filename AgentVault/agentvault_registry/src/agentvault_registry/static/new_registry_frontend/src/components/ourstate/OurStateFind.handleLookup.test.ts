import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): OurChat's Find sheet, "By handle". "No account carries the handle @x."
 * was said ONLY when nothing answered: an answered error showed its own detail, and a lookup that never reached the
 * registry (fetch threw, no status) fell through to the "no account" words. A 404 says no account now; no answer or the
 * registry's own failure (5xx) says the lookup failed, with Try again; a found handle shows its profile (the control).
 */
const h = vi.hoisted(() => ({ handleProfile: vi.fn(), discover: vi.fn() }))
vi.mock('@/services/api/chat', () => ({ chatApi: { handleProfile: h.handleProfile, createConversation: vi.fn() } }))
vi.mock('@/services/api/discovery', () => ({ discoveryService: { discover: h.discover } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'tok' }) }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourstate') }) }
})
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, path: '/pocket/ourstate' }),
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
}))

import OurStateFind from './OurStateFind.vue'

const opts = { global: { stubs: { Icon: true, UserAvatar: true, OurStateIdentity: true, Teleport: true, teleport: true } } }
const answered = (status: number, detail: string) => Object.assign(new Error(detail), { status, detail })
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()

async function lookUp(w: ReturnType<typeof mount>, handle: string) {
  await w.find('[data-testid="os-find-lane-person"]').trigger('click')
  await w.find('[data-testid="os-find-handle"]').setValue(handle)
  await w.find('[data-testid="os-find-lookup"]').trigger('click')
  await flushPromises()
}

describe('the handle lookup tells no account from no answer', () => {
  beforeEach(() => {
    h.handleProfile.mockReset()
    h.discover.mockReset().mockResolvedValue({ results: [], total: 0, has_more: false, facets: null })
  })

  for (const [what, err] of [
    ['no answer at all', () => new TypeError('Failed to fetch')],
    ['the registry failed (502)', () => answered(502, 'HTTP 502')],
  ] as const) {
    it(`${what}: the lookup says it failed, never "No account carries the handle"`, async () => {
      h.handleProfile.mockRejectedValueOnce(err())
      const w = mount(OurStateFind, opts)
      await flushPromises()
      await lookUp(w, '@mira')
      expect(w.text()).not.toContain('No account carries the handle')
      expect(has(w, 'os-find-handle-unread')).toBe(true)
      h.handleProfile.mockResolvedValueOnce({ handle: 'mira', display_name: 'Mira', visibility: 'public' })
      await w.find('[data-testid="os-find-handle-unread"] [data-testid="read-failed-retry"]').trigger('click')
      await flushPromises()
      expect(has(w, 'os-find-handle-unread')).toBe(false)
      expect(has(w, 'os-find-profile')).toBe(true)
      w.unmount()
    })
  }

  it('control: a 404 says no account carries the handle; a found handle shows its profile', async () => {
    h.handleProfile.mockRejectedValueOnce(answered(404, 'Handle not found'))
    const w = mount(OurStateFind, opts)
    await flushPromises()
    await lookUp(w, '@nobody')
    expect(w.find('[data-testid="os-find-handle-err"]').text()).toContain('No account carries the handle @nobody')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    h.handleProfile.mockResolvedValueOnce({ handle: 'mira', display_name: 'Mira', visibility: 'public' })
    await lookUp(w, '@mira')
    expect(has(w, 'os-find-profile')).toBe(true)
    w.unmount()
  })
})
