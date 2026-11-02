import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (ac) (order gwo_2ae43c7789db1e808ea1417f): threads and the status board, in the open room. An order's messages
 * fold into one entry drawn where the order's latest message is, its bar saying how many; Show opens them under the root.
 * Reply answers a message (the composer says so; the message carries reply_to) and the thread it joins opens, so your
 * own message never vanishes into a fold, nor one that names you. The room's board is pinned above the history (narrow
 * and Pocket), and a board update on the socket shows at once. BASE (V0651): no fold, no Reply, no board.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: null as null | { onMessage: (env: any) => void; onBoardUpdate: (env: any) => void },
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: vi.fn().mockResolvedValue({ agents: [] }) } }))
vi.mock('@/services/api/client', () => {
  const c = { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn(), put: vi.fn(), delete: vi.fn() }
  return { default: c, apiClient: c }
})
vi.mock('@/services/chat/localCache', () => ({
  getThread: vi.fn().mockResolvedValue(null), putThread: vi.fn().mockResolvedValue(false), dropThread: vi.fn(),
  cacheAvailable: () => false, burnDeviceNote: () => '',
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok', user: { developer_id: 6 }, agentToken: null }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev-tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: (o: any) => { h.stream = o } }))
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
  h.route = reactive({ params: { id: 'room1' }, query: {}, path: '/pocket/ourchat/room1' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true },
  },
}
const A = 'gwo_' + 'a'.repeat(24)
const text = (id: string, seq: number, body: string, extra: Record<string, unknown> = {}) => ({ id, seq, kind: 'text', body,
  sender_ptype: 'developer', sender_id: '7', sender_name: 'Mira', created_at: '2026-11-01T00:00:00Z', ...extra })
const room = (board: unknown) => ({ org_id: 'org1', title: 'TheProtocol Sessions', mode: 'open', topic: null, board })
const page = (messages: unknown[], board: unknown = null) => ({ messages, last_seq: messages.length, page_bound: 40, kind: 'org',
  my_state: 'active', my_last_read_seq: 99, counterparty: null, room: room(board) })
const shownIds = (w: any) => w.findAll('[data-testid^="ost-msg-"]').map((x: any) => x.attributes('data-testid'))

describe('threads and the status board, in the open room', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.stream = null
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
    h.chat.listApprovals = vi.fn().mockResolvedValue({ items: [], can_decide: true, presence: 'off' })
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it("an order's messages fold into one entry where its latest message is; Show opens them under the root", async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('o1', 1, `ORDER ${A}: build`), text('x1', 2, 'unrelated'),
      text('o2', 3, `BID on ${A}`), text('x2', 4, 'unrelated too'), text('o3', 5, `DONE ${A}`)]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(shownIds(w)).toEqual(['ost-msg-2', 'ost-msg-4', 'ost-msg-1'])
    const bar = w.find('[data-testid="ost-thread-1"]')
    expect(bar.text()).toContain('2 more about gwo_aaaaaaaa')
    expect(bar.attributes('aria-expanded')).toBe('false')
    await bar.trigger('click')
    expect(shownIds(w)).toEqual(['ost-msg-2', 'ost-msg-4', 'ost-msg-1', 'ost-msg-3', 'ost-msg-5'])
    expect(w.find('[data-testid="ost-msg-3"]').classes()).toContain('in-thread')
    w.unmount()
  })

  it('a message that names you and an order is in view without a click; Hide folds it and it stays folded (seq 419)', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue({ ...page([text('o1', 1, `ORDER ${A}: build`),
      text('o2', 2, `@maintainer can you approve ${A}?`, { mentions: [{ key: 'dev:6' }] }), text('x', 3, 'unrelated')]),
      my_last_read_seq: 1 })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(shownIds(w)).toEqual(['ost-msg-1', 'ost-msg-2', 'ost-msg-3'])
    const bar = w.find('[data-testid="ost-thread-1"]')
    expect(bar.attributes('aria-expanded')).toBe('true')
    expect(bar.text()).toContain('1 for you')
    await bar.trigger('click')
    expect(shownIds(w)).toEqual(['ost-msg-1', 'ost-msg-3'])
    expect(w.find('[data-testid="ost-thread-1"]').attributes('aria-expanded')).toBe('false')
    // a newer message for you opens it again (seq 425); one that is not for you does not
    h.stream!.onMessage({ conversation_id: 'room1', message: text('o4', 4, `BID again on ${A}`) })
    await flushPromises()
    expect(w.find('[data-testid="ost-thread-1"]').attributes('aria-expanded')).toBe('false')
    h.stream!.onMessage({ conversation_id: 'room1', message: text('o5', 5, `@maintainer one more on ${A}`, { mentions: [{ key: 'dev:6' }] }) })
    await flushPromises()
    expect(w.find('[data-testid="ost-thread-1"]').attributes('aria-expanded')).toBe('true')
    expect(shownIds(w)).toContain('ost-msg-5')
    w.unmount()
    // read already: the same thread is folded
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('o1', 1, `ORDER ${A}: build`),
      text('o2', 2, `@maintainer can you approve ${A}?`, { mentions: [{ key: 'dev:6' }] }), text('x', 3, 'unrelated')]))
    const again = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(shownIds(again)).toEqual(['ost-msg-1', 'ost-msg-3'])
    again.unmount()
  })

  it('Reply answers a message: the composer says so, the message carries reply_to, and its thread opens', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('q', 1, 'Which slot for the roll?'), text('x', 2, 'other')]))
    h.chat.postMessage = vi.fn().mockImplementation(async (_t: string, _c: string, p: any) => ({ my_state: 'active',
      message: text('r1', 3, p.body, { reply_to: p.reply_to, sender_id: '6', sender_name: 'maintainer' }) }))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    await w.find('[data-testid="ost-reply-1"]').trigger('click')
    expect(w.find('[data-testid="ost-replying"]').text()).toContain('Which slot for the roll?')
    await w.find('textarea').setValue('05:00Z')
    await w.find('[data-testid="ost-send"]').trigger('click')
    await flushPromises()
    expect(h.chat.postMessage.mock.calls[0][2]).toMatchObject({ kind: 'text', body: '05:00Z', reply_to: 'q' })
    expect(w.find('[data-testid="ost-replying"]').exists()).toBe(false)
    expect(shownIds(w)).toEqual(['ost-msg-2', 'ost-msg-1', 'ost-msg-3'])     // the thread at its latest, opened
    expect(w.find('[data-testid="ost-thread-1"]').attributes('aria-expanded')).toBe('true')
    w.unmount()
  })

  it('the board is pinned above the history, and an update on the socket shows at once', async () => {
    const b = { text: 'V0651 at 05:00Z', rev: 1, updated_at: '2026-11-01T01:00:00Z',
      updated_by: { ptype: 'developer', id: '6', name: 'maintainer' }, can_edit: false }
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('x', 1, 'hello')], b))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const board = w.find('[data-testid="ost-board"]')
    const scroll = w.find('[data-testid="ost-messages"]')
    expect(board.exists() && !scroll.element.contains(board.element)).toBe(true)
    expect(board.text()).toContain('V0651 at 05:00Z')
    h.stream!.onBoardUpdate({ conversation_id: 'room1', board: { ...b, text: 'V0651 is on production', rev: 2 } })
    await flushPromises()
    expect(w.find('[data-testid="ost-board"]').text()).toContain('V0651 is on production')
    h.stream!.onBoardUpdate({ conversation_id: 'room1', board: { ...b, text: 'stale', rev: 1 } })
    await flushPromises()
    expect(w.find('[data-testid="ost-board"]').text()).toContain('V0651 is on production')    // an older one changes nothing
    w.unmount()
  })

  it('a member sees no board strip while the board is empty', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page([text('x', 1, 'hello')],
      { text: '', rev: 0, updated_at: null, updated_by: null, can_edit: false }))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-board"]').exists()).toBe(false)
    w.unmount()
  })
})

/**
 * V0653 (al) (order gwo_2f0d7d69673b8f9c9392e5dc): his report (the sessions' room, seq 665: a request "showed timestamp
 * 6:37 but the previous messages says 8:31pm"), and session-lead's review (seq 685: the thread bar's parts joined in the
 * text run, "1 newlast:"). A root drawn at its latest reply also says when that reply came; the bar's parts are apart in
 * the text a screen reader reads. BASE (V0652): only the root's own time, and the parts ran together.
 */
describe("a thread's root and bar, read in order", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.stream = null
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
    h.chat.listApprovals = vi.fn().mockResolvedValue({ items: [], can_decide: true, presence: 'off' })
  })
  afterEach(() => { vi.unstubAllGlobals() })

  const thread = () => [
    text('r1', 1, 'Roll the faucet off?', { created_at: '2026-11-01T17:37:00Z' }),
    text('x1', 2, 'meanwhile', { created_at: '2026-11-01T19:31:00Z' }),
    text('r2', 3, 'approved', { reply_to: 'r1', sender_id: '8', sender_name: 'Theo', created_at: '2026-11-01T20:00:07Z' }),
  ]

  it('the root, drawn at its latest reply, says when that reply came; its own time stays', async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue(page(thread()))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(shownIds(w)).toEqual(['ost-msg-2', 'ost-msg-1'])          // the root sits after the 19:31 message
    expect(w.find('[data-testid="ost-time-1"]').attributes('datetime')).toBe('2026-11-01T17:37:00Z')
    const last = w.find('[data-testid="ost-time-last-1"]')
    expect(last.exists()).toBe(true)
    expect(last.text()).toMatch(/^, last reply \S/)
    expect(w.find('[data-testid="ost-time-last-2"]').exists()).toBe(false)   // a message outside a thread: its own time only
    w.unmount()
  })

  it("the bar's parts are apart in the text run: count, new, last, the action", async () => {
    h.chat.getMessages = vi.fn().mockResolvedValue({ ...page(thread()), my_last_read_seq: 1 })
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const run = w.find('[data-testid="ost-thread-1"]').text()
    expect(run).toMatch(/^1 reply, 1 new, last: Theo, .+, Show$/)
    expect(run).not.toMatch(/new(last|Show)/)
    w.unmount()
  })
})
