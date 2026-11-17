import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b / the batch's item 4): a link to one message. Copy link puts the
 * thread's address and the message id on the clipboard; a thread opened at `?m=<id>` scrolls to that line (older pages are read
 * until it is loaded), marks it, drops the parameter, and says so when the line is gone. BASE (0f0977fb4): no control, no
 * handling. The harness is PocketOurStateThread.edit.test.ts's.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: {} as Record<string, any>,
  startConnected: true,
  replace: null as any,
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
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: (h.replace ??= vi.fn().mockResolvedValue(undefined)) }),
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
  h.replace = vi.fn().mockResolvedValue(undefined)
  h.route.params.id = 'room-a'
  h.auth.activeAgent = null
  localStorage.clear()
})
afterEach(() => { document.body.innerHTML = '' })


describe('copying a link to a message', () => {
  it('puts the thread\'s address and the message id on the clipboard and says so for a moment', async () => {
    const write = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', { clipboard: { writeText: write } })
    const w = await open([line({ id: 'm-aaaa-1111', seq: 1 })])
    await tid(w, 'ost-link-1').trigger('click')
    await settle(3)
    expect(write).toHaveBeenCalledTimes(1)
    const url = String(write.mock.calls[0][0])
    expect(url.endsWith('#/pocket/ourchat/room-a?m=m-aaaa-1111')).toBe(true)
    expect(url.startsWith(window.location.origin)).toBe(true)
    expect(tid(w, 'ost-link-1').text()).toBe('Link copied')
    vi.unstubAllGlobals()
  })
  it('says the link could not be copied when nothing can copy', async () => {
    vi.stubGlobal('navigator', {})
    ;(document as any).execCommand = vi.fn(() => false)
    const w = await open([line()])
    await tid(w, 'ost-link-1').trigger('click')
    await settle(3)
    expect(tid(w, 'ost-link-1').text()).toBe('The link could not be copied')
    vi.unstubAllGlobals()
    delete (document as any).execCommand
  })
  it('is offered on a text line and a card, not on a system line or one taken back', async () => {
    const w = await open([line(), line({ id: 'm2', seq: 2, kind: 'card', body: null, card: { type: 'media' } }),
      line({ id: 'm3', seq: 3, kind: 'system', body: 'x' }), line({ id: 'm4', seq: 4, deleted: true, kind: 'system', body: null })])
    expect(tid(w, 'ost-link-1').exists()).toBe(true)
    expect(tid(w, 'ost-link-2').exists()).toBe(true)
    expect(tid(w, 'ost-link-3').exists()).toBe(false)
    expect(tid(w, 'ost-link-4').exists()).toBe(false)
  })
})

describe('opening a thread at a linked message', () => {
  const stage = () => { ;(Element.prototype as any).scrollIntoView = vi.fn(); return (Element.prototype as any).scrollIntoView as ReturnType<typeof vi.fn> }
  it('scrolls to a loaded line, marks it and drops the parameter', async () => {
    const scrolled = stage()
    h.route.query.m = 'm-bbbb-2222'
    const w = await open([line(), line({ id: 'm-bbbb-2222', seq: 2, sender_id: 2, body: 'the linked one' })])
    await settle(6)
    expect(scrolled).toHaveBeenCalled()
    expect(w.find('.ost-msg[data-seq="2"]').classes()).toContain('search-found')
    expect(h.replace).toHaveBeenCalledWith({ query: expect.objectContaining({ m: undefined }) })
    delete h.route.query.m
  })
  it('reads older pages until the line is loaded', async () => {
    const scrolled = stage()
    h.route.query.m = 'm-cccc-0003'
    const page = Array.from({ length: 40 }, (_, k) => line({ id: `m${21 + k}`, seq: 21 + k, sender_id: 2, body: `line ${21 + k}` }))
    h.chat.getMessages = vi.fn()
      .mockResolvedValueOnce({ messages: page, last_seq: 60, page_bound: 40, kind: 'dm', my_state: 'active', my_last_read_seq: 60,
        counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
      .mockResolvedValueOnce({ messages: [line({ id: 'm-cccc-0003', seq: 3, sender_id: 2, body: 'old linked' })], page_bound: 40 })
    h.chat.markRead = vi.fn().mockResolvedValue({})
    const w = mount(PocketOurStateThread, opts)
    await settle(10)
    expect(h.chat.getMessages).toHaveBeenCalledWith(h.auth.token, 'room-a', 21)
    expect(w.find('.ost-msg[data-seq="3"]').exists()).toBe(true)
    expect(scrolled).toHaveBeenCalled()
    delete h.route.query.m
  })
  it('says so when the line is gone (and still opens the thread)', async () => {
    stage()
    h.route.query.m = 'm-dddd-9999'
    const w = await open([line()])
    await settle(6)
    expect(tid(w, 'ost-link-missing').exists()).toBe(true)
    expect(w.text()).toContain('first draft')
    delete h.route.query.m
  })
  it('ignores a value that is not an id', async () => {
    const scrolled = stage()
    h.route.query.m = '<img src=x>'
    const w = await open([line()])
    await settle(4)
    expect(scrolled).not.toHaveBeenCalled()
    expect(tid(w, 'ost-link-missing').exists()).toBe(false)
    delete h.route.query.m
  })
})

describe('Quote', () => {
  const box = (w: any) => w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement
  it('puts the line into the composer as a markdown quote, after what is written, and posts nothing', async () => {
    const w = await open([line({ id: 'm1', seq: 1, sender_id: 2, sender_name: 'Mira', body: 'we ship on Friday' })])
    await w.find('[data-testid="ost-input"]').setValue('I think')
    await tid(w, 'ost-quote-1').trigger('click')
    await settle(3)
    expect(box(w).value).toBe('I think\n\n> Mira: we ship on Friday\n\n')
    expect(h.chat.postMessage).toBeUndefined()
  })
  it('is not offered on a card, a taken-back line or a /me action', async () => {
    const w = await open([line({ id: 'm2', seq: 2, kind: 'card', body: null, card: { type: 'media' } }),
      line({ id: 'm3', seq: 3, deleted: true, kind: 'system', body: null }), line({ id: 'm4', seq: 4, body: '/me waves' })])
    expect(tid(w, 'ost-quote-2').exists()).toBe(false)
    expect(tid(w, 'ost-quote-3').exists()).toBe(false)
    expect(tid(w, 'ost-quote-4').exists()).toBe(false)
  })
  it('the quote renders as a quotation once sent (the renderer draws > lines as a blockquote)', async () => {
    const { renderMarkdown } = await import('@/services/chat/messageText')
    expect(renderMarkdown('> Mira: we ship on Friday\n\nagreed')).toContain('<blockquote>')
  })
})
