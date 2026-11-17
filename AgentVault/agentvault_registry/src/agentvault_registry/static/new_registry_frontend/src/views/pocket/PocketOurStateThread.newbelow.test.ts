import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0665 (order gwo_d9a1bc30946de40ff0ef9195, his report, room seq 4218: "When new messages come in on desktop. I get
 * scrolled down to it always. So when I read a message further up I lose it. Clickable pill should show new messages and
 * arrow down."): a live message takes the reader down only when they were near the bottom before it arrived; reading
 * further up, the place holds and a pill "3 new" counts what came in below, takes the reader to the FIRST of them and goes;
 * reaching the bottom by hand clears it; the reader's own message still takes them down. The rule itself is
 * services/chat/placeHold.ts (placeHold.test.ts). jsdom has no layout: the scroll box's numbers are set on the element.
 * The harness is PocketOurStateThread.mentions.test.ts's.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: {} as Record<string, any>,
  startConnected: true,
  base: '/pocket/ourchat',
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
  return { useOurChatBase: () => ({ base: ref(h.base) }) }
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

const last = <T,>(a: T[]): T | undefined => a[a.length - 1]
async function settle(n = 4) { for (let i = 0; i < n; i++) await flushPromises() }
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const line = (over: Record<string, any> = {}) => ({ id: 'm1', seq: 1, kind: 'text', body: 'hello', sender_ptype: 'developer', sender_id: 9, sender_name: 'Mira',
  conversation_id: 'room-a', created_at: new Date(Date.now() - 60_000).toISOString(), mentions: [], ...over })
const TEN = Array.from({ length: 10 }, (_v, i) => line({ id: `m${i + 1}`, seq: i + 1, body: `line ${i + 1}` }))

/** a thread of 10 read lines, open */
async function open() {
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages: TEN, last_seq: 10, page_bound: 40, kind: 'dm', my_state: 'active',
    my_last_read_seq: 10, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.getMentionsMe = vi.fn().mockResolvedValue({ messages: [] })
  const w = mount(PocketOurStateThread, opts)
  await settle()
  return w
}

/** the scroll box's numbers (jsdom has no layout): the thread is 2000 px tall in a 500 px box, `top` px scrolled */
function box(w: any, top: number, scrollHeight = 2000, clientHeight = 500) {
  const el = tid(w, 'ost-messages').element as HTMLElement
  const st = { top, writes: [] as number[], to: [] as any[] }
  Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => scrollHeight })
  Object.defineProperty(el, 'clientHeight', { configurable: true, get: () => clientHeight })
  Object.defineProperty(el, 'scrollTop', { configurable: true, get: () => st.top, set: (v: number) => { st.top = v; st.writes.push(v) } })
  ;(el as any).scrollTo = (a: any) => { st.to.push(a); if (typeof a?.top === 'number') st.top = a.top }
  return st
}
async function arrive(msg: any) {
  h.stream.onMessage({ conversation_id: 'room-a', message: line(msg) })
  await settle()
}
const reducedMotion = (on: boolean) => {
  ;(window as any).matchMedia = (q: string) => ({ matches: on && String(q).includes('reduce'), media: q, addEventListener() {}, removeEventListener() {},
    addListener() {}, removeListener() {} })
}

beforeEach(() => {
  setActivePinia(createPinia())
  h.chat = {}
  h.stream = {}
  h.startConnected = true
  h.route.params.id = 'room-a'
  h.base = '/pocket/ourchat'
  h.auth.activeAgent = null
  localStorage.clear()
  reducedMotion(false)
})
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks(); delete (window as any).matchMedia })

describe('a message arrives while the reader is near the bottom', () => {
  it('takes them down, as before, and shows no pill', async () => {
    const w = await open()
    const st = box(w, 1500)                                   // 2000 - 1500 - 500 = 0 px from the end
    await arrive({ id: 'n1', seq: 11, body: 'new' })
    expect(last(st.writes)).toBe(2000)
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(false)
  })
})

describe('a message arrives while the reader is further up', () => {
  it('holds the place (no scroll write at all) and counts it: "1 new", then "3 new"', async () => {
    const w = await open()
    const st = box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    expect(st.writes).toEqual([])
    expect(st.top).toBe(300)
    expect(tid(w, 'ost-newbelow-pill').text()).toBe('1 new')
    await arrive({ id: 'n2', seq: 12 })
    await arrive({ id: 'n3', seq: 13 })
    expect(st.writes).toEqual([])
    expect(tid(w, 'ost-newbelow-pill').text()).toBe('3 new')
  })

  it('the reader\'s own message still takes them down, and clears the pill', async () => {
    const w = await open()
    const st = box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(true)
    await arrive({ id: 'n2', seq: 12, sender_id: 6, body: 'mine' })       // developer 6 is the reader
    expect(last(st.writes)).toBe(2000)
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(false)
  })

  it('counts a message that came through a catch-up read (the socket was away) just the same, and not the reader\'s own', async () => {
    const w = await open()
    const st = box(w, 300)
    h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [...TEN, line({ id: 'c1', seq: 11 }), line({ id: 'c2', seq: 12, sender_id: 6 }),
      line({ id: 'c3', seq: 13 })], last_seq: 13, page_bound: 40, kind: 'dm', my_state: 'active', my_last_read_seq: 10, counterparty: null })
    window.dispatchEvent(new Event('focus'))
    await settle(6)
    expect(st.writes).toEqual([])
    expect(tid(w, 'ost-newbelow-pill').text()).toBe('2 new')              // seq 11 and 13; seq 12 is the reader's own
  })
})

describe('the pill', () => {
  it('takes the reader to the FIRST new message, not past it, and goes', async () => {
    const w = await open()
    const st = box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    await arrive({ id: 'n2', seq: 12 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('ost-scroll')) return { top: 100, bottom: 600, left: 0, right: 300, width: 300, height: 500 } as DOMRect
      const seq = this.getAttribute('data-seq')
      const top = seq === '11' ? 1500 : seq === '12' ? 1560 : 0           // 1500 px below the box's top edge, in view coordinates
      return { top, bottom: top + 50, left: 0, right: 300, width: 300, height: 50 } as DOMRect
    })
    await tid(w, 'ost-newbelow-pill').trigger('click')
    await settle()
    // the first new line is 1400 px below the box's top: scrollTop moves by that, less the 8 px the unread line keeps
    expect(last(st.to)).toEqual({ top: 300 + (1500 - 100) - 8, behavior: 'smooth' })
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(false)
  })

  it('does not scroll smoothly when the reader asked for reduced motion', async () => {
    reducedMotion(true)
    const w = await open()
    const st = box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('ost-scroll')) return { top: 100, bottom: 600, left: 0, right: 300, width: 300, height: 500 } as DOMRect
      const top = this.getAttribute('data-seq') === '11' ? 1500 : 0
      return { top, bottom: top + 50, left: 0, right: 300, width: 300, height: 50 } as DOMRect
    })
    await tid(w, 'ost-newbelow-pill').trigger('click')
    await settle()
    expect(st.to).toEqual([])                                 // no scrollTo with a behavior
    expect(last(st.writes)).toBe(300 + (1500 - 100) - 8)     // a plain position
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(false)
  })

  it('goes when the reader reaches the bottom by hand', async () => {
    const w = await open()
    const st = box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(true)
    st.top = 1450                                             // 50 px from the end: near the bottom
    await tid(w, 'ost-messages').trigger('scroll')
    await settle()
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(false)
  })

  it('has a name for a screen reader, says "new" with the number, and sits beside the Mentions pill\'s row', async () => {
    const w = await open()
    box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    const pill = tid(w, 'ost-newbelow-pill')
    expect(pill.attributes('aria-label')).toBe('1 new message below, go to it')
    expect(pill.element.parentElement?.getAttribute('data-testid')).toBe('ost-pills')   // one row holds both pills
  })
})

describe('a new conversation starts with no pill', () => {
  it('forgets what was counted when the thread changes', async () => {
    const w = await open()
    box(w, 300)
    await arrive({ id: 'n1', seq: 11 })
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(true)
    h.route.params.id = 'room-b'
    await settle(6)
    expect(tid(w, 'ost-newbelow-pill').exists()).toBe(false)
  })
})
