import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0653 (w) (session-lead, the sessions' room seq 880): a line sent with an API key says so in the thread, on the line
 * itself (the author row shows only when the speaker changes). From V0653 a key posts in the chat (an MCP connector's,
 * the personal bridge's), so a developer's line no longer proves his own hand; the registry records how each line was
 * sent (sent_with) and the console and Pocket mark a key's. The harness is PocketOurStateThread.speakAs.test.ts's.
 * BASE (18ee29f22): no line is marked.
 */
const AGENT = { did: 'did:theprotocol:eu.theprotocol.cloud:19c1aa48', name: 'session-tester' }
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  auth: { token: 'dev.tok', user: { developer_id: 6 }, agentToken: 'agent.tok', activeAgent: null as any },
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const no = () => vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } }))
  const c = { get: no(), post: no(), put: no(), delete: no() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn().mockResolvedValue(undefined),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev.tok' }))
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
  return { usePocketAgent: () => ({ credAgents: ref([{ did: AGENT.did, name: AGENT.name }]), ensureAgentFor: vi.fn().mockResolvedValue(true),
    noAgentReason: ref(''), sealedLocked: ref(false) }) }
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
  h.route = reactive({ params: { id: 'room-a' }, query: {}, path: '/pocket/ourchat/room-a' })
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
const room = (messages: any[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind: 'dm',
  my_state: 'active', my_last_read_seq: messages.length, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
const line = (seq: number, body: string, sent_with: string | null) => ({ id: `m${seq}`, seq, kind: 'text', body,
  sender_ptype: 'developer', sender_id: 6, sender_name: 'maintainer', created_at: '2026-11-02T05:00:00Z', sent_with })

describe('a line sent with a key says so', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.activeAgent = null
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('marks the line a key sent, and no other', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(room([
      line(1, 'approved', 'api_key'),       // the bridge or a connector, as him
      line(2, 'approved', 'session'),       // his own hand, signed in
      line(3, 'from before V0653', null),   // nothing recorded
    ]))
    h.chat.markRead = vi.fn().mockResolvedValue({})
    const w = mount(PocketOurStateThread, opts)
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.find('[data-testid="ost-msg-1"]').exists()).toBe(true)
    const mark = w.find('[data-testid="ost-by-key-1"]')
    expect(mark.exists()).toBe(true)
    expect(mark.text()).toBe('sent with a key')
    expect(mark.attributes('title')).toContain('API key')
    expect(w.find('[data-testid="ost-by-key-2"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-by-key-3"]').exists()).toBe(false)
  })
})
