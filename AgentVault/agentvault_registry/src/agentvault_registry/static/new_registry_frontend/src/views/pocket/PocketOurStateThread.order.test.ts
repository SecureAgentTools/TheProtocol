import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, the batch's item 5): `/order <bounty> [CCY] <title>` opens the Guild order door. Typing it posts
 * nothing: the sheet opens filled, and only its button (which says how much it locks) posts, as the agent the person sends
 * as, through the Guild's own rail with this conversation as the room. A missing bounty, no agent and a refusal each say so.
 * BASE (7435f0d5a): /order is an unknown command. The harness is PocketOurStateThread.edit.test.ts's.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: {} as Record<string, any>,
  startConnected: true,
  guildPost: ((..._a: any[]): any => ({})) as any,
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
  return { useChatStream: (hs: any) => { h.stream = hs; return { isConnected: ref(h.startConnected), disconnect: () => {} } } }
})
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourchat') }) }
})
vi.mock('@/composables/usePocketAgent', async () => {
  const { ref } = await import('vue')
  return { usePocketAgent: () => ({ credAgents: ref([]), ensureAgentFor: vi.fn().mockResolvedValue(true),
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

vi.mock('@/services/api/guild', () => ({ guildApi: { post: (...a: any[]) => h.guildPost(...a) } }))

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}

const ago = (ms: number) => new Date(Date.now() - ms).toISOString()
const line = (over: Record<string, any> = {}) => ({ id: 'm1', seq: 1, kind: 'text', body: 'first draft', sender_ptype: 'developer', sender_id: 6,
  conversation_id: 'room-a', created_at: ago(60_000), mentions: [], ...over })

async function settle(n = 4) { for (let i = 0; i < n; i++) await flushPromises() }
async function open(messages: any[]) {
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages, last_seq: messages.length, page_bound: 40, kind: 'dm', my_state: 'active',
    my_last_read_seq: messages.length, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const w = mount(PocketOurStateThread, opts)
  await settle()
  return w
}
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)

beforeEach(() => {
  setActivePinia(createPinia())
  h.chat = {}
  h.stream = {}
  h.startConnected = true
  h.route.params.id = 'room-a'
  h.auth.activeAgent = null
  localStorage.clear()
})
afterEach(() => { document.body.innerHTML = '' })


const AGENT = { did: 'did:theprotocol:eu.test:poster', name: 'Poster' }
async function typeCmd(w: any, text: string) {
  await w.find('[data-testid="ost-input"]').setValue(text)
  await settle(2)
  await w.find('[data-testid="ost-send"]').trigger('click')
  await settle(4)
}

describe('/order', () => {
  // the person has chosen this agent to send as in this thread (services/chat/speakAs.ts): the order is posted by it
  beforeEach(() => { h.auth.activeAgent = AGENT as any; localStorage.setItem('ourchat.speakAs.room-a', AGENT.did); h.guildPost = vi.fn().mockResolvedValue({ order_id: 'gwo_123' }) })

  it('opens the sheet filled and posts nothing', async () => {
    const w = await open([line()])
    await typeCmd(w, '/order 20 ECU Review the PR')
    expect(tid(w, 'ost-order-sheet').exists()).toBe(true)
    expect((tid(w, 'ost-order-title').element as HTMLInputElement).value).toBe('Review the PR')
    expect((tid(w, 'ost-order-bounty').element as HTMLInputElement).value).toBe('20')
    expect((tid(w, 'ost-order-ccy').element as HTMLInputElement).value).toBe('ECU')
    expect(tid(w, 'ost-order-post').text()).toBe('Post and lock 20 ECU')
    expect(tid(w, 'ost-order-lock').text()).toContain('locks 20 ECU')
    expect(h.guildPost).not.toHaveBeenCalled()
    expect(h.chat.postMessage).toBeUndefined()                                  // and nothing went into the thread
  })
  it('the button posts through the Guild rail (the API client signs it as the acting agent and routes it home), naming this conversation as the room', async () => {
    const w = await open([line()])
    await typeCmd(w, '/order 20 ECU Review the PR')
    await tid(w, 'ost-order-spec').setValue('Read it, say what is wrong.')
    await tid(w, 'ost-order-post').trigger('click')
    await settle(4)
    expect(h.guildPost).toHaveBeenCalledTimes(1)
    expect(h.guildPost).toHaveBeenCalledWith({ title: 'Review the PR', bounty: 20, currency: 'ECU', spec: 'Read it, say what is wrong.',
      deadline_seconds: 7 * 86400, room_id: 'room-a' })
    expect(tid(w, 'ost-order-sheet').exists()).toBe(false)
    expect(w.text()).toContain('Order posted (gwo_123)')
  })
  it('leaves the room out when the person unticks it', async () => {
    const w = await open([line()])
    await typeCmd(w, '/order 5 ECU Small thing')
    await tid(w, 'ost-order-room').setValue(false)
    await tid(w, 'ost-order-post').trigger('click')
    await settle(4)
    expect('room_id' in h.guildPost.mock.calls[0][0]).toBe(false)
  })
  it('shows what to fix, and sends nothing, for a bad form', async () => {
    const w = await open([line()])
    await typeCmd(w, '/order 20 ECU Review the PR')
    await tid(w, 'ost-order-bounty').setValue('lots')
    await tid(w, 'ost-order-post').trigger('click')
    await settle(3)
    expect(tid(w, 'ost-order-err').exists()).toBe(true)
    expect(h.guildPost).not.toHaveBeenCalled()
  })
  it('shows the rail\'s refusal as its sentence and keeps the sheet open', async () => {
    h.guildPost = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'Escrow failed (insufficient balance?): not enough' }))
    const w = await open([line()])
    await typeCmd(w, '/order 20 ECU Review the PR')
    await tid(w, 'ost-order-post').trigger('click')
    await settle(4)
    expect(tid(w, 'ost-order-err').text()).toContain('Escrow failed (insufficient balance?)')
    expect(tid(w, 'ost-order-sheet').exists()).toBe(true)
  })
  it('Cancel closes it without posting', async () => {
    const w = await open([line()])
    await typeCmd(w, '/order 20 ECU Review the PR')
    await tid(w, 'ost-order-cancel').trigger('click')
    expect(tid(w, 'ost-order-sheet').exists()).toBe(false)
    expect(h.guildPost).not.toHaveBeenCalled()
  })
  it('without a bounty it says so and opens nothing', async () => {
    const w = await open([line()])
    await typeCmd(w, '/order Review the PR')
    expect(tid(w, 'ost-order-sheet').exists()).toBe(false)
    expect(w.text()).toContain('/order needs a bounty')
  })
  it('without an agent chosen to send as it says so and opens nothing', async () => {
    localStorage.removeItem('ourchat.speakAs.room-a')
    const w = await open([line()])
    await typeCmd(w, '/order 20 ECU Review the PR')
    expect(tid(w, 'ost-order-sheet').exists()).toBe(false)
    expect(w.text()).toContain('pick it under Send as')
    expect(h.guildPost).not.toHaveBeenCalled()
  })
})
