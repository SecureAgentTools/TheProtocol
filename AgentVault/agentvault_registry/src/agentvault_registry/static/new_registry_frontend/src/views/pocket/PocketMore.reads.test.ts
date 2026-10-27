import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): Pocket → More read four settings with "absence, not an error" catches,
 * while every route answers 200 for absence, so a thrown error was a FAILED read drawn as an answer:
 *  - the handle: "not claimed — you are unreachable by name";
 *  - Pulse: "off — your profile shows no activity" (a profile may be publishing);
 *  - Away mode: "off — nobody answers for you", and its whole-value save would drop the fields nobody read;
 *  - contact terms: "open to anyone", and Save then wrote "open" over a priced or contacts-only policy.
 * Each says '—' and its read failed (Try again) and writes nothing until a read answers. Answered reads keep their
 * values and their saves (the control).
 */
const h = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), post: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, put: h.put, post: h.post, delete: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'tok', isAuthenticated: true, logout: vi.fn() }) }))
vi.mock('@/composables/usePocketLock', async () => {
  const { ref } = await import('vue')
  return { usePocketLock: () => ({ enabled: ref(false), available: vi.fn().mockResolvedValue(false), disable: vi.fn(), enroll: vi.fn(),
    vaultInfo: () => ({ sealed: false, method: null }), sealCredentials: vi.fn(), sealCredentialsDeviceKey: vi.fn(), unsealCredentialsToPlain: vi.fn() }) }
})
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { getAllCredentials: () => ({}) } }))
vi.mock('@/views/Tutorials/guided/tourStore', () => ({ useGuidedTourStore: () => ({ start: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined) }), useRoute: () => ({ query: {}, path: '/pocket/more' }) }))

import PocketMore from './PocketMore.vue'

const opts = { global: { stubs: { Icon: true, PocketFrame: true, RouterLink: true, 'router-link': true, Teleport: true, teleport: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const SETTINGS = ['/chat/pulse/me', '/chat/handles/me', '/chat/contact-policy/me', '/developers/me/prefs/pocket.away']
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()
const val = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"] .pm-val`).text()

function routes(fail: boolean) {
  h.get.mockImplementation(async (url: string) => {
    if (fail && SETTINGS.includes(url)) throw failure()
    if (url === '/chat/pulse/me') return { data: { enabled: true, moments: [{ text: 'Settled a guild job' }] } }
    if (url === '/chat/handles/me') return { data: { handle: 'mira' } }
    if (url === '/chat/contact-policy/me') return { data: { policy: 'priced', effective: 'priced', price: '2', currency: 'ECU', purse_did: 'did:theprotocol:p1' } }
    if (url === '/developers/me/prefs/pocket.away') return { data: { value: { enabled: false, note: 'back soon', threads_off: ['c9'] } } }
    if (url === '/developers/me/agents') return { data: [{ did: 'did:theprotocol:p1', name: 'Purse' }] }
    if (url === '/chat/blocks') return { data: { blocks: [] } }
    return { data: {} }
  })
}

describe('Pocket → More says what its settings reads answered, and writes nothing over a failed one', () => {
  beforeEach(() => { h.get.mockReset(); h.put.mockReset().mockResolvedValue({ data: {} }); h.post.mockReset() })

  it('failed reads: no "not claimed", no "off", no "open to anyone"; each says it failed and nothing is written', async () => {
    routes(true)
    const w = mount(PocketMore, opts)
    await flushPromises()
    expect(val(w, 'pm-handle')).toBe('—')
    expect(val(w, 'pm-pulse')).toBe('—')
    expect(val(w, 'pm-away')).toBe('—')
    expect(val(w, 'pm-terms')).toBe('—')
    expect(has(w, 'pm-pulse-unread') && has(w, 'pm-away-unread')).toBe(true)
    // the switches change nothing, and the terms' Save is closed
    await w.find('[data-testid="pm-pulse"]').trigger('click')
    await w.find('[data-testid="pm-away"]').trigger('click')
    await w.find('[data-testid="pm-terms"]').trigger('click')
    await flushPromises()
    expect(has(w, 'pm-terms-unread')).toBe(true)
    expect(w.find('[data-testid="pm-terms-save"]').attributes('disabled')).toBeDefined()
    await w.find('[data-testid="pm-terms-save"]').trigger('click')
    await flushPromises()
    expect(h.put, 'nothing was written over settings nobody read').not.toHaveBeenCalled()
    // Try again reads the terms and opens Save
    routes(false)
    await w.find('[data-testid="pm-terms-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(val(w, 'pm-terms')).toContain('2 ECU')
    expect(w.find('[data-testid="pm-terms-save"]').attributes('disabled')).toBeUndefined()
    w.unmount()
  })

  it('the terms Save over a failed read writes nothing (it wrote "open" over the policy nobody read)', async () => {
    routes(true)
    const w = mount(PocketMore, opts)
    await flushPromises()
    await w.find('[data-testid="pm-terms"]').trigger('click')
    await flushPromises()
    await w.find('[data-testid="pm-terms-save"]').trigger('click')
    await flushPromises()
    expect(h.put.mock.calls.filter((c) => c[0] === '/chat/contact-policy/me')).toEqual([])
    w.unmount()
  })

  it('control: answered reads keep their values; the away save carries the fields it read (threads_off)', async () => {
    routes(false)
    const w = mount(PocketMore, opts)
    await flushPromises()
    expect(val(w, 'pm-handle')).toBe('@mira')
    expect(val(w, 'pm-pulse')).toContain('1 moment')
    expect(val(w, 'pm-terms')).toContain('2 ECU')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    await w.find('[data-testid="pm-away"]').trigger('click')
    await flushPromises()
    const call = h.put.mock.calls.find((c) => c[0] === '/developers/me/prefs/pocket.away')
    expect(call?.[1]?.value?.threads_off).toEqual(['c9'])
    w.unmount()
  })
})
