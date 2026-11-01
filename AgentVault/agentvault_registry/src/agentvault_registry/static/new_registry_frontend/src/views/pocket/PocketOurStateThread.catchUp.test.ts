import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (ag) (order gwo_647f50fd40c19f6f685d0c8e): a thread opens at the first message you have not read, under a NEW
 * line, and catches up by itself when the window gets focus (merged by seq: nothing twice). The header says live.
 * BASE (V0651): no NEW line (the thread opened at the end and marked everything read), and a focus did nothing.
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
vi.mock('@/composables/useChatStream', async () => {
  const { ref } = await import('vue')
  return { useChatStream: () => ({ isConnected: ref(true), disconnect: () => {} }) }
})
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
const msg = (seq: number) => ({ id: `m${seq}`, seq, kind: 'text', body: `line ${seq}`, sender_ptype: 'developer', sender_id: 2,
  sender_name: 'Mira', created_at: `2026-10-31T20:${String(seq).padStart(2, '0')}:00Z` })
const page = (seqs: number[], lastRead: number) => ({ messages: seqs.map(msg), last_seq: seqs[seqs.length - 1] || 0, page_bound: 40,
  kind: 'dm', my_state: 'active', my_last_read_seq: lastRead, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
const order = (w: any) => [...w.element.querySelectorAll('[data-testid="ost-unread-line"], [data-testid^="ost-msg-"]')]
  .map((e: any) => e.getAttribute('data-testid'))

describe('a thread opens where you left it and catches up by itself', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'cA'
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('opens at the first unread message, under a NEW line', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([1, 2, 3, 4, 5], 3))
    const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
    await flushPromises()
    const o = order(w)
    expect(o.indexOf('ost-unread-line')).toBe(o.indexOf('ost-msg-4') - 1)
    expect(w.find('[data-testid="ost-unread-line"]').text()).toContain('2')
    w.unmount()
  })

  it('with nothing unread, no line (it opens at the end)', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([1, 2, 3], 3))
    const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
    await flushPromises()
    expect(w.find('[data-testid="ost-unread-line"]').exists()).toBe(false)
    w.unmount()
  })

  it('a focus catches up: the new message appears once', async () => {
    h.chat.getMessages = vi.fn()
      .mockResolvedValueOnce(page([1, 2], 2))
      .mockResolvedValue(page([1, 2, 3], 2))
    const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
    await flushPromises()
    expect(w.findAll('[data-testid="ost-msg-3"]')).toHaveLength(0)
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(w.findAll('[data-testid="ost-msg-3"]')).toHaveLength(1)
    window.dispatchEvent(new Event('focus'))
    await flushPromises()
    expect(w.findAll('[data-testid="ost-msg-3"]')).toHaveLength(1)
    w.unmount()
  })

  it('the header says live', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([1], 1))
    const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
    await flushPromises()
    expect(w.find('[data-testid="ost-live"]').attributes('data-state')).toBe('live')
    w.unmount()
  })
})
