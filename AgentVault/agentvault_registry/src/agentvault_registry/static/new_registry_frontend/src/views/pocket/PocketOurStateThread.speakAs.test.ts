import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (aj) (order gwo_9fa441b938ff31f95662243f): the composer shows who a message goes out as, beside the send button,
 * and it is YOU unless an agent was chosen for this thread. The maintainer (the room, seq 313): "I accidentally wrote with
 * tester session account. It got accidentally picked in the mobile app": the console acted as an agent (it picks one by
 * itself at sign-in) and the composer posted as it. BASE (V0651): the room's message went out with the agent's token.
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
// a conversation between two people (the composer's rule is the same in a room: you unless an agent was chosen there)
const room = (messages: any[] = []) => ({ messages, last_seq: messages.length, page_bound: 40, kind: 'dm',
  my_state: 'active', my_last_read_seq: messages.length, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })

async function open() {
  h.chat.getMessages = vi.fn().mockResolvedValue(room([{ id: 'm0', seq: 1, kind: 'text', body: 'hello', sender_ptype: 'developer',
    sender_id: 2, sender_name: 'Mira', created_at: '2026-10-31T21:00:00Z' }]))
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.postMessage = vi.fn().mockResolvedValue({ message: { id: 'm1', seq: 1, kind: 'text', body: 'hi', sender_ptype: 'developer', sender_id: 6 } })
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function send(w: any, body: string) {
  await w.find('[data-testid="ost-input"]').setValue(body)
  await w.find('[data-testid="ost-send"]').trigger('click')
  for (let i = 0; i < 3; i++) await flushPromises()
}

describe('the composer posts as you unless an agent was chosen here', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.activeAgent = { ...AGENT }   // acting as an agent, chosen elsewhere (or by the console at sign-in)
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('shows you beside the send button, and the message is the developer\'s', async () => {
    const w = await open()
    const chip = w.find('[data-testid="ost-speaker"]')
    expect(chip.attributes('data-speaker')).toBe('you')
    expect(chip.text()).toContain('You')
    // the chip sits right before the send button
    expect(chip.element.nextElementSibling?.getAttribute('data-testid')).toBe('ost-send')
    await send(w, 'hello room')
    expect(h.chat.postMessage).toHaveBeenCalled()
    expect(h.chat.postMessage.mock.calls[0][0]).toBe('dev.tok')
  })

  it('an agent chosen for this thread speaks here, and only here', async () => {
    localStorage.setItem('ourchat.speakAs.room-a', AGENT.did)
    const w = await open()
    expect(w.find('[data-testid="ost-speaker"]').attributes('data-speaker')).toBe('agent')
    await send(w, 'as the agent')
    expect(h.chat.postMessage.mock.calls[0][0]).toBe('agent.tok')
    w.unmount()
    h.route.params.id = 'room-b'
    const w2 = await open()
    expect(w2.find('[data-testid="ost-speaker"]').attributes('data-speaker')).toBe('you')
  })

  it('a thread whose chosen agent is no longer the acting one speaks as you', async () => {
    localStorage.setItem('ourchat.speakAs.room-a', AGENT.did)
    h.auth.activeAgent = { did: 'did:theprotocol:eu.theprotocol.cloud:other', name: 'other' }
    const w = await open()
    expect(w.find('[data-testid="ost-speaker"]').attributes('data-speaker')).toBe('you')
  })

  it('a message an owner sent as the agent says so', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(room([
      { id: 'm1', seq: 1, kind: 'text', body: 'by hand', sender_ptype: 'agent', sender_id: AGENT.did, sender_name: AGENT.name,
        sent_by_owner: true, created_at: '2026-10-31T21:00:00Z' },
      { id: 'm2', seq: 2, kind: 'text', body: 'by itself', sender_ptype: 'agent', sender_id: AGENT.did, sender_name: AGENT.name,
        sent_by_owner: false, created_at: '2026-10-31T21:01:00Z' },
    ]))
    h.chat.markRead = vi.fn().mockResolvedValue({})
    const w = mount(PocketOurStateThread, opts)
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.findAll('[data-testid="ost-by-owner"]').length).toBe(1)
  })
})
