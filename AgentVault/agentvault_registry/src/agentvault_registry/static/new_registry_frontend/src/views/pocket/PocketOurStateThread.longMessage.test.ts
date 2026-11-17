import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): the composer counts BYTES against the registry's 4096-byte
 * cap (chat_service.BODY_MAX_BYTES) and, past it, Send posts the text as a markdown document: upload, the file's card,
 * then one line that summarises it (the three steps chat_link takes above 1,500 characters). A service call, a support
 * reply and an assistant ask keep their own limits and do not get the document. The harness is
 * PocketOurStateThread.sentWithKey.test.ts's.
 * BASE (f569f6a6e): no counter and no document; a text past the cap goes to the registry and comes back refused.
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
import { BODY_MAX_BYTES } from '@/services/chat/longMessage'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true },
  },
}
const thread = (kind: string) => ({ messages: [], last_seq: 0, page_bound: 40, kind, my_state: 'active', my_last_read_seq: 0,
  counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
const posted = (conv: string, p: any, seq: number) => ({ message: { id: `m${seq}`, seq, kind: p.kind, body: p.body, card: p.card,
  sender_ptype: 'developer', sender_id: 6, conversation_id: conv, created_at: '2026-11-13T15:00:00Z' } })

/** A long text that starts with words (a leading "/" would be a command) and is `n` bytes of ASCII. */
const longText = (n: number) => ('The plan, in short. ' + 'x'.repeat(n)).slice(0, n)

async function open(kind = 'dm') {
  h.chat.getMessages = vi.fn().mockResolvedValue(thread(kind))
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.uploadAttachment = vi.fn().mockResolvedValue({ attachment_id: 'att_1', id: 'att_1', card: { type: 'media', id: 'att_1' } })
  h.chat.postMessage = vi.fn().mockImplementation(async (_t: string, conv: string, p: any) => posted(conv, p, 1))
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function type(w: any, text: string) {
  await w.find('[data-testid="ost-input"]').setValue(text)
  await flushPromises()
}
async function sendIt(w: any) {
  await w.find('[data-testid="ost-send"]').trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}

describe('the byte counter', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.activeAgent = null
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('stays out of the way until 3,500 bytes, then counts', async () => {
    const w = await open()
    await type(w, longText(3499))
    expect(w.find('[data-testid="ost-count"]').exists()).toBe(false)
    await type(w, longText(3500))
    const c = w.find('[data-testid="ost-count"]')
    expect(c.exists()).toBe(true)
    expect(c.text()).toBe('3500 of 4096 bytes')
    expect(c.attributes('data-over')).toBe('0')
    expect(w.find('[data-testid="ost-send"]').attributes('data-mode')).toBe('text')
  })

  it('counts BYTES: 1,800 letters "ä" are 3,600 bytes and show the counter', async () => {
    const w = await open()
    await type(w, 'ä'.repeat(1800))
    expect(w.find('[data-testid="ost-count"]').text()).toBe('3600 of 4096 bytes')
  })

  it('says what Send will do once the text is past the cap', async () => {
    const w = await open()
    await type(w, longText(BODY_MAX_BYTES + 1))
    const c = w.find('[data-testid="ost-count"]')
    expect(c.attributes('data-over')).toBe('1')
    expect(c.text()).toBe('4097 of 4096 bytes: Send posts this as a document')
    const send = w.find('[data-testid="ost-send"]')
    expect(send.attributes('data-mode')).toBe('document')
    expect(send.attributes('aria-label')).toBe('Send as document')
  })

  it('is not shown in an agent thread, where the limits are other ones', async () => {
    const w = await open('agent_service')
    await type(w, longText(BODY_MAX_BYTES + 500))
    expect(w.find('[data-testid="ost-count"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-send"]').attributes('data-mode')).toBe('text')
  })

  it('is not shown in a support thread either', async () => {
    const w = await open('support')
    await type(w, longText(BODY_MAX_BYTES + 500))
    expect(w.find('[data-testid="ost-count"]').exists()).toBe(false)
  })
})

describe('Send as document', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.activeAgent = null
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('uploads the text as a markdown file, posts its card, then one summarising line, in that order', async () => {
    const w = await open()
    const text = '  # The plan\n\n' + longText(BODY_MAX_BYTES + 200) + '  '
    await type(w, text)
    await sendIt(w)

    expect(h.chat.uploadAttachment).toHaveBeenCalledTimes(1)
    const [tok, conv, file] = h.chat.uploadAttachment.mock.calls[0]
    expect(tok).toBe('dev.tok')
    expect(conv).toBe('room-a')
    expect(file.name).toMatch(/^message-\d{8}-\d{6}\.md$/)
    expect(file.type).toBe('text/markdown')
    expect(await file.text()).toBe(text.trim())

    const sent = h.chat.postMessage.mock.calls.map((c: any[]) => c[2])
    expect(sent).toHaveLength(2)
    expect(sent[0].kind).toBe('card')
    expect(sent[0].card).toEqual({ type: 'media', id: 'att_1' })
    expect(sent[1].kind).toBe('text')
    expect(sent[1].body.startsWith('# The plan (the whole message: message-')).toBe(true)
    expect(sent[1].body).toMatch(/\(the whole message: message-\d{8}-\d{6}\.md, \d+ bytes\)$/)
    expect(sent[1].body).not.toContain('att_1')      // the card above it carries the id
    // the long text itself is never posted as a message body
    expect(sent.some((p: any) => typeof p.body === 'string' && p.body.length > 1000)).toBe(false)
    // the card goes before the line (the upload's order of events), each under its own idempotency key
    expect(h.chat.postMessage.mock.invocationCallOrder[0]).toBeLessThan(h.chat.postMessage.mock.invocationCallOrder[1])
    expect(sent[0].client_ref).not.toBe(sent[1].client_ref)

    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toBe('')
  })

  it('leaves a text under the cap alone: one plain message, no upload', async () => {
    const w = await open()
    await type(w, longText(BODY_MAX_BYTES))
    await sendIt(w)
    expect(h.chat.uploadAttachment).not.toHaveBeenCalled()
    expect(h.chat.postMessage).toHaveBeenCalledTimes(1)
    expect(h.chat.postMessage.mock.calls[0][2].kind).toBe('text')
    expect(h.chat.postMessage.mock.calls[0][2].body).toHaveLength(BODY_MAX_BYTES)
  })

  it('keeps the text and says why when the registry refuses the file', async () => {
    const w = await open()
    await type(w, longText(BODY_MAX_BYTES + 100))
    h.chat.uploadAttachment = vi.fn().mockRejectedValue(Object.assign(new Error('files are limited to 5 MB'),
      { status: 413, detail: 'files are limited to 5 MB' }))
    await sendIt(w)
    expect(h.chat.postMessage).not.toHaveBeenCalled()
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('files are limited to 5 MB')
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toHaveLength(BODY_MAX_BYTES + 100)
  })

  it('keeps the text and says so when offline: a file cannot wait in the queue', async () => {
    const w = await open()
    await type(w, longText(BODY_MAX_BYTES + 100))
    h.chat.uploadAttachment = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))   // no status: the network
    await sendIt(w)
    expect(h.chat.postMessage).not.toHaveBeenCalled()
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('Offline')
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toHaveLength(BODY_MAX_BYTES + 100)
  })

  it('clears the composer when the card went out and the line did not, so a retry cannot upload the file twice', async () => {
    const w = await open()
    await type(w, longText(BODY_MAX_BYTES + 100))
    let n = 0
    h.chat.postMessage = vi.fn().mockImplementation(async (_t: string, conv: string, p: any) => {
      if (++n === 2) throw Object.assign(new Error('slow down'), { status: 429, detail: 'slow down' })
      return posted(conv, p, n)
    })
    await sendIt(w)
    expect(h.chat.uploadAttachment).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('The file is in the room; its line did not post: slow down')
    expect((w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement).value).toBe('')
  })
})
