import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0654 (ap) (order gwo_03a846cb91b37628c3c6710a; his words in the sessions' room, seq 1091): the assistant in OurChat.
 * Pickable per identity in the "Speak as" choice; the "as" chip turns amber with the assistant's mark while it is on;
 * what he types then goes to his assistant, not the room: his request shows to him alone and the answer the registry
 * posts (sent_with "assistant") comes below it, marked "written by your assistant" for him and "written by the
 * assistant" for everyone else. Only where GET /assistant/status says his assistant is there. One component serves the
 * desktop and Pocket. The harness is PocketOurStateThread.sentWithKey.test.ts's. BASE (V0653): none of it exists.
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
const ASK = 'tell Mira the build starts at five'
const ANSWER = { id: 'm2', seq: 2, kind: 'text', body: 'The build starts at 17:00Z.', sender_ptype: 'developer', sender_id: 6,
  sender_name: 'maintainer', sent_with: 'assistant', created_at: '2026-11-02T15:01:00Z', conversation_id: 'room-a' }

async function open(messages = [line(1, 'when do we build?')], kind = 'dm') {
  h.chat.getMessages = vi.fn().mockResolvedValue(room(messages, kind))
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 5; i++) await flushPromises()
  return w
}
async function type(w: any, body: string) {
  await w.find('[data-testid="ost-input"]').setValue(body)
  await w.find('[data-testid="ost-send"]').trigger('click')
  for (let i = 0; i < 3; i++) await flushPromises()
}
const chip = (w: any) => w.find('[data-testid="ost-speaker"]')

describe('the assistant in OurChat', () => {
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

  it('is not offered where the assistant is not there for this caller', async () => {
    h.status = { bridge: { enabled: false } }
    localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))   // a switch kept from before: inert here
    const w = await open()
    await chip(w).trigger('click')
    expect(w.find('[data-testid="ost-speaker-picker"]').exists()).toBe(true)
    expect(w.find('[data-testid="ost-assist-switch"]').exists()).toBe(false)
    expect(chip(w).attributes('data-assist')).toBe('off')
  })

  it('switched on in the "Speak as" choice, the chip turns amber with its mark, for this room', async () => {
    const w = await open()
    expect(chip(w).attributes('data-assist')).toBe('off')
    await chip(w).trigger('click')
    const sw = w.find('[data-testid="ost-assist-switch"]')
    expect(sw.attributes('aria-checked')).toBe('false')
    expect(sw.text()).toContain('AI assistant for you')
    await sw.trigger('click')
    expect(w.find('[data-testid="ost-assist-switch"]').attributes('aria-checked')).toBe('true')
    expect(chip(w).attributes('data-assist')).toBe('on')
    expect(chip(w).classes()).toContain('assist')
    expect(w.find('[data-testid="ost-speaker-assist"]').exists()).toBe(true)
    expect(JSON.parse(localStorage.getItem('ourchat.assist.room-a') || '[]')).toEqual(['you'])
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).placeholder).toBe('Ask your assistant…')
    expect(w.find('[data-testid="ost-send"]').attributes('aria-label')).toBe('Ask your assistant to write as you')
  })

  it('what you type goes to your assistant, not the room; your request shows to you and the answer comes below it',
    async () => {
      localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))
      let answer: (v: any) => void = () => {}
      h.chat.assist = vi.fn().mockImplementation(() => new Promise((r) => { answer = r }))
      const w = await open()
      await type(w, ASK)
      expect(h.chat.postMessage?.mock.calls.length ?? 0).toBe(0)     // nothing was posted by the console
      expect(h.chat.assist).toHaveBeenCalledTimes(1)
      const [tok, conv, body] = h.chat.assist.mock.calls[0]
      expect([tok, conv, body.prompt]).toEqual(['dev.tok', 'room-a', ASK])
      expect(body.client_ref).toMatch(/.{8,}/)
      expect(w.find('[data-testid="ost-assist-prompt"]').text()).toBe(ASK)
      expect(w.find('[data-testid="ost-assist-waiting"]').exists()).toBe(true)
      expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toBe('')
      answer({ message: ANSWER, my_state: 'active' })
      for (let i = 0; i < 4; i++) await flushPromises()
      expect(w.find('[data-testid="ost-assist-waiting"]').exists()).toBe(false)
      expect(w.find(`[data-testid="ost-assist-ask-${body.client_ref}"]`).attributes('data-state')).toBe('answered')
      const order = w.findAll('[data-testid^="ost-assist-ask-"], [data-testid^="ost-msg-"]').map((x: any) => x.attributes('data-testid'))
      expect(order).toEqual(['ost-msg-1', `ost-assist-ask-${body.client_ref}`, 'ost-msg-2'])
      expect(w.find('[data-testid="ost-by-assistant-2"]').text()).toBe('written by your assistant')
      // the request is this device's, for this browser session: never in the room
      expect(sessionStorage.getItem('ourchat.assistAsks.room-a')).toContain(ASK)
    })

  it('each identity has its own switch, and an agent\'s answer is asked with the agent\'s token', async () => {
    localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))
    localStorage.setItem('ourchat.speakAs.room-a', AGENT.did)
    h.auth.activeAgent = { ...AGENT }
    h.chat.assist = vi.fn().mockResolvedValue({ message: { ...ANSWER, sender_ptype: 'agent', sender_id: AGENT.did } })
    const w = await open()
    expect(chip(w).attributes('data-speaker')).toBe('agent')
    expect(chip(w).attributes('data-assist')).toBe('off')        // on for you is not on for Atlas
    await chip(w).trigger('click')
    expect(w.find('[data-testid="ost-assist-switch"]').text()).toContain('AI assistant for Atlas')
    await w.find('[data-testid="ost-assist-switch"]').trigger('click')
    expect(chip(w).attributes('data-assist')).toBe('on')
    await type(w, ASK)
    expect(h.chat.assist.mock.calls[0][0]).toBe('agent.tok')
    expect(w.find('[data-testid^="ost-assist-ask-"]').text()).toContain('You asked your assistant, as Atlas')
  })

  it('a refusal says why on the request, nothing is posted, and Edit puts the request back', async () => {
    localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))
    h.chat.assist = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { status: 504,
      detail: 'The assistant took too long to answer.' }))
    const w = await open()
    await type(w, ASK)
    expect(w.find('[data-testid="ost-assist-error"]').text()).toBe('The assistant took too long to answer.')
    expect(h.chat.postMessage?.mock.calls.length ?? 0).toBe(0)
    await w.find('[data-testid="ost-assist-edit"]').trigger('click')
    await flushPromises()
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toBe(ASK)
    expect(w.find('[data-testid^="ost-assist-ask-"]').exists()).toBe(false)
  })

  it('asking again sends the same request with the same ref, so an answer already posted comes back once', async () => {
    localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))
    h.chat.assist = vi.fn().mockRejectedValueOnce(Object.assign(new Error('x'), { status: 0 }))   // the connection dropped
      .mockResolvedValueOnce({ message: ANSWER })
    const w = await open()
    await type(w, ASK)
    expect(w.find('[data-testid="ost-assist-error"]').text()).toContain('connection dropped')
    await w.find('[data-testid="ost-assist-retry"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    const [a, b] = h.chat.assist.mock.calls.map((c: any[]) => c[2])
    expect(b.client_ref).toBe(a.client_ref)
    expect(w.findAll('[data-testid="ost-msg-2"]').length).toBe(1)
  })

  it('marks an answer "written by your assistant" for its owner and "written by the assistant" for everyone else', async () => {
    h.status = { bridge: { enabled: false } }   // reading the marks needs no assistant of your own
    const w = await open([
      line(1, 'from my assistant', { sender_id: 6, sent_with: 'assistant' }),
      line(2, 'from Mira\'s assistant', { sent_with: 'assistant' }),
      line(3, 'by hand', { sent_with: 'session' }),
    ])
    expect(w.find('[data-testid="ost-by-assistant-1"]').text()).toBe('written by your assistant')
    expect(w.find('[data-testid="ost-by-assistant-2"]').text()).toBe('written by the assistant')
    expect(w.find('[data-testid="ost-by-assistant-3"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-by-key-1"]').exists()).toBe(false)
  })

  it('is never offered in a support thread (the desk writes it)', async () => {
    localStorage.setItem('ourchat.assist.room-a', JSON.stringify(['you']))
    const w = await open([line(1, 'how can we help?')], 'support')
    expect(chip(w).attributes('data-assist')).toBe('off')
  })
})
