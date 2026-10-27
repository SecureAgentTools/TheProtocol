import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §COCKPITDESK (2026-10-15): the OurChat thread reads for the thread on screen. Switching threads while the first
 * thread's messages were in flight let them land under the second: painted there, written into the second thread's
 * device cache, and the second thread marked read up to the first thread's last message.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  putThread: vi.fn(),
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: h.putThread, dropThread: vi.fn(),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'tok', user: { developer_id: 1 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: () => {} }))
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
  h.route = reactive({ params: { id: 'cA' }, query: {}, path: '/pocket/ourchat/cA' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}
const msg = (id: string, seq: number, body: string) => ({ id, seq, kind: 'text', body, sender_kind: 'developer', sender_id: 2,
  sender_name: 'Mira', created_at: '2026-10-15T03:00:00Z' })
const page = (messages: unknown[], last: number) => ({ messages, last_seq: last, page_bound: 40, kind: 'dm', my_state: 'active',
  counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

describe('the OurChat thread reads for the thread on screen', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.putThread.mockReset().mockResolvedValue(false)
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it("thread A's messages landing after the switch to B are not painted, cached or marked read under B", async () => {
    h.route.params.id = 'cA'
    const slowA = deferred<unknown>()
    h.chat.getMessages = vi.fn((_tok: string, id: string) =>
      id === 'cA' ? slowA.promise : Promise.resolve(page([msg('b1', 3, 'hello from B')], 3)))
    h.chat.markRead = vi.fn().mockResolvedValue({})
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    h.route.params.id = 'cB'                       // the person opens thread B while A is still being read
    await flushPromises()
    expect(w.text()).toContain('hello from B')
    slowA.resolve(page([msg('a1', 98, 'secret of A'), msg('a2', 99, 'more of A')], 99))
    await flushPromises()
    expect(w.text(), "A's messages are never painted under B").not.toContain('secret of A')
    expect(w.text()).toContain('hello from B')
    for (const [id, messages] of h.putThread.mock.calls) {
      if (id === 'cB') expect((messages as { id: string }[]).map((m) => m.id), "B's cache holds B's messages").toEqual(['b1'])
    }
    expect(h.chat.markRead.mock.calls.filter((c) => c[1] === 'cB').map((c) => c[2]), 'B is read up to its own last message')
      .toEqual([3])
    w.unmount()
  })
})
