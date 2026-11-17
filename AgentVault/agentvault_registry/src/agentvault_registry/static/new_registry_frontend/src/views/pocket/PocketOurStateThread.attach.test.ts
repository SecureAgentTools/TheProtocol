import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): files pasted or dropped into the composer are STAGED (a chip,
 * a cross) and go out with Send: each one uploaded and posted as its card, then the text. Only a plain room or direct
 * thread takes files. A paste of words stays a paste, a refused file says why, a file already in the room never goes
 * twice, and a staged file never follows you into another room. The harness is PocketOurStateThread.sentWithKey.test.ts's.
 * BASE (6fdebed71): the composer takes no file.
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

const bigFile = (name: string, type: string, size: number) => {
  const f = new File(['x'], name, { type })
  Object.defineProperty(f, 'size', { value: size })       // the size a test names, without a buffer of that size
  return f
}
const png = (name = 'shot.png') => new File(['x'], name, { type: 'image/png' })

async function open(kind = 'dm') {
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [], last_seq: 0, page_bound: 40, kind, my_state: 'active',
    my_last_read_seq: 0, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  let n = 0
  h.chat.uploadAttachment = vi.fn().mockImplementation(async (_t: string, _c: string, file: File) =>
    ({ attachment_id: `att_${++n}`, id: `att_${n}`, card: { type: 'media', name: file.name } }))
  let seq = 0
  h.chat.postMessage = vi.fn().mockImplementation(async (_t: string, conv: string, p: any) => ({ message: {
    id: `m${++seq}`, seq, kind: p.kind, body: p.body, card: p.card, sender_ptype: 'developer', sender_id: 6, conversation_id: conv } }))
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
const box = (w: any) => w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement
const chips = (w: any) => w.findAll('.ost-chip')
const bodies = () => h.chat.postMessage.mock.calls.map((c: any[]) => c[2])

/** a paste or a drop is an event carrying a clipboard or a data transfer: built by hand so the test says what it holds */
function paste(w: any, files: File[]) {
  const ev = new Event('paste', { bubbles: true, cancelable: true })
  Object.defineProperty(ev, 'clipboardData', { value: { files, items: [] } })
  w.find('[data-testid="ost-input"]').element.dispatchEvent(ev)
  return ev
}
function drag(w: any, type: 'dragover' | 'dragleave' | 'drop', files: File[], types: string[] = ['Files']) {
  const ev = new Event(type, { bubbles: true, cancelable: true })
  Object.defineProperty(ev, 'dataTransfer', { value: { files, types, items: [] } })
  w.find('.ost-input-wrap').element.dispatchEvent(ev)
  return ev
}
async function settle(n = 4) { for (let i = 0; i < n; i++) await flushPromises() }
async function type(w: any, text: string) { await w.find('[data-testid="ost-input"]').setValue(text); await settle(2) }
async function send(w: any) { await w.find('[data-testid="ost-send"]').trigger('click'); await settle(6) }

beforeEach(() => {
  setActivePinia(createPinia())
  h.chat = {}
  h.route.params.id = 'room-a'
  h.auth.activeAgent = null
  localStorage.clear()
})
afterEach(() => { document.body.innerHTML = '' })

describe('a paste', () => {
  it('stages a pasted file as a chip and posts nothing', async () => {
    const w = await open()
    const ev = paste(w, [png('shot.png')])
    await settle()
    expect(ev.defaultPrevented).toBe(true)
    expect(chips(w)).toHaveLength(1)
    expect(chips(w)[0].attributes('data-kind')).toBe('image')
    expect(chips(w)[0].text()).toContain('shot.png')
    expect(h.chat.uploadAttachment).not.toHaveBeenCalled()
    expect(h.chat.postMessage).not.toHaveBeenCalled()
    expect(box(w).value).toBe('')
  })

  it('leaves a paste of words alone', async () => {
    const w = await open()
    const ev = new Event('paste', { bubbles: true, cancelable: true })
    Object.defineProperty(ev, 'clipboardData', { value: { files: [], items: [{ kind: 'string' }] } })
    w.find('[data-testid="ost-input"]').element.dispatchEvent(ev)
    await settle()
    expect(ev.defaultPrevented).toBe(false)
    expect(chips(w)).toHaveLength(0)
  })

  it('shows the size beside the name and lets the cross take the file back', async () => {
    const w = await open()
    paste(w, [bigFile('report.pdf', 'application/pdf', 1536)])
    await settle()
    expect(chips(w)[0].text()).toContain('1.5 KB')
    await chips(w)[0].find('button').trigger('click')
    await settle()
    expect(chips(w)).toHaveLength(0)
  })
})

describe('a drop', () => {
  it('stages the files, and shows the zone while they are over it', async () => {
    const w = await open()
    const over = drag(w, 'dragover', [])
    await settle(2)
    expect(over.defaultPrevented).toBe(true)
    expect(w.find('.ost-input-wrap').classes()).toContain('dropping')
    drag(w, 'dragleave', [])
    await settle(2)
    expect(w.find('.ost-input-wrap').classes()).not.toContain('dropping')
    const dropped = drag(w, 'drop', [png('a.png'), png('b.png')])
    await settle()
    expect(dropped.defaultPrevented).toBe(true)
    expect(chips(w)).toHaveLength(2)
  })

  it('ignores a drag that is not carrying files', async () => {
    const w = await open()
    const ev = drag(w, 'dragover', [], ['text/plain'])
    await settle(2)
    expect(ev.defaultPrevented).toBe(false)
    expect(w.find('.ost-input-wrap').classes()).not.toContain('dropping')
  })
})

describe('what may be staged', () => {
  it('refuses SVG with a reason that names the file and what is taken', async () => {
    const w = await open()
    paste(w, [new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' })])
    await settle()
    expect(chips(w)).toHaveLength(0)
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('logo.svg: images, PDF, text, Markdown, JSON and CSV only.')
  })

  it('refuses a file over five MB and an empty one, and still stages the good one beside them', async () => {
    const w = await open()
    paste(w, [bigFile('big.png', 'image/png', 6 * 1024 * 1024), bigFile('none.txt', 'text/plain', 0), png('ok.png')])
    await settle()
    expect(chips(w)).toHaveLength(1)
    expect(chips(w)[0].text()).toContain('ok.png')
    const hint = w.find('[data-testid="ost-hint"]').text()
    expect(hint).toContain('big.png is over 5.0 MB.')
    expect(hint).toContain('none.txt is empty.')
  })

  it('stops at five files', async () => {
    const w = await open()
    paste(w, [1, 2, 3, 4, 5, 6, 7].map((i) => png(`f${i}.png`)))
    await settle()
    expect(chips(w)).toHaveLength(5)
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('5 files at most, in one message.')
  })

  it('gives a markdown file the type the registry takes, though the browser gave none', async () => {
    const w = await open()
    paste(w, [new File(['# plan'], 'plan.md', { type: '' })])
    await settle()
    await send(w)
    expect(h.chat.uploadAttachment).toHaveBeenCalledTimes(1)
    expect(h.chat.uploadAttachment.mock.calls[0][2].type).toBe('text/markdown')
  })
})

describe('Send with files', () => {
  it('uploads each file and posts its card, in order, then the text', async () => {
    const w = await open()
    paste(w, [png('a.png'), png('b.png')])
    await type(w, 'two screenshots')
    await send(w)
    expect(h.chat.uploadAttachment.mock.calls.map((c: any[]) => c[2].name)).toEqual(['a.png', 'b.png'])
    expect(bodies().map((b: any) => b.kind)).toEqual(['card', 'card', 'text'])
    expect(bodies()[0].card).toEqual({ type: 'media', name: 'a.png' })
    expect(bodies()[1].card).toEqual({ type: 'media', name: 'b.png' })
    expect(bodies()[2].body).toBe('two screenshots')
    expect(chips(w)).toHaveLength(0)
    expect(box(w).value).toBe('')
  })

  it('sends files alone: Send is on with no text, and no text is posted', async () => {
    const w = await open()
    expect(w.find('[data-testid="ost-send"]').attributes('disabled')).toBeDefined()
    paste(w, [png('a.png')])
    await settle()
    expect(w.find('[data-testid="ost-send"]').attributes('disabled')).toBeUndefined()
    await send(w)
    expect(bodies().map((b: any) => b.kind)).toEqual(['card'])
    expect(chips(w)).toHaveLength(0)
  })

  it('keeps the unsent files, and the text, when one fails, and never sends a posted file twice', async () => {
    const w = await open()
    paste(w, [png('a.png'), png('b.png')])
    await type(w, 'the caption')
    let call = 0
    h.chat.uploadAttachment = vi.fn().mockImplementation(async (_t: string, _c: string, file: File) => {
      if (file.name === 'b.png' && ++call === 1) throw Object.assign(new Error('files are limited'), { status: 413, detail: 'files are limited' })
      return { attachment_id: 'att_' + file.name, card: { type: 'media', name: file.name } }
    })
    await send(w)
    expect(bodies().map((b: any) => b.kind)).toEqual(['card'])        // a.png is in the room, the text is not
    expect(chips(w)).toHaveLength(1)
    expect(chips(w)[0].text()).toContain('b.png')
    expect(box(w).value).toBe('the caption')
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('files are limited')
    await send(w)                                                      // the retry
    expect(h.chat.uploadAttachment.mock.calls.map((c: any[]) => c[2].name)).toEqual(['a.png', 'b.png', 'b.png'])
    expect(bodies().map((b: any) => b.kind)).toEqual(['card', 'card', 'text'])
    expect(chips(w)).toHaveLength(0)
  })

  it('says so when offline, and keeps every file and the text', async () => {
    const w = await open()
    paste(w, [png('a.png')])
    await type(w, 'caption')
    h.chat.uploadAttachment = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'))
    await send(w)
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('Offline')
    expect(chips(w)).toHaveLength(1)
    expect(box(w).value).toBe('caption')
    expect(h.chat.postMessage).not.toHaveBeenCalled()
  })

  it('sends a command as a command and leaves the files staged', async () => {
    const w = await open()
    paste(w, [png('a.png')])
    await type(w, '/me waves')
    await send(w)
    expect(h.chat.uploadAttachment).not.toHaveBeenCalled()
    expect(bodies().map((b: any) => b.body)).toEqual(['/me waves'])
    expect(chips(w)).toHaveLength(1)
  })

  it('posts a text past the cap as a document after the files', async () => {
    const w = await open()
    paste(w, [png('a.png')])
    await type(w, 'x'.repeat(5000))
    await send(w)
    expect(h.chat.uploadAttachment.mock.calls.map((c: any[]) => c[2].name)).toEqual(['a.png', expect.stringMatching(/^message-\d{8}-\d{6}\.md$/)])
    expect(bodies().map((b: any) => b.kind)).toEqual(['card', 'card', 'text'])
  })
})

describe('where a staged file belongs', () => {
  it('does not follow you into another room', async () => {
    const w = await open()
    paste(w, [png('a.png')])
    await settle()
    expect(chips(w)).toHaveLength(1)
    h.route.params.id = 'room-b'
    await settle(6)
    expect(chips(w)).toHaveLength(0)
  })

  it('is not taken in an agent thread, where a paste stays a paste', async () => {
    const w = await open('agent_service')
    const ev = paste(w, [png('a.png')])
    await settle()
    expect(ev.defaultPrevented).toBe(false)
    expect(chips(w)).toHaveLength(0)
  })

  it('is not taken in a support thread either', async () => {
    const w = await open('support')
    const ev = paste(w, [png('a.png')])
    await settle()
    expect(ev.defaultPrevented).toBe(false)
    expect(chips(w)).toHaveLength(0)
  })
})

describe('the paperclip', () => {
  const pick = async (w: any, files: File[]) => {
    const input = w.find('[data-testid="ost-file"]').element as HTMLInputElement
    Object.defineProperty(input, 'files', { configurable: true, value: files })
    const resets: string[] = []
    Object.defineProperty(input, 'value', { configurable: true, get: () => '', set: (v: string) => { resets.push(v) } })
    await w.find('[data-testid="ost-file"]').trigger('change')
    await settle()
    return resets
  }

  it('is in a plain room, named for a screen reader, with the chooser it opens beside it', async () => {
    const w = await open()
    const btn = w.find('[data-testid="ost-attach"]')
    expect(btn.exists()).toBe(true)
    expect(btn.attributes('aria-label')).toBe('Attach a file')
    expect(btn.attributes('type')).toBe('button')
    expect(w.find('[data-testid="ost-file"]').attributes('multiple')).toBeDefined()
    expect(w.find('[data-testid="ost-file"]').attributes('accept')).toContain('.pdf')
    expect(w.find('[data-testid="ost-file"]').attributes('accept')).not.toMatch(/svg/i)
  })

  it('opens the file chooser when pressed', async () => {
    const w = await open()
    const input = w.find('[data-testid="ost-file"]').element as HTMLInputElement
    const click = vi.spyOn(input, 'click').mockImplementation(() => {})
    await w.find('[data-testid="ost-attach"]').trigger('click')
    expect(click).toHaveBeenCalledTimes(1)
  })

  it('stages what is chosen, exactly as a paste does, and clears the chooser so the same file can be chosen again', async () => {
    const w = await open()
    const resets = await pick(w, [png('a.png'), bigFile('big.pdf', 'application/pdf', 1536)])
    expect(chips(w)).toHaveLength(2)
    expect(chips(w).map((c: any) => c.attributes('data-kind'))).toEqual(['image', 'pdf'])
    expect(resets).toEqual([''])
    expect(h.chat.uploadAttachment).not.toHaveBeenCalled()
  })

  it('refuses what the rules refuse, with the same reason', async () => {
    const w = await open()
    await pick(w, [new File(['<svg/>'], 'logo.svg', { type: 'image/svg+xml' })])
    expect(chips(w)).toHaveLength(0)
    expect(w.find('[data-testid="ost-hint"]').text()).toContain('logo.svg: images, PDF, text, Markdown, JSON and CSV only.')
  })

  it('does nothing when the chooser is closed with no file', async () => {
    const w = await open()
    const resets = await pick(w, [])
    expect(chips(w)).toHaveLength(0)
    expect(resets).toEqual([''])
  })

  it('is not in an agent thread or a support thread, which take no files', async () => {
    expect((await open('agent_service')).find('[data-testid="ost-attach"]').exists()).toBe(false)
    expect((await open('support')).find('[data-testid="ost-attach"]').exists()).toBe(false)
  })
})
