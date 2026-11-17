import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): edit and take back your own text line. Edit and Delete are
 * offered on your own text line inside the window and nowhere else; Save sends the new text and the line shows it with an
 * "edited" mark that reads the earlier texts; Delete asks first and leaves the tombstone; the registry's refusal is shown as
 * its sentence; a change the thread hears (the socket's edited and deleted events) is folded in. BASE (1412e2858): no
 * control, no API call, no handler. The harness is PocketOurStateThread.attach.test.ts's.
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

describe('where Edit and Delete are offered', () => {
  it('on your own fresh text line', async () => {
    const w = await open([line()])
    expect(tid(w, 'ost-edit-1').exists()).toBe(true)
    expect(tid(w, 'ost-delete-1').exists()).toBe(true)
  })
  it('not on someone else\'s line (control: the same line, another sender)', async () => {
    const w = await open([line({ sender_id: 2 })])
    expect(tid(w, 'ost-edit-1').exists()).toBe(false)
    expect(tid(w, 'ost-delete-1').exists()).toBe(false)
  })
  it('not once the window has closed (20 minutes old)', async () => {
    const w = await open([line({ created_at: ago(20 * 60_000) })])
    expect(tid(w, 'ost-edit-1').exists()).toBe(false)
  })
  it('not on a card, and not on a line taken back', async () => {
    const w = await open([line({ kind: 'card', body: null, card: { type: 'media' } }), line({ id: 'm2', seq: 2, deleted: true, kind: 'system', body: null })])
    expect(tid(w, 'ost-edit-1').exists()).toBe(false)
    expect(tid(w, 'ost-edit-2').exists()).toBe(false)
  })
})

describe('editing a line', () => {
  it('opens a field with the text, and Save sends the new text and shows it, marked edited', async () => {
    h.chat.editMessage = vi.fn().mockResolvedValue({ changed: true, message: line({ body: 'second draft', edited_at: new Date().toISOString() }) })
    const w = await open([line()])
    await tid(w, 'ost-edit-1').trigger('click')
    const field = tid(w, 'ost-edit-field-1')
    expect((field.element as HTMLTextAreaElement).value).toBe('first draft')
    await field.setValue('second draft')
    await tid(w, 'ost-edit-save-1').trigger('click')
    await settle()
    expect(h.chat.editMessage).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1', 'second draft')
    expect(tid(w, 'ost-editbox-1').exists()).toBe(false)
    expect(w.text()).toContain('second draft')
    expect(tid(w, 'ost-edited-1').exists()).toBe(true)
  })
  it('Cancel (and Escape) closes it and sends nothing', async () => {
    h.chat.editMessage = vi.fn()
    const w = await open([line()])
    await tid(w, 'ost-edit-1').trigger('click')
    await tid(w, 'ost-edit-cancel-1').trigger('click')
    expect(tid(w, 'ost-editbox-1').exists()).toBe(false)
    await tid(w, 'ost-edit-1').trigger('click')
    await tid(w, 'ost-edit-field-1').trigger('keydown', { key: 'Escape' })
    expect(tid(w, 'ost-editbox-1').exists()).toBe(false)
    expect(h.chat.editMessage).not.toHaveBeenCalled()
  })
  it('Save is off for an empty text and for one over the registry\'s byte limit', async () => {
    const w = await open([line()])
    await tid(w, 'ost-edit-1').trigger('click')
    await tid(w, 'ost-edit-field-1').setValue('   ')
    expect((tid(w, 'ost-edit-save-1').element as HTMLButtonElement).disabled).toBe(true)
    await tid(w, 'ost-edit-field-1').setValue('é'.repeat(2049))          // 4098 bytes, 2049 characters
    expect((tid(w, 'ost-edit-save-1').element as HTMLButtonElement).disabled).toBe(true)
    await tid(w, 'ost-edit-field-1').setValue('é'.repeat(2048))          // exactly 4096 bytes
    expect((tid(w, 'ost-edit-save-1').element as HTMLButtonElement).disabled).toBe(false)
  })
  it('shows the registry\'s refusal as its sentence and keeps the field open with the text', async () => {
    h.chat.editMessage = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'a message takes changes for 15 minutes after it is posted' }))
    const w = await open([line()])
    await tid(w, 'ost-edit-1').trigger('click')
    await tid(w, 'ost-edit-field-1').setValue('too late')
    await tid(w, 'ost-edit-save-1').trigger('click')
    await settle()
    expect(tid(w, 'ost-edit-err-1').text()).toContain('15 minutes after it is posted')
    expect((tid(w, 'ost-edit-field-1').element as HTMLTextAreaElement).value).toBe('too late')
  })
})

describe('taking a line back', () => {
  it('asks first; Keep it leaves the line and calls nothing', async () => {
    h.chat.deleteMessage = vi.fn()
    const w = await open([line()])
    await tid(w, 'ost-delete-1').trigger('click')
    expect(tid(w, 'ost-delask-1').exists()).toBe(true)
    await tid(w, 'ost-delete-keep-1').trigger('click')
    expect(tid(w, 'ost-delask-1').exists()).toBe(false)
    expect(h.chat.deleteMessage).not.toHaveBeenCalled()
    expect(w.text()).toContain('first draft')
  })
  it('Take it back calls the registry and leaves the tombstone', async () => {
    h.chat.deleteMessage = vi.fn().mockResolvedValue({ message: { id: 'm1', deleted: true } })
    const w = await open([line()])
    await tid(w, 'ost-delete-1').trigger('click')
    await tid(w, 'ost-delete-yes-1').trigger('click')
    await settle()
    expect(h.chat.deleteMessage).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1')
    expect(w.find('.ost-tombstone').exists()).toBe(true)
    expect(w.text()).not.toContain('first draft')
    expect(tid(w, 'ost-edit-1').exists()).toBe(false)
  })
  it('a refusal is shown and the line stays', async () => {
    h.chat.deleteMessage = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'this message was taken back' }))
    const w = await open([line()])
    await tid(w, 'ost-delete-1').trigger('click')
    await tid(w, 'ost-delete-yes-1').trigger('click')
    await settle()
    expect(tid(w, 'ost-delask-1').text()).toContain('this message was taken back')
    expect(w.text()).toContain('first draft')
  })
})

describe('a change the thread hears', () => {
  it('an edit from another device replaces the text and marks the line', async () => {
    const w = await open([line()])
    h.stream.onMessageEdited({ conversation_id: 'room-a', kind: 'dm', message: line({ body: 'from my phone', edited_at: new Date().toISOString() }) })
    await settle()
    expect(w.text()).toContain('from my phone')
    expect(tid(w, 'ost-edited-1').exists()).toBe(true)
  })
  it('a take-back leaves the tombstone', async () => {
    const w = await open([line({ sender_id: 2 })])
    h.stream.onMessageDeleted({ conversation_id: 'room-a', kind: 'dm', message: { id: 'm1', deleted: true } })
    await settle()
    expect(w.find('.ost-tombstone').exists()).toBe(true)
    expect(w.text()).not.toContain('first draft')
  })
  it('a change in another thread is ignored (control)', async () => {
    const w = await open([line()])
    h.stream.onMessageEdited({ conversation_id: 'room-b', kind: 'dm', message: line({ body: 'elsewhere', edited_at: new Date().toISOString() }) })
    h.stream.onMessageDeleted({ conversation_id: 'room-b', kind: 'dm', message: { id: 'm1', deleted: true } })
    await settle()
    expect(w.text()).toContain('first draft')
    expect(w.find('.ost-tombstone').exists()).toBe(false)
  })
})

describe('a thread that was away', () => {
  it('a catch-up read shows an edit and a take-back made meanwhile (the socket missed them)', async () => {
    const first = [line(), line({ id: 'm2', seq: 2, sender_id: 2, body: 'theirs' })]
    const w = await open(first)
    h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [line({ body: 'fixed meanwhile', edited_at: new Date().toISOString() }),
      line({ id: 'm2', seq: 2, sender_id: 2, kind: 'system', body: null, deleted: true })], last_seq: 2, page_bound: 40, kind: 'dm',
      my_state: 'active', my_last_read_seq: 2, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await settle(8)
    expect(w.text()).toContain('fixed meanwhile')
    expect(w.text()).not.toContain('theirs')
  })
})

describe('a thread whose socket is down polls the sync feed', () => {
  it('applies the edit and the take-back its updates lane carries, for this thread only', async () => {
    vi.useFakeTimers({ toFake: ['setTimeout'] })
    try {
      h.startConnected = false
      h.chat.sync = vi.fn().mockResolvedValue({ messages: [], next_cursor: 'c2', updates: [
        { id: 'm1', conversation_id: 'room-a', seq: 1, change: 'edit', body: 'edited while away', edited_at: new Date().toISOString() },
        { id: 'm2', conversation_id: 'room-a', seq: 2, change: 'delete', body: null, deleted_at: new Date().toISOString() },
        { id: 'm3', conversation_id: 'room-b', seq: 1, change: 'delete', body: null, deleted_at: new Date().toISOString() }] })
      const w = await open([line(), line({ id: 'm2', seq: 2, sender_id: 2, body: 'theirs' }), line({ id: 'm3', seq: 3, sender_id: 2, body: 'other thread line' })])
      await vi.advanceTimersByTimeAsync(3200)
      await settle(6)
      expect(h.chat.sync).toHaveBeenCalled()
      expect(w.text()).toContain('edited while away')
      expect(w.text()).not.toContain('theirs')
      expect(w.text()).toContain('other thread line')                    // a change in another thread is not this one's
    } finally { vi.useRealTimers() }
  })
})

describe('the edited mark and the earlier texts', () => {
  it('shows only on an edited line; pressing it reads the earlier text, pressing again closes it', async () => {
    h.chat.messageHistory = vi.fn().mockResolvedValue({ changes: [
      { rev: 1, kind: 'edit', at: ago(30_000), by: { name: 'me' }, body_before: 'the very first words' }] })
    const w = await open([line({ body: 'now', edited_at: ago(30_000) }), line({ id: 'm2', seq: 2, body: 'plain' })])
    expect(tid(w, 'ost-edited-2').exists()).toBe(false)
    await tid(w, 'ost-edited-1').trigger('click')
    await settle()
    expect(h.chat.messageHistory).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1')
    expect(tid(w, 'ost-history-1').text()).toContain('the very first words')
    await tid(w, 'ost-edited-1').trigger('click')
    expect(tid(w, 'ost-history-1').exists()).toBe(false)
  })
  it('says so when the earlier text could not be read', async () => {
    h.chat.messageHistory = vi.fn().mockRejectedValue(new Error('down'))
    const w = await open([line({ edited_at: ago(30_000) })])
    await tid(w, 'ost-edited-1').trigger('click')
    await settle()
    expect(tid(w, 'ost-history-1').text()).toContain('could not be read')
  })
})

describe('reactions', () => {
  const chips = (w: any, seq = 1) => w.findAll(`[data-testid^="ost-react-${seq}-"]`)

  it('draws the words a line carries with their counts, yours pressed, and nothing under a line without any', async () => {
    const w = await open([line({ reactions: [{ key: 'ack', count: 2, mine: true }, { key: 'look', count: 1, mine: false }] }), line({ id: 'm2', seq: 2 })])
    const c = chips(w)
    expect(c.map((x: any) => x.text())).toEqual(['Got it 2', 'Looking 1'])
    expect(c[0].attributes('aria-pressed')).toBe('true')
    expect(c[1].attributes('aria-pressed')).toBe('false')
    expect(tid(w, 'ost-reacts-2').exists()).toBe(false)                   // control: no empty row under every line
  })
  it('opens the closed list from React and puts a word on: the registry\'s answer replaces the chips', async () => {
    h.chat.addReaction = vi.fn().mockResolvedValue({ added: true, reactions: [{ key: 'thanks', count: 1, mine: true }] })
    const w = await open([line({ sender_id: 2 })])
    await tid(w, 'ost-react-add-1').trigger('click')
    const picks = w.findAll('[data-testid^="ost-react-pick-1-"]')
    expect(picks.map((x: any) => x.text())).toEqual(['Got it', 'Agree', 'Thanks', 'Done', 'Question', 'Looking'])
    await tid(w, 'ost-react-pick-1-thanks').trigger('click')
    await settle()
    expect(h.chat.addReaction).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1', 'thanks')
    expect(chips(w).map((x: any) => x.text())).toEqual(['Thanks 1'])
    expect(chips(w)[0].attributes('aria-pressed')).toBe('true')
    expect(w.findAll('[data-testid^="ost-react-pick-1-"]')).toHaveLength(0)    // the list closed
  })
  it('pressing a chip of yours takes it off', async () => {
    h.chat.removeReaction = vi.fn().mockResolvedValue({ removed: true, reactions: [] })
    const w = await open([line({ reactions: [{ key: 'ack', count: 1, mine: true }] })])
    await tid(w, 'ost-react-1-ack').trigger('click')
    await settle()
    expect(h.chat.removeReaction).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1', 'ack')
    expect(h.chat.addReaction).toBeUndefined()
    expect(chips(w)).toHaveLength(0)
  })
  it('pressing a chip that is not yours adds yours', async () => {
    h.chat.addReaction = vi.fn().mockResolvedValue({ added: true, reactions: [{ key: 'look', count: 2, mine: true }] })
    const w = await open([line({ sender_id: 2, reactions: [{ key: 'look', count: 1, mine: false }] })])
    await tid(w, 'ost-react-1-look').trigger('click')
    await settle()
    expect(h.chat.addReaction).toHaveBeenCalledWith(h.auth.token, 'room-a', 'm1', 'look')
    expect(chips(w)[0].text()).toBe('Looking 2')
  })
  it('shows the registry\'s refusal and leaves the chips as they were', async () => {
    h.chat.addReaction = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'this message was taken back' }))
    const w = await open([line({ sender_id: 2, reactions: [{ key: 'look', count: 1, mine: false }] })])
    await tid(w, 'ost-react-1-look').trigger('click')
    await settle()
    expect(tid(w, 'ost-reacts-1').text()).toContain('this message was taken back')
    expect(chips(w)[0].text()).toBe('Looking 1')
  })
  it('a count the thread hears from another device changes the chips, mine kept (and mine set for my own change)', async () => {
    const w = await open([line({ reactions: [{ key: 'ack', count: 1, mine: true }] })])
    h.stream.onReaction({ conversation_id: 'room-a', kind: 'dm', message: { id: 'm1', word: 'look', reactions: [{ key: 'ack', count: 1 }, { key: 'look', count: 1 }], by: { ptype: 'developer', id: 2 } } })
    await settle()
    expect(chips(w).map((x: any) => [x.text(), x.attributes('aria-pressed')])).toEqual([['Got it 1', 'true'], ['Looking 1', 'false']])
    h.stream.onReaction({ conversation_id: 'room-a', kind: 'dm', message: { id: 'm1', word: 'done', reactions: [{ key: 'ack', count: 1 }, { key: 'done', count: 1 }, { key: 'look', count: 1 }], by: { ptype: 'developer', id: 6 } } })
    await settle()
    expect(chips(w).map((x: any) => [x.text(), x.attributes('aria-pressed')])).toEqual([['Got it 1', 'true'], ['Done 1', 'true'], ['Looking 1', 'false']])
  })
  it('an event for another thread is ignored (control)', async () => {
    const w = await open([line()])
    h.stream.onReaction({ conversation_id: 'room-b', kind: 'dm', message: { id: 'm1', word: 'ack', reactions: [{ key: 'ack', count: 1 }], by: { ptype: 'developer', id: 2 } } })
    await settle()
    expect(chips(w)).toHaveLength(0)
  })
  it('no React button on a line taken back, and a catch-up read refreshes the words', async () => {
    const w = await open([line({ deleted: true, kind: 'system', body: null }), line({ id: 'm2', seq: 2, sender_id: 2 })])
    expect(tid(w, 'ost-react-add-1').exists()).toBe(false)
    expect(tid(w, 'ost-react-add-2').exists()).toBe(true)
    h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [line({ deleted: true, kind: 'system', body: null }),
      line({ id: 'm2', seq: 2, sender_id: 2, reactions: [{ key: 'agree', count: 3, mine: false }] })], last_seq: 2, page_bound: 40, kind: 'dm',
      my_state: 'active', my_last_read_seq: 2, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
    window.dispatchEvent(new Event('focus'))
    document.dispatchEvent(new Event('visibilitychange'))
    await settle(8)
    expect(chips(w, 2).map((x: any) => x.text())).toEqual(['Agree 3'])
  })
})
