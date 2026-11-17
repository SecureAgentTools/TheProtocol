import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): search in a thread. The header's Search opens a field; two
 * characters or more ask the registry (after a short pause), the lines found are drawn with the words marked, a press jumps
 * to a line (scrolled to when loaded, else older pages are read until it is). A stale answer is dropped; markup in a line is
 * text. BASE (c42be1743): no control, no API call. The harness is PocketOurStateThread.edit.test.ts's.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: {} as Record<string, any>,
  startConnected: true,
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


const hit = (seq: number, body: string, over: Record<string, any> = {}) => ({ id: `m${seq}`, seq, kind: 'text', body, sender_name: 'Mira',
  created_at: ago(120_000), conversation_id: 'room-a', ...over })
const hits = (w: any) => w.findAll('[data-testid^="ost-search-hit-"]')
async function openSearch(w: any) { await tid(w, 'ost-search-toggle').trigger('click'); await settle(2) }
async function typeQ(w: any, q: string) {
  await tid(w, 'ost-search-input').setValue(q)
  await vi.advanceTimersByTimeAsync(350)
  await settle(4)
}

describe('search in a thread', () => {
  beforeEach(() => { vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }) })
  afterEach(() => { vi.useRealTimers() })

  it('opens from the header, asks the registry after a pause and draws the lines with the words marked', async () => {
    h.chat.searchMessages = vi.fn().mockResolvedValue({ results: [hit(7, 'The Release train leaves'), hit(3, 'release notes')], more: false })
    const w = await open([line()])
    expect(tid(w, 'ost-search').exists()).toBe(false)
    await openSearch(w)
    await tid(w, 'ost-search-input').setValue('release')
    expect(h.chat.searchMessages).not.toHaveBeenCalled()                     // the pause: not on every keystroke
    await vi.advanceTimersByTimeAsync(350); await settle(4)
    expect(h.chat.searchMessages).toHaveBeenCalledTimes(1)
    expect(h.chat.searchMessages).toHaveBeenCalledWith(h.auth.token, 'room-a', 'release', undefined)
    expect(hits(w)).toHaveLength(2)
    expect(w.find('[data-testid="ost-search-hit-7"] mark').text()).toBe('Release')
    expect(w.find('[data-testid="ost-search-hit-7"]').text()).toContain('Mira')
  })
  it('asks nothing for one character and says so; asks again when it is longer', async () => {
    h.chat.searchMessages = vi.fn().mockResolvedValue({ results: [], more: false })
    const w = await open([line()])
    await openSearch(w)
    await typeQ(w, 'a')
    expect(h.chat.searchMessages).not.toHaveBeenCalled()
    expect(tid(w, 'ost-search-short').exists()).toBe(true)
    await typeQ(w, 'ab')
    expect(h.chat.searchMessages).toHaveBeenCalledTimes(1)
    expect(tid(w, 'ost-search-none').exists()).toBe(true)
  })
  it('says nothing was found, and says when the search itself failed', async () => {
    h.chat.searchMessages = vi.fn().mockRejectedValue(new Error('down'))
    const w = await open([line()])
    await openSearch(w)
    await typeQ(w, 'needle')
    expect(tid(w, 'ost-search-failed').exists()).toBe(true)
    expect(tid(w, 'ost-search-none').exists()).toBe(false)
  })
  it('More results continues below the last seq and appends', async () => {
    h.chat.searchMessages = vi.fn()
      .mockResolvedValueOnce({ results: [hit(9, 'needle nine'), hit(8, 'needle eight')], more: true, next_before_seq: 8 })
      .mockResolvedValueOnce({ results: [hit(5, 'needle five')], more: false, next_before_seq: null })
    const w = await open([line()])
    await openSearch(w)
    await typeQ(w, 'needle')
    await tid(w, 'ost-search-more').trigger('click')
    await settle(4)
    expect(h.chat.searchMessages).toHaveBeenLastCalledWith(h.auth.token, 'room-a', 'needle', 8)
    expect(hits(w)).toHaveLength(3)
    expect(tid(w, 'ost-search-more').exists()).toBe(false)
  })
  it('a stale answer does not replace a newer query\'s', async () => {
    let first: (v: any) => void = () => {}
    h.chat.searchMessages = vi.fn()
      .mockImplementationOnce(() => new Promise((res) => { first = res }))
      .mockResolvedValueOnce({ results: [hit(2, 'second query line')], more: false })
    const w = await open([line()])
    await openSearch(w)
    await typeQ(w, 'first')
    await typeQ(w, 'second')
    first({ results: [hit(1, 'first query line')], more: false })
    await settle(4)
    expect(hits(w).map((x: any) => x.attributes('data-testid'))).toEqual(['ost-search-hit-2'])
  })
  it('markup in a found line is shown as text, never as markup', async () => {
    h.chat.searchMessages = vi.fn().mockResolvedValue({ results: [hit(4, '<img src=x onerror=alert(1)> needle')], more: false })
    const w = await open([line()])
    await openSearch(w)
    await typeQ(w, 'needle')
    expect(w.find('[data-testid="ost-search-hit-4"] img').exists()).toBe(false)
    expect(w.find('[data-testid="ost-search-hit-4"]').text()).toContain('<img src=x onerror=alert(1)>')
  })
  it('Close (and Escape) shuts the panel and clears it', async () => {
    h.chat.searchMessages = vi.fn().mockResolvedValue({ results: [hit(7, 'needle')], more: false })
    const w = await open([line()])
    await openSearch(w)
    await typeQ(w, 'needle')
    await tid(w, 'ost-search-close').trigger('click')
    expect(tid(w, 'ost-search').exists()).toBe(false)
    await openSearch(w)
    expect((tid(w, 'ost-search-input').element as HTMLInputElement).value).toBe('')
    expect(hits(w)).toHaveLength(0)
    await tid(w, 'ost-search-input').trigger('keydown', { key: 'Escape' })
    expect(tid(w, 'ost-search').exists()).toBe(false)
  })
  it('a press on a loaded line scrolls to it and marks it for a moment', async () => {
    const scrolled = vi.fn()
    ;(Element.prototype as any).scrollIntoView = scrolled
    h.chat.searchMessages = vi.fn().mockResolvedValue({ results: [hit(2, 'needle two')], more: false })
    const w = await open([line(), line({ id: 'm2', seq: 2, sender_id: 2, body: 'needle two' })])
    await openSearch(w)
    await typeQ(w, 'needle')
    await tid(w, 'ost-search-hit-2').trigger('click')
    await settle(4)
    expect(scrolled).toHaveBeenCalled()
    expect(w.find('.ost-msg[data-seq="2"]').classes()).toContain('search-found')
    await vi.advanceTimersByTimeAsync(2600)
    expect(w.find('.ost-msg[data-seq="2"]').classes()).not.toContain('search-found')
  })
  it('a press on a line older than what is loaded reads older pages until it is, then scrolls to it', async () => {
    const scrolled = vi.fn()
    ;(Element.prototype as any).scrollIntoView = scrolled
    h.chat.searchMessages = vi.fn().mockResolvedValue({ results: [hit(3, 'needle old')], more: false })
    const page = Array.from({ length: 40 }, (_, k) => line({ id: `m${21 + k}`, seq: 21 + k, sender_id: 2, body: `line ${21 + k}` }))
    const w = await open(page)                                              // 40 lines: the registry has more before them
    h.chat.getMessages = vi.fn().mockResolvedValueOnce({ messages: [line({ id: 'm3', seq: 3, sender_id: 2, body: 'needle old' })], page_bound: 40 })
    await openSearch(w)
    await typeQ(w, 'needle')
    expect(w.find('.ost-msg[data-seq="3"]').exists()).toBe(false)
    await tid(w, 'ost-search-hit-3').trigger('click')
    await settle(6)
    expect(h.chat.getMessages).toHaveBeenCalledWith(h.auth.token, 'room-a', 21)
    expect(w.find('.ost-msg[data-seq="3"]').exists()).toBe(true)
    expect(scrolled).toHaveBeenCalled()
  })
})
