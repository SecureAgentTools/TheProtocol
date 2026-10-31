import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0650 (l): in an org room the approvals panel is pinned ABOVE the history, outside the message scroll, so the
 * messages move underneath it (his words: "it should stay locked above the chat window"); an approval card arriving
 * in the thread refreshes it; a direct thread has no panel. BASE (V0649): no panel exists.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: null as null | { onMessage: (env: any) => void },
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
vi.mock('@/composables/useChatStream', () => ({ useChatStream: (o: any) => { h.stream = o } }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourchat') }) }
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
vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ params: { id: 'room1' }, query: {}, path: '/pocket/ourchat/room1' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true },
  },
}
const text = (id: string, seq: number) => ({ id, seq, kind: 'text', body: `m${seq}`, sender_ptype: 'developer', sender_id: '7',
  sender_name: 'Mira', created_at: '2026-10-31T03:00:00Z' })
const page = (kind: string, messages: unknown[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind,
  my_state: 'active', counterparty: null })
const pending = { items: [{ id: 'apr_1', conversation_id: 'room1', status: 'pending', title: 'Roll V0649',
  requester: { agent_did: 'did:x:aaaaaa', name: 'session-release' }, created_at: '2026-10-31T03:50:00Z',
  expires_at: '2099-01-01T00:00:00Z' }], can_decide: true, presence: 'off' }

describe('approvals stay pinned above the thread', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.stream = null
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('in an org room the panel sits before the message scroll and outside it', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1), text('m2', 2)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const panel = w.find('[data-testid="ost-approvals"]')
    const scroll = w.find('[data-testid="ost-messages"]')
    expect(panel.exists() && scroll.exists()).toBe(true)
    expect(scroll.element.contains(panel.element), 'the panel is not inside the scroll').toBe(false)
    expect(panel.element.compareDocumentPosition(scroll.element) & Node.DOCUMENT_POSITION_FOLLOWING,
      'the scroll comes after the panel').toBeTruthy()
    w.unmount()
  })

  it('an approval card arriving in the thread refreshes the panel', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const before = h.chat.listApprovals.mock.calls.length
    h.stream!.onMessage({ conversation_id: 'room1', message: { id: 'm9', seq: 9, kind: 'card', sender_ptype: 'developer',
      sender_id: '6', card: { v: 1, type: 'approval.decided', data: { approval_id: 'apr_1', decision: 'approved' } } } })
    await flushPromises()
    expect(h.chat.listApprovals.mock.calls.length).toBeGreaterThan(before)
    w.unmount()
  })

  it('a direct thread has no approvals panel and never asks for one', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page('dm', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-approvals"]').exists()).toBe(false)
    expect(h.chat.listApprovals).not.toHaveBeenCalled()
    w.unmount()
  })
})
