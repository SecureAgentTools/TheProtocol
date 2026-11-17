import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0664 (order gwo_874694de65551c5c1488641c): a sender sees when the cross-frame relay limit holds a message back. In a thread another
 * registry hosts, a line the host's limit holds shows "Waiting: the relay to <frame> is busy, sends in about N s", counts down, goes
 * again under the same client_ref and then says it was sent and waits for the host's copy; after the last try it says Not sent with
 * Send again. A thread hosted here keeps its old behaviour. The harness is PocketOurStateThread.composer.test.ts's.
 */
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

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}
/* the test DOM lays nothing out: the pane reports the height a test gives it, and the textarea the text height a test
   gives it (scrollHeight), as a browser's layout would */
let paneH = 800
const clientHeightDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
function textHeight(el: Element, px: number) { Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => px }) }


const MIRROR = { registry: 'Sandbox Alpha', here: false, copies: [] as string[], plaintext: true, says: 'x' }
const LOCAL = { registry: 'this registry', here: true, copies: [] as string[], plaintext: true, says: 'x' }
const limit = (retryAfterS?: number) => Object.assign(new Error('capped'), { status: 429, detail: 'the thread is capped', ...(retryAfterS ? { retryAfterS } : {}) })

async function open(hosting: any) {
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [], last_seq: 0, page_bound: 40, kind: 'dm', my_state: 'active',
    my_last_read_seq: 0, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' }, hosting })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function send(w: any, text: string) {
  await w.find('[data-testid="ost-input"]').setValue(text)
  await w.find('[data-testid="ost-send"]').trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}
const pending = (w: any) => w.find('[data-testid^="ost-pending-"]')

beforeEach(() => {
  setActivePinia(createPinia())
  h.chat = {}
  h.route.params.id = 'room-a'
  h.auth.activeAgent = null
  localStorage.clear()
  vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
})
afterEach(() => { vi.useRealTimers(); document.body.innerHTML = '' })

describe('a line the cross-frame relay limit holds back', () => {
  it('shows the wait in the host\'s own number, counts down, and the text leaves the composer (it is in the thread now)', async () => {
    const w = await open(MIRROR)
    h.chat.postMessage = vi.fn().mockRejectedValue(limit(7))
    await send(w, 'hello over there')
    expect(pending(w).attributes('data-state')).toBe('waiting')
    expect(pending(w).text()).toContain('hello over there')
    expect(pending(w).text()).toContain('Waiting: the relay to Sandbox Alpha is busy, sends in about 7 s')
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toBe('')
    expect(w.find('[data-testid="ost-hint"]').exists()).toBe(false)             // not the old refusal sentence
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(pending(w).text()).toContain('sends in about 6 s')
    w.unmount()
  })

  it('goes again under the same client_ref when the seconds are up, then says it was sent and is waiting to arrive', async () => {
    const w = await open(MIRROR)
    h.chat.postMessage = vi.fn().mockRejectedValueOnce(limit(2)).mockResolvedValue({ relayed: true, host_seq: 9, client_ref: 'x' })
    await send(w, 'hello over there')
    const first = h.chat.postMessage.mock.calls[0][2]
    await vi.advanceTimersByTimeAsync(2000)
    await flushPromises()
    expect(h.chat.postMessage).toHaveBeenCalledTimes(2)
    expect(h.chat.postMessage.mock.calls[1][2].client_ref).toBe(first.client_ref)
    expect(pending(w).attributes('data-state')).toBe('sent')
    expect(pending(w).text()).toContain('Sent to Sandbox Alpha, waiting for it to arrive')
    w.unmount()
  })

  it('a line the relay took at once also shows until the host\'s copy comes back (the silent gap), and goes when it does', async () => {
    const w = await open(MIRROR)
    h.chat.postMessage = vi.fn().mockResolvedValue({ relayed: true, host_seq: 9 })
    await send(w, 'quick one')
    expect(pending(w).attributes('data-state')).toBe('sent')
    const ref = h.chat.postMessage.mock.calls[0][2].client_ref
    h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [{ id: 'm9', seq: 9, kind: 'text', body: 'quick one', client_ref: ref,
      sender_ptype: 'developer', sender_id: 6, created_at: '2026-11-14T10:00:00Z' }], last_seq: 9, page_bound: 40, kind: 'dm', my_state: 'active',
      my_last_read_seq: 9, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' }, hosting: MIRROR })
    window.dispatchEvent(new Event('online'))                                    // any reload of the thread
    await (w.vm as any).load?.()
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(pending(w).exists()).toBe(false)
    w.unmount()
  })

  it('after the last try says Not sent in the host\'s words and offers Send again, which tries once more with the same text', async () => {
    const w = await open(MIRROR)
    h.chat.postMessage = vi.fn().mockRejectedValue(limit(1))
    await send(w, 'hello over there')
    await vi.advanceTimersByTimeAsync(1000 * 10)
    await flushPromises()
    expect(pending(w).attributes('data-state')).toBe('failed')
    expect(pending(w).text()).toContain('Not sent')
    expect(pending(w).text()).toContain('the thread is capped')
    const calls = h.chat.postMessage.mock.calls.length
    h.chat.postMessage = vi.fn().mockResolvedValue({ relayed: true })
    await w.find('[data-testid^="ost-pending-again-"]').trigger('click')
    await flushPromises()
    expect(h.chat.postMessage).toHaveBeenCalledTimes(1)
    expect(pending(w).attributes('data-state')).toBe('sent')
    expect(calls).toBeGreaterThan(1)
    w.unmount()
  })

  it('a host that names no wait gets the one fixed fallback, never a made-up number', async () => {
    const w = await open(MIRROR)
    h.chat.postMessage = vi.fn().mockRejectedValue(limit())
    await send(w, 'hello over there')
    expect(pending(w).text()).toContain('sends in about 15 s')
    w.unmount()
  })

  it('a thread hosted here keeps today\'s behaviour: the hint, the text stays in the composer, no pending line', async () => {
    const w = await open(LOCAL)
    h.chat.postMessage = vi.fn().mockRejectedValue(limit(7))
    await send(w, 'hello here')
    expect(pending(w).exists()).toBe(false)
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('the thread is capped')
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toBe('hello here')
    w.unmount()
  })
})
