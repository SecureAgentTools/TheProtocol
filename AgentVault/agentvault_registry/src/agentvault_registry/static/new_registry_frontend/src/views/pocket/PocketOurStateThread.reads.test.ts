import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the OurChat thread over three reads that failed silently.
 *  - the CONSENT BANNER ("Support can review this conversation", commented "Never covert"): a failed grants read
 *    removed it, which told every participant that the desk could not read the thread;
 *  - "Load older": a failed read set hasOlder false, so the button went away as if the thread's start was reached;
 *  - the support ticket's attach picker: a failed read of your conversations left it empty, saying nothing.
 * Each says its read failed now (Try again); answered reads keep their banner, button and choices (the control).
 */
const h = vi.hoisted(() => ({ chat: {} as Record<string, ReturnType<typeof vi.fn>>, route: { params: { id: 'c1' }, query: {}, path: '/pocket/ourstate/c1' } }))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
// no stray network: every other rail answers "absent" (the view treats a 404 as nothing to show)
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn(),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'tok', user: { developer_id: 1 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: () => {} }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourstate') }) }
})
vi.mock('@/composables/usePocketAgent', async () => {
  const { ref } = await import('vue')
  return { usePocketAgent: () => ({ credAgents: ref([]), ensureAgentFor: vi.fn().mockResolvedValue(null), noAgentReason: ref(''), sealedLocked: ref(false) }) }
})
vi.mock('@/composables/usePocketLock', async () => {
  const { ref } = await import('vue')
  return { usePocketLock: () => ({ enabled: ref(false), verify: vi.fn().mockResolvedValue(true) }) }
})
vi.mock('@/composables/useActingContext', async () => {
  const { ref } = await import('vue')
  return { useActingContext: () => ({ actingCurrencyLabel: ref('ECU') }) }
})
vi.mock('vue-router', () => ({
  useRoute: () => h.route,
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
}))

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}
const failed = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const msg = (seq: number) => ({ id: `m${seq}`, seq, kind: 'text', body: `line ${seq}`, sender_kind: 'developer', sender_id: 2,
  sender_name: 'Mira', created_at: '2026-10-05T10:00:00Z' })
const PAGE = (kind = 'dm') => ({ messages: [msg(5), msg(6)], last_seq: 6, page_bound: 2, kind, my_state: 'active',
  counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
const GRANT = { grant_id: 'g1', live: true, ticket_id: 7, granted_by_name: 'Mira', granted_by_me: false }
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()

describe('the OurChat thread says what its consent, history and attach reads answered', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route = { params: { id: 'c1' }, query: {}, path: '/pocket/ourstate/c1' }
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })

  afterEach(() => { vi.unstubAllGlobals() })

  it('a failed grants read: the consent check says it failed, never a thread nobody else can read', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(PAGE())
    h.chat.reviewState = vi.fn().mockRejectedValue(failed())
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(has(w, 'cd-review-unread'), 'the consent check says it failed').toBe(true)
    h.chat.reviewState.mockResolvedValue({ grants: [GRANT] })
    await w.find('[data-testid="cd-review-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(has(w, 'cd-review-unread')).toBe(false)
    expect(has(w, 'cd-review-banner'), 'the banner the answer holds').toBe(true)
    w.unmount()
  })

  it('a failed older read keeps the history open and says so; an answer adds the older messages', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(PAGE())
    h.chat.reviewState = vi.fn().mockResolvedValue({ grants: [] })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('button.ost-older').exists(), 'Load older is offered').toBe(true)
    h.chat.getMessages.mockRejectedValueOnce(failed())
    await w.find('button.ost-older').trigger('click')
    await flushPromises()
    expect(has(w, 'ost-older-unread'), 'the older read says it failed').toBe(true)
    h.chat.getMessages.mockResolvedValueOnce({ messages: [msg(3), msg(4)], page_bound: 2 })
    await w.find('[data-testid="ost-older-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(has(w, 'ost-older-unread')).toBe(false)
    expect(w.text()).toContain('line 3')
    w.unmount()
  })

  it('the attach picker: a failed read of your conversations says so', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(PAGE('support'))
    h.chat.supportState = vi.fn().mockResolvedValue({ status: 'open', ticket_id: 7 })
    h.chat.listConversations = vi.fn().mockRejectedValue(failed())
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const det = w.find('[data-testid="cd-review-attach"]')
    expect(det.exists(), 'the attach flow is offered on an open ticket').toBe(true)
    await det.trigger('toggle')
    await flushPromises()
    expect(has(w, 'cd-review-pick-unread')).toBe(true)
    w.unmount()
  })

  it('control: answered reads keep their words (no grants, no banner; a grant, the banner; the history; the choices)', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(PAGE())
    h.chat.reviewState = vi.fn().mockResolvedValue({ grants: [] })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(has(w, 'cd-review-banner') || has(w, 'cd-review-unread')).toBe(false)
    h.chat.getMessages.mockResolvedValueOnce({ messages: [], page_bound: 2 })
    await w.find('button.ost-older').trigger('click')
    await flushPromises()
    expect(w.find('button.ost-older').exists(), 'an answered empty page ends the history').toBe(false)
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
    h.chat.reviewState = vi.fn().mockResolvedValue({ grants: [GRANT] })
    h.chat.getMessages = vi.fn().mockResolvedValue(PAGE())
    const w2 = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(has(w2, 'cd-review-banner')).toBe(true)
    w2.unmount()
  })
})
