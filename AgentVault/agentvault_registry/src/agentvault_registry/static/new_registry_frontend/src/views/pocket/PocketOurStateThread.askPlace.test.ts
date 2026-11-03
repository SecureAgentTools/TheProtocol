import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0655 (av) (order gwo_ce52bf8dc39e7202817f16c7): a request to the assistant belongs with its answer, not with the chat
 * box. An answered request sits directly above its answer wherever the answer is drawn (the main list, or inside the thread
 * its reply folds it into) and folds with it; a waiting or refused one keeps V0654's place, after the line it followed or
 * at the bottom. One component serves the desktop and Pocket. The harness is PocketOurStateThread.assistant.test.ts's.
 * BASE (V0654): an answered request asked after a line that sat in a folded thread was drawn at the bottom, above the
 * chat box, for as long as the thread stayed folded (the folded-thread case below is red there).
 */
const AGENT = { did: 'did:theprotocol:eu.theprotocol.cloud:19c1aa48', name: 'Atlas' }
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  auth: { token: 'dev.tok', user: { developer_id: 6 }, agentToken: 'agent.tok', activeAgent: null as any },
  status: null as any,
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/client', () => {
  const no = () => vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } }))
  const get = vi.fn().mockImplementation((url: string) => (url === '/assistant/status' && h.status
    ? Promise.resolve({ data: h.status }) : Promise.reject(Object.assign(new Error('404'), { response: { status: 404 } }))))
  const c = { get, post: no(), put: no(), delete: no() }
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
const room = (messages: any[], kind = 'dm') => ({ messages, last_seq: messages.length, page_bound: 40, kind,
  my_state: 'active', my_last_read_seq: messages.length, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
const line = (seq: number, body: string, extra: Record<string, any> = {}) => ({ id: `m${seq}`, seq, kind: 'text', body,
  sender_ptype: 'developer', sender_id: 2, sender_name: 'Mira', created_at: '2026-11-02T15:00:00Z', ...extra })
const PROMPT = 'tell Mira the build starts at five'
function seedAsk(a: Record<string, any>) {
  sessionStorage.setItem('ourchat.assistAsks.room-a', JSON.stringify([{ ref: 'ask-1', conversationId: 'room-a',
    prompt: PROMPT, who: '', whoKey: 'you', ...a }]))
}
const answer = (seq: number, extra: Record<string, any> = {}) => line(seq, 'The build starts at 17:00Z.',
  { sender_id: 6, sender_name: 'maintainer', sent_with: 'assistant', created_at: '2026-11-03T09:01:00Z', ...extra })
async function open(messages: any[]) {
  h.chat.getMessages = vi.fn().mockResolvedValue(room(messages))
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 5; i++) await flushPromises()
  return w
}
const order = (w: any) => w.findAll('[data-testid^="ost-assist-ask-"], [data-testid^="ost-msg-"]')
  .map((x: any) => x.attributes('data-testid'))

describe('the assistant\'s request stays with its answer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.activeAgent = null
    h.status = { bridge: { enabled: true } }
    localStorage.clear()
    sessionStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('answered in the main list: the request sits directly above its answer, not after the line it followed', async () => {
    seedAsk({ state: 'answered', afterSeq: 1, answerSeq: 3 })
    const w = await open([line(1, 'when do we build?'), line(2, 'and who runs it?'), answer(3)])
    expect(order(w)).toEqual(['ost-msg-1', 'ost-msg-2', 'ost-assist-ask-ask-1', 'ost-msg-3'])
    expect(w.find('[data-testid="ost-assist-ask-ask-1"]').attributes('data-state')).toBe('answered')
  })

  it('answered inside a folded thread: not above the chat box; when the thread opens, directly above its answer',
    async () => {
      // he asked after line 2, a reply folded under line 1; the answer replies to line 1, so it folds there too
      seedAsk({ state: 'answered', afterSeq: 2, answerSeq: 3, replyTo: 'm1' })
      const w = await open([line(1, 'when do we build?'), line(2, 'today?', { reply_to: 'm1' }),
        answer(3, { reply_to: 'm1' })])
      expect(w.find('[data-testid="ost-thread-1"]').attributes('aria-expanded')).toBe('false')
      expect(order(w)).toEqual(['ost-msg-1'])                     // folded with its answer: nowhere near the chat box
      await w.find('[data-testid="ost-thread-1"]').trigger('click')
      await flushPromises()
      expect(order(w)).toEqual(['ost-msg-1', 'ost-msg-2', 'ost-assist-ask-ask-1', 'ost-msg-3'])
      // folded again, it goes with its answer
      await w.find('[data-testid="ost-thread-1"]').trigger('click')
      await flushPromises()
      expect(order(w)).toEqual(['ost-msg-1'])
    })

  it('refused: keeps its place after the line it followed, with its reason and Edit', async () => {
    seedAsk({ state: 'failed', afterSeq: 1, error: 'The assistant took too long to answer.' })
    const w = await open([line(1, 'when do we build?'), line(2, 'and who runs it?')])
    expect(order(w)).toEqual(['ost-msg-1', 'ost-assist-ask-ask-1', 'ost-msg-2'])
    expect(w.find('[data-testid="ost-assist-error"]').text()).toBe('The assistant took too long to answer.')
    expect(w.find('[data-testid="ost-assist-edit"]').exists()).toBe(true)
  })

  it('waiting: after the line it followed, and once answered it moves above the answer', async () => {
    localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))
    let reply: (v: any) => void = () => {}
    h.chat.assist = vi.fn().mockImplementation(() => new Promise((r) => { reply = r }))
    const w = await open([line(1, 'when do we build?')])
    await w.find('[data-testid="ost-input"]').setValue(PROMPT)
    await w.find('[data-testid="ost-send"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    const ref = h.chat.assist.mock.calls[0][2].client_ref
    expect(order(w)).toEqual(['ost-msg-1', `ost-assist-ask-${ref}`])
    expect(w.find('[data-testid="ost-assist-waiting"]').exists()).toBe(true)
    reply({ message: { ...answer(2), conversation_id: 'room-a' }, my_state: 'active' })
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(order(w)).toEqual(['ost-msg-1', `ost-assist-ask-${ref}`, 'ost-msg-2'])
    expect(w.find(`[data-testid="ost-assist-ask-${ref}"]`).attributes('data-state')).toBe('answered')
  })
})
