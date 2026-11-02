import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { computed, ref } from 'vue'

/**
 * V0653 (al) (order gwo_2f0d7d69673b8f9c9392e5dc), the maintainer in the sessions' room (seq 686): the arrow over the chat
 * "just leave[s] the chat and says pick a conversation", and a new approval appeared only small in the side panel ("the
 * pinned version was way more clear to spot"). Inside the shell's two panes the header arrow folds and opens the list
 * and never leaves the thread (on one pane, or outside the shell, it leaves as before); the requests are pinned above
 * the history at every width, compact: one card (the newest that can be decided, or the one a link opened) with
 * "n more" opening the whole list, and on a phone-width pane the one-line strip that opens the card. BASE (V0652): the
 * arrow always left the thread, and on a wide console pane the requests sat only in the side panel, as a list.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  base: '/ourchat',
  presence: vi.fn(),
  push: vi.fn(),
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn(),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', user: { developer_id: 6 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev-tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: () => {} }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref(h.base) }) }
})
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: h.presence } }))
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
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ params: { id: 'room1' }, query: {}, path: '/ourchat/room1' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: h.push, replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'
import { SIDE_PANEL_MIN_PX } from '@/services/chat/sidePanel'
import { OURCHAT_LIST_FOLD } from '@/services/chat/listFold'

const stubs = { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
  ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true }
const text = (id: string, seq: number) => ({ id, seq, kind: 'text', body: `m${seq}`, sender_ptype: 'developer', sender_id: '7',
  sender_name: 'Mira', created_at: '2026-11-01T19:00:00Z' })
const page = (kind: string, messages: unknown[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind,
  my_state: 'active', counterparty: null,
  room: kind === 'org' ? { org_id: 'org1', title: 'TheProtocol Sessions', mode: 'open', topic: null } : undefined })
const item = (n: number) => ({ id: `apr_${n}`, conversation_id: 'room1', status: 'pending', title: `Request ${n}`,
  unlocks: `act ${n}`, reason: `because ${n}`, artifact_sha256: 'ab'.repeat(32),
  requester: { agent_did: 'did:x:aaaaaa', name: 'session-release' }, created_at: `2026-11-01T20:0${n}:00Z`,
  expires_at: '2099-01-01T00:00:00Z' })
const waiting = (n: number) => ({ items: Array.from({ length: n }, (_x, i) => item(i + 1)), can_decide: true, presence: 'off' })

/* the test DOM lays nothing out: the thread pane reports the width a test gives it */
let paneW = 0
const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
class FakeResizeObserver { observe() {} unobserve() {} disconnect() {} }

function fold(twoPane: boolean, folded = false) {
  const f = ref(folded)
  const two = ref(twoPane)
  return { twoPane: two, folded: f, canFold: computed(() => two.value), setUnread: vi.fn(),
    toggle: vi.fn(() => { f.value = !f.value }) }
}
function mountThread(provideFold?: ReturnType<typeof fold>) {
  return mount(PocketOurStateThread, {
    global: { stubs, provide: provideFold ? { [OURCHAT_LIST_FOLD as symbol]: provideFold } : {} },
  })
}

describe('V0653 (al): the arrow, and the requests pinned compact', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.base = '/ourchat'
    h.route.path = '/ourchat/room1'
    h.route.query = {}
    h.push.mockReset().mockResolvedValue(undefined)
    h.presence.mockReset().mockResolvedValue({ organization_id: 'org1', as_of: '', agents: [], count: 0 })
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true,
      get() { return (this as HTMLElement).classList?.contains('ost') ? paneW : 0 } })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    if (desc) Object.defineProperty(HTMLElement.prototype, 'clientWidth', desc)
  })

  it('beside the list (two panes) the arrow folds the list, then opens it again, and never leaves the thread', async () => {
    paneW = 1200
    h.chat.getMessages = vi.fn().mockResolvedValue(page('dm', [text('m1', 1)]))
    const ctl = fold(true)
    const w = mountThread(ctl)
    await flushPromises()
    const back = w.find('[data-testid="ost-back"]')
    expect(back.attributes('data-act')).toBe('fold-list')
    expect(back.attributes('aria-label')).toBe('Fold the conversation list')
    await back.trigger('click')
    expect(ctl.toggle).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="ost-back"]').attributes('data-act')).toBe('open-list')
    expect(w.find('[data-testid="ost-back"]').attributes('aria-label')).toBe('Show the conversation list')
    await w.find('[data-testid="ost-back"]').trigger('click')
    expect(ctl.toggle).toHaveBeenCalledTimes(2)
    expect(h.push).not.toHaveBeenCalled()
    w.unmount()
  })

  it('on one pane (a phone) the arrow leaves the thread for the list, as before', async () => {
    paneW = 393
    h.chat.getMessages = vi.fn().mockResolvedValue(page('dm', [text('m1', 1)]))
    const ctl = fold(false)
    const w = mountThread(ctl)
    await flushPromises()
    const back = w.find('[data-testid="ost-back"]')
    expect(back.attributes('data-act')).toBe('leave')
    expect(back.attributes('aria-label')).toBe('Back')
    await back.trigger('click')
    expect(h.push).toHaveBeenCalledWith('/ourchat')
    expect(ctl.toggle).not.toHaveBeenCalled()
    w.unmount()
  })

  it('outside the shell the arrow leaves, as before', async () => {
    paneW = 1200
    h.chat.getMessages = vi.fn().mockResolvedValue(page('dm', [text('m1', 1)]))
    const w = mountThread()
    await flushPromises()
    await w.find('[data-testid="ost-back"]').trigger('click')
    expect(h.push).toHaveBeenCalledWith('/ourchat')
    w.unmount()
  })

  it('on a wide pane beside the side panel: one card, the newest request, "n more" opens the list with Approve all', async () => {
    paneW = SIDE_PANEL_MIN_PX + 200
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(waiting(3))
    const w = mountThread(fold(true))
    await flushPromises()
    const pinned = w.find('[data-testid="ost-approvals"]')
    expect(pinned.exists()).toBe(true)
    expect(w.find('[data-testid="ost-side"]').element.contains(pinned.element)).toBe(false)
    expect(pinned.attributes('data-view')).toBe('card')
    expect(w.findAll('[data-testid^="oca-item-"]').map((x) => x.attributes('data-testid'))).toEqual(['oca-item-apr_3'])
    expect(w.find('[data-testid="oca-approve-apr_3"]').exists()).toBe(true)
    expect(w.find('[data-testid="oca-deny-apr_3"]').exists()).toBe(true)
    expect(w.find('[data-testid="oca-why-apr_3"]').text()).toContain('because 3')
    expect(w.find('[data-testid="oca-approve-all"]').exists()).toBe(false)   // Approve all sends what is on screen: one card is not all
    expect(w.find('[data-testid="oca-more"]').text()).toBe('2 more')
    expect(w.find('[data-testid="csp-approvals-count"]').text()).toBe('3')
    await w.find('[data-testid="oca-more"]').trigger('click')
    expect(w.find('[data-testid="ost-approvals"]').attributes('data-view')).toBe('list')
    expect(w.findAll('[data-testid^="oca-item-"]')).toHaveLength(3)
    expect(w.find('[data-testid="oca-approve-all"]').exists()).toBe(true)
    await w.find('[data-testid="oca-less"]').trigger('click')
    expect(w.findAll('[data-testid^="oca-item-"]')).toHaveLength(1)
    w.unmount()
  })

  it("the side panel's WAITING ON YOU keeps the count and opens the whole list where it is pinned", async () => {
    paneW = SIDE_PANEL_MIN_PX + 200
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(waiting(2))
    const w = mountThread(fold(true))
    await flushPromises()
    expect(w.find('[data-testid="ost-side-approvals-pinned"]').text()).toBe('2 pinned above the chat')
    await w.find('[data-testid="ost-side-approvals-open"]').trigger('click')
    expect(w.find('[data-testid="ost-approvals"]').attributes('data-view')).toBe('list')
    expect(w.findAll('[data-testid^="oca-item-"]')).toHaveLength(2)
    w.unmount()
  })

  it('a single request on a narrower desktop pane: the card, and no "more"', async () => {
    paneW = 820
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(waiting(1))
    const w = mountThread(fold(true))
    await flushPromises()
    expect(w.find('[data-testid="ost-side"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-approvals"]').attributes('data-view')).toBe('card')
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(true)
    expect(w.find('[data-testid="oca-more"]').exists()).toBe(false)
    w.unmount()
  })

  it('a phone-width pane starts as the one-line strip, which opens the same card, and Hide folds it back', async () => {
    h.base = '/pocket/ourchat'
    h.route.path = '/pocket/ourchat/room1'
    paneW = 393
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(waiting(2))
    const w = mountThread(fold(false))
    await flushPromises()
    expect(w.find('[data-testid="ost-approvals"]').attributes('data-view')).toBe('strip')
    expect(w.find('[data-testid="oca-strip"]').text()).toContain('2 waiting for a decision')
    expect(w.findAll('[data-testid^="oca-item-"]')).toHaveLength(0)
    await w.find('[data-testid="oca-strip"]').trigger('click')
    expect(w.findAll('[data-testid^="oca-item-"]').map((x) => x.attributes('data-testid'))).toEqual(['oca-item-apr_2'])
    expect(w.find('[data-testid="oca-more"]').text()).toBe('1 more')
    await w.find('[data-testid="oca-hide"]').trigger('click')
    expect(w.find('[data-testid="oca-strip"]').exists()).toBe(true)
    w.unmount()
  })

  it('a link that names a request (a push, Pocket Approvals) opens the card on that request, strip or not', async () => {
    h.base = '/pocket/ourchat'
    h.route.path = '/pocket/ourchat/room1'
    h.route.query = { approval: 'apr_1' }
    paneW = 393
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(waiting(2))
    const w = mountThread(fold(false))
    await flushPromises()
    expect(w.find('[data-testid="ost-approvals"]').attributes('data-view')).toBe('card')
    expect(w.findAll('[data-testid^="oca-item-"]').map((x) => x.attributes('data-testid'))).toEqual(['oca-item-apr_1'])
    w.unmount()
  })
})
