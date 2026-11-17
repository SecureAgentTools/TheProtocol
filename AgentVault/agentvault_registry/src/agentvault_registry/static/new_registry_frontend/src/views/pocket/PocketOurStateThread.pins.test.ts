import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): pinned messages. The thread reads the registry's pins on open and
 * draws a strip under its header (the count, the newest pin, opened to the list); Pin / Unpin appears on a line only where
 * the registry says can_pin; a press asks the registry and reads the list again; the socket's pins_changed reads it again
 * too; a pin in the list jumps to its line. BASE (b4591d1af): no strip, no call. The harness is PocketOurStateThread.edit.test.ts's.
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


const pinRow = (seq: number, body: string, over: Record<string, any> = {}) => ({
  message: { id: `m${seq}`, seq, kind: 'text', body, sender_name: 'Mira', created_at: ago(120_000), conversation_id: 'room-a', ...over },
  pinned_by: { ptype: 'developer', id: 6, name: 'me' }, at: ago(60_000) })
async function openWith(messages: any[], pinsAnswer: any) {
  h.chat.listPins = vi.fn().mockResolvedValue(pinsAnswer)
  return open(messages)
}

describe('the pins strip', () => {
  it('is not there when the thread has no pins, and asks the registry on open', async () => {
    const w = await openWith([line()], { pins: [], can_pin: true, max: 10 })
    expect(h.chat.listPins).toHaveBeenCalledWith(h.auth.token, 'room-a')
    expect(tid(w, 'ost-pins').exists()).toBe(false)
  })
  it('shows the count and the newest pin, opens to the list, and a press jumps to the line', async () => {
    ;(Element.prototype as any).scrollIntoView = vi.fn()
    const w = await openWith([line({ id: 'm2', seq: 2, sender_id: 2, body: 'the plan' })], { pins: [pinRow(2, 'the plan'), pinRow(1, 'older pin')], can_pin: false, max: 10 })
    expect(tid(w, 'ost-pins').text()).toContain('2 pinned')
    expect(tid(w, 'ost-pins').text()).toContain('the plan')
    expect(tid(w, 'ost-pin-jump-1').exists()).toBe(false)                                  // closed: only the newest
    await tid(w, 'ost-pins-toggle').trigger('click')
    expect(tid(w, 'ost-pin-jump-1').exists()).toBe(true)
    expect(tid(w, 'ost-pin-off-2').exists()).toBe(false)                                   // can_pin false: no Unpin
    await tid(w, 'ost-pin-jump-2').trigger('click')
    await settle(4)
    expect((Element.prototype as any).scrollIntoView).toHaveBeenCalled()
  })
  it('a press on Unpin in the list asks the registry and reads the list again', async () => {
    h.chat.unpinMessage = vi.fn().mockResolvedValue({ removed: true })
    const w = await openWith([line({ id: 'm2', seq: 2 })], { pins: [pinRow(2, 'the plan')], can_pin: true, max: 10 })
    h.chat.listPins = vi.fn().mockResolvedValue({ pins: [], can_pin: true, max: 10 })
    await tid(w, 'ost-pins-toggle').trigger('click')
    await tid(w, 'ost-pin-off-2').trigger('click')
    await settle(4)
    expect(h.chat.unpinMessage).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm2')
    expect(h.chat.listPins).toHaveBeenCalled()
    expect(tid(w, 'ost-pins').exists()).toBe(false)
  })
})

describe('Pin on a line', () => {
  it('is offered only where the registry says can_pin, and says Unpin on a pinned line', async () => {
    const no = await openWith([line()], { pins: [], can_pin: false, max: 10 })
    expect(tid(no, 'ost-pin-1').exists()).toBe(false)
    const yes = await openWith([line(), line({ id: 'm2', seq: 2 })], { pins: [pinRow(2, 'x')], can_pin: true, max: 10 })
    expect(tid(yes, 'ost-pin-1').text()).toBe('Pin')
    expect(tid(yes, 'ost-pin-2').text()).toBe('Unpin')
  })
  it('pins through the registry and then reads the list again', async () => {
    h.chat.pinMessage = vi.fn().mockResolvedValue({ added: true })
    const w = await openWith([line()], { pins: [], can_pin: true, max: 10 })
    h.chat.listPins = vi.fn().mockResolvedValue({ pins: [pinRow(1, 'first draft')], can_pin: true, max: 10 })
    await tid(w, 'ost-pin-1').trigger('click')
    await settle(4)
    expect(h.chat.pinMessage).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1')
    expect(tid(w, 'ost-pins').text()).toContain('1 pinned')
    expect(tid(w, 'ost-pin-1').text()).toBe('Unpin')
  })
  it('shows the registry\'s refusal as its sentence', async () => {
    h.chat.pinMessage = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'a thread keeps 10 pins: take one off first' }))
    const w = await openWith([line({ id: 'm2', seq: 2 }), line()], { pins: Array.from({ length: 1 }, () => pinRow(2, 'p')), can_pin: true, max: 10 })
    await tid(w, 'ost-pins-toggle').trigger('click')
    await tid(w, 'ost-pin-1').trigger('click')
    await settle(4)
    expect(tid(w, 'ost-pins').text()).toContain('a thread keeps 10 pins')
  })
  it('an answer for a thread no longer on screen is dropped', async () => {
    let late: (v: any) => void = () => {}
    h.chat.listPins = vi.fn().mockImplementationOnce(() => new Promise((res) => { late = res })).mockResolvedValue({ pins: [], can_pin: false, max: 10 })
    h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [line()], last_seq: 1, page_bound: 40, kind: 'dm', my_state: 'active',
      my_last_read_seq: 1, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
    h.chat.markRead = vi.fn().mockResolvedValue({})
    const w = mount(PocketOurStateThread, opts)
    await settle(3)
    h.route.params.id = 'room-b'                                     // the person moved to another thread
    await settle(4)
    late({ pins: [pinRow(1, 'from the old thread')], can_pin: true, max: 10 })
    await settle(4)
    expect(tid(w, 'ost-pins').exists()).toBe(false)
  })
  it('the socket\'s pins_changed reads the list again (and one for another thread does not)', async () => {
    const w = await openWith([line()], { pins: [], can_pin: true, max: 10 })
    h.chat.listPins = vi.fn().mockResolvedValue({ pins: [pinRow(1, 'first draft')], can_pin: true, max: 10 })
    h.stream.onPinsChanged({ conversation_id: 'room-b', kind: 'dm', message: { id: 'm1', pinned: true, count: 1 } })
    await settle(3)
    expect(h.chat.listPins).not.toHaveBeenCalled()
    h.stream.onPinsChanged({ conversation_id: 'room-a', kind: 'dm', message: { id: 'm1', pinned: true, count: 1 } })
    await settle(4)
    expect(h.chat.listPins).toHaveBeenCalledTimes(1)
    expect(tid(w, 'ost-pins').exists()).toBe(true)
  })
})
