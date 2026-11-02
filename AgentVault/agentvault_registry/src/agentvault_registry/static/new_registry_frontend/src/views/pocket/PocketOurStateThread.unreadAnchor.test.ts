import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0654 (session-lead, the sessions' room seq 941/949; check 140 of V0653's console proof): a thread that opens at its
 * NEW line keeps it in view while it settles. A live message arriving in that hold stays below the line (ingest took the
 * view to the end); a size change in the thread re-runs the scroll to the line; the reader's own move ends the hold (a
 * wheel on the history, a key in the composer), and then a live message goes to the end as before. A thread with nothing
 * unread holds nothing; a switch and an unmount end the hold.
 * BASE (V0653, 1d92f4882): the live message took the view to the end (the first test fails there).
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: null as any,
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
// the hold's length is not what is tested here (unreadAnchor.test.ts holds it to ANCHOR_MS): long, so a slow run cannot end it
vi.mock('@/services/chat/unreadAnchor', async (orig) => ({ ...(await orig<typeof import('@/services/chat/unreadAnchor')>()), ANCHOR_MS: 600_000 }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'tok', user: { developer_id: 1 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'tok' }))
vi.mock('@/composables/useChatStream', async () => {
  const { ref } = await import('vue')
  return { useChatStream: (o: any) => { h.stream = o; return { isConnected: ref(true), disconnect: () => {} } } }
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

class FakeRO {
  static all: FakeRO[] = []
  observed: Element[] = []
  disconnected = false
  constructor(public cb: ResizeObserverCallback) { FakeRO.all.push(this) }
  observe(el: Element) { this.observed.push(el) }
  unobserve() {}
  disconnect() { this.disconnected = true }
  fire() { if (!this.disconnected) this.cb([], this as unknown as ResizeObserver) }
}

const opts = {
  attachTo: document.body,
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}
const msg = (seq: number) => ({ id: `m${seq}`, seq, kind: 'text', body: `line ${seq}`, sender_ptype: 'developer', sender_id: 2,
  sender_name: 'Mira', created_at: `2026-11-02T08:${String(seq).padStart(2, '0')}:00Z` })
const page = (seqs: number[], lastRead: number) => ({ messages: seqs.map(msg), last_seq: seqs[seqs.length - 1] || 0, page_bound: 40,
  kind: 'dm', my_state: 'active', my_last_read_seq: lastRead, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
const END = 5000   // the history's height: a scroll to the end writes it

/** Opens thread cA and records every write to its history's scroll position (jsdom lays nothing out). */
async function open(lastRead: number) {
  h.chat.getMessages = vi.fn().mockResolvedValue(page([3, 4, 5, 6, 7, 8], lastRead))
  const w = mount(PocketOurStateThread, opts)
  const sc = w.find('[data-testid="ost-messages"]').element as HTMLElement
  const writes: number[] = []
  let top = 0
  Object.defineProperty(sc, 'scrollHeight', { configurable: true, get: () => END })
  Object.defineProperty(sc, 'clientHeight', { configurable: true, get: () => 400 })
  Object.defineProperty(sc, 'scrollTop', { configurable: true, get: () => top, set: (v: number) => { top = v; writes.push(v) } })
  await flushPromises()
  const hold = FakeRO.all.find(r => r.observed.includes(sc)) || null
  return { w, sc, writes, hold }
}
async function live(seq: number) {
  h.stream.onMessage({ conversation_id: 'cA', message: msg(seq) })
  await flushPromises()
}

describe('a thread that opens at its NEW line keeps it in view while it settles', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'cA'
    FakeRO.all = []
    vi.stubGlobal('ResizeObserver', FakeRO)
  })
  afterEach(() => { vi.unstubAllGlobals(); document.body.innerHTML = '' })

  it('a live message in the hold stays below the line; a size change scrolls to the line again; a wheel ends the hold', async () => {
    const { w, sc, writes, hold } = await open(3)
    expect(w.find('[data-testid="ost-unread-line"]').exists(), 'opened under a NEW line').toBe(true)
    expect(writes.length, 'the open scrolled to the line').toBeGreaterThan(0)
    expect(writes).not.toContain(END)
    const before = writes.length
    await live(9)
    expect(w.find('[data-testid="ost-msg-9"]').exists(), 'the live message is shown').toBe(true)
    expect(writes.slice(before), 'it did not take the view to the end').not.toContain(END)
    expect(hold, 'the history and its messages are held').not.toBeNull()
    hold!.fire()   // the pane narrowed: the messages above the line wrapped again
    expect(writes.length, 'a size change scrolls to the line again').toBeGreaterThan(before)
    expect(writes).not.toContain(END)
    sc.dispatchEvent(new Event('wheel', { bubbles: true }))   // the reader's own move
    expect(hold!.disconnected).toBe(true)
    const after = writes.length
    hold!.fire()
    expect(writes.length, 'nothing re-runs once the reader moved').toBe(after)
    await live(10)
    expect(writes[writes.length - 1], 'control: after the hold a live message goes to the end').toBe(END)
    w.unmount()
  })

  it("a key in the composer is the reader's move: the hold ends (their own send goes to the end)", async () => {
    const { w, writes, hold } = await open(3)
    expect(hold).not.toBeNull()
    w.find('[data-testid="ost-input"]').element.dispatchEvent(new Event('keydown', { bubbles: true }))
    expect(hold!.disconnected).toBe(true)
    await live(9)
    expect(writes[writes.length - 1]).toBe(END)
    w.unmount()
  })

  it('control: with nothing unread it opens at the end, holds nothing, and a live message goes to the end', async () => {
    const { w, sc, writes, hold } = await open(8)
    expect(w.find('[data-testid="ost-unread-line"]').exists()).toBe(false)
    expect(hold, 'nothing held').toBeNull()
    expect(writes[writes.length - 1]).toBe(END)
    const before = writes.length
    await live(9)
    expect(writes.slice(before)).toContain(END)
    expect(sc).toBeTruthy()
    w.unmount()
  })

  it('a switch to another thread and an unmount end the hold', async () => {
    const { w, hold } = await open(3)
    expect(hold).not.toBeNull()
    h.route.params.id = 'cB'
    await flushPromises()
    expect(hold!.disconnected, 'the switch ended the first thread\'s hold').toBe(true)
    const second = FakeRO.all.filter(r => r !== hold && r.observed.includes(w.find('[data-testid="ost-messages"]').element))
    expect(second.length, 'the second thread (also unread) holds its own line').toBe(1)
    w.unmount()
    expect(second[0].disconnected, 'the unmount ended it').toBe(true)
  })
})
