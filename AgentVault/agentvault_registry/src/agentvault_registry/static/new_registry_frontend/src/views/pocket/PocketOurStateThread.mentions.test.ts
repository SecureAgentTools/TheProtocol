import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0663 (order gwo_7dd5a9be91eede9c2cc35376, his request seq 3349): mentions you cannot miss, in the thread. A line that names
 * YOU (the registry's stored mention of your key) is marked; an @all line, your own line and a deleted one are not. A pill
 * "Mentioned you" (", 2" for two) shows while an unread mention sits outside the view and takes you to the oldest; a line you
 * have seen leaves it. The thread asks the registry for its mentions of you (mentions=me) so one older than the page counts too.
 * The harness is PocketOurStateThread.pins.test.ts's.
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

const ago = (ms: number) => new Date(Date.now() - ms).toISOString()
async function settle(n = 4) { for (let i = 0; i < n; i++) await flushPromises() }
const YOU = [{ key: 'dev:6' }]
async function open(messages: any[], opts2: { read?: number; mentionsRead?: any } = {}) {
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages, last_seq: messages.length, page_bound: 40, kind: 'dm', my_state: 'active',
    my_last_read_seq: opts2.read ?? 0, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.getMentionsMe = opts2.mentionsRead ?? vi.fn().mockResolvedValue({ messages: messages.filter((m) => (m.mentions || []).length) })
  const w = mount(PocketOurStateThread, opts)
  await settle()
  return w
}
/** the console's chat in an organization's room on a wide pane: the side panel (and its Mentions section) shows */
async function openDesk(messages: any[]) {
  h.base = '/ourchat'
  vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(1400)
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages, last_seq: messages.length, page_bound: 40, kind: 'org', room: { org_id: 'org-1' }, my_state: 'active',
    my_last_read_seq: 0, counterparty: null })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.getMentionsMe = vi.fn().mockResolvedValue({ messages: messages.filter((m) => (m.mentions || []).length) })
  const w = mount(PocketOurStateThread, opts)
  await settle()
  return w
}
const tid = (w: any, id: string) => w.find(`[data-testid="${id}"]`)
const line = (over: Record<string, any> = {}) => ({ id: 'm1', seq: 1, kind: 'text', body: 'hello', sender_ptype: 'developer', sender_id: 9, sender_name: 'Mira',
  conversation_id: 'room-a', created_at: new Date(Date.now() - 60_000).toISOString(), mentions: [], ...over })

beforeEach(() => {
  setActivePinia(createPinia())
  h.chat = {}
  h.stream = {}
  h.startConnected = true
  h.route.params.id = 'room-a'
  h.base = '/pocket/ourchat'
  h.auth.activeAgent = null
  localStorage.clear()
})
afterEach(() => { document.body.innerHTML = ''; vi.restoreAllMocks() })

describe('the marked line', () => {
  it('marks a line that names you, and only that', async () => {
    const w = await open([
      line({ id: 'a', seq: 1, body: 'hi @him', mentions: YOU }),
      line({ id: 'b', seq: 2, body: '@all lunch?' }),                                            // names nobody by name
      line({ id: 'c', seq: 3, body: 'note to self @him', sender_id: 6, mentions: YOU }),          // your own line
      line({ id: 'd', seq: 4, body: 'gone', mentions: YOU, deleted: true }),
    ])
    expect(tid(w, 'ost-msg-1').classes()).toContain('mentioned-you')
    expect(tid(w, 'ost-at-tag-1').exists()).toBe(true)
    for (const s of [2, 3, 4]) {
      expect(tid(w, `ost-msg-${s}`).classes(), `line ${s}`).not.toContain('mentioned-you')
      expect(tid(w, `ost-at-tag-${s}`).exists(), `line ${s}`).toBe(false)
    }
  })
})

describe('the pill', () => {
  it('says "Mentioned you" for one unread mention outside the view and ", 2" for two', async () => {
    const w = await open([line({ id: 'a', seq: 1, mentions: YOU }), line({ id: 'b', seq: 2 })])
    expect(tid(w, 'ost-mention-pill').text()).toBe('Mentioned you')
    await w.unmount()
    const w2 = await open([line({ id: 'a', seq: 1, mentions: YOU }), line({ id: 'b', seq: 2, mentions: YOU })])
    expect(tid(w2, 'ost-mention-pill').text()).toBe('Mentioned you, 2')
  })

  it('is absent when every mention is above the read mark, and when nobody named you', async () => {
    const w = await open([line({ id: 'a', seq: 1, mentions: YOU }), line({ id: 'b', seq: 2 })], { read: 2 })
    expect(tid(w, 'ost-mention-pill').exists()).toBe(false)
    await w.unmount()
    const w2 = await open([line({ id: 'a', seq: 1, body: '@all hi' })])
    expect(tid(w2, 'ost-mention-pill').exists()).toBe(false)
  })

  it('takes you to the oldest unread mention', async () => {
    const scrollTo = vi.fn()
    ;(Element.prototype as any).scrollIntoView = function () { scrollTo(this.getAttribute('data-seq')) }
    const w = await open([line({ id: 'a', seq: 1 }), line({ id: 'b', seq: 2, mentions: YOU }), line({ id: 'c', seq: 3, mentions: YOU })])
    expect(tid(w, 'ost-mention-pill').text()).toBe('Mentioned you, 2')
    await tid(w, 'ost-mention-pill').trigger('click')
    await settle()
    expect(scrollTo).toHaveBeenCalledWith('2')
  })

  it('lets go of a mention once its line has been in view', async () => {
    const rects = vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
      if (this.classList.contains('ost-scroll')) return { top: 0, bottom: 500, left: 0, right: 300, width: 300, height: 500 } as DOMRect
      const seq = this.getAttribute('data-seq')
      const top = seq === '2' ? 100 : 900          // the mention's line is inside the container; line 3 is far below
      return { top, bottom: top + 40, left: 0, right: 300, width: 300, height: 40 } as DOMRect
    })
    const w = await open([line({ id: 'a', seq: 1 }), line({ id: 'b', seq: 2, mentions: YOU }), line({ id: 'c', seq: 3, mentions: YOU })])
    await tid(w, 'ost-messages').trigger('scroll')
    await new Promise((r) => setTimeout(r, 40)); await settle()
    expect(tid(w, 'ost-mention-pill').text()).toBe('Mentioned you')       // line 2 seen; line 3 still waits out of view
    expect(rects).toHaveBeenCalled()
  })
})

describe('the registry read', () => {
  it('asks for the mentions of you with the thread, so one older than the page counts', async () => {
    const old = line({ id: 'old', seq: 3, body: 'long ago @him', mentions: YOU })
    const w = await open([line({ id: 'x', seq: 50 }), line({ id: 'y', seq: 51 })],
      { read: 0, mentionsRead: vi.fn().mockResolvedValue({ messages: [old] }) })
    expect(h.chat.getMentionsMe).toHaveBeenCalledWith('dev.tok', 'room-a')
    expect(tid(w, 'ost-mention-pill').text()).toBe('Mentioned you')       // known to the registry, not on the page
  })

  it('a failed read leaves the lines already on the page marked and raises no error', async () => {
    const w = await open([line({ id: 'a', seq: 1, mentions: YOU })], { mentionsRead: vi.fn().mockRejectedValue(new Error('503')) })
    expect(tid(w, 'ost-msg-1').classes()).toContain('mentioned-you')
    expect(tid(w, 'ost-mention-pill').exists()).toBe(true)
  })
})

describe('the side panel\'s Mentions section (his report, seq 4032)', () => {
  it('lists the unread mentions and "Mark all read" moves this room\'s read mark to its newest message, once, and empties the list', async () => {
    const w = await openDesk([line({ id: 'a', seq: 1, mentions: YOU }), line({ id: 'b', seq: 2, mentions: YOU }), line({ id: 'c', seq: 3 })])
    expect(w.findAll('[data-testid="cml-unread-list"] [data-testid^="cml-row-"]')).toHaveLength(2)
    h.chat.markRead.mockClear()
    await tid(w, 'cml-markall').trigger('click')
    await settle()
    expect(h.chat.markRead).toHaveBeenCalledTimes(1)
    expect(h.chat.markRead).toHaveBeenCalledWith('dev.tok', 'room-a', 3)
    expect(tid(w, 'cml-unread-list').exists()).toBe(false)
    expect(tid(w, 'cml-allread').exists()).toBe(true)
    expect(tid(w, 'cml-earlier-sum').text()).toBe('Earlier mentions (2)')
    expect(tid(w, 'ost-mention-pill').exists()).toBe(false)            // the pill follows the same mark
  })

  it('says so when the mark could not be moved, and keeps the list', async () => {
    const w = await openDesk([line({ id: 'a', seq: 1, mentions: YOU })])
    h.chat.markRead = vi.fn().mockRejectedValue(new Error('503'))
    await tid(w, 'cml-markall').trigger('click')
    await settle()
    expect(tid(w, 'cml-mark-failed').exists()).toBe(true)
    expect(tid(w, 'cml-unread-list').exists()).toBe(true)
  })
})
