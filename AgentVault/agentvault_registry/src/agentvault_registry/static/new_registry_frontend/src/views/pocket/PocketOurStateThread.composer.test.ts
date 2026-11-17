import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, order gwo_173e400022a85073f908044b): the composer grows with the text to about 40% of the pane,
 * can be dragged taller by its handle (the height is remembered per device), can be taken full-height, has a formatting
 * toolbar (Ctrl+B, I, K too) and a Write/Preview switch that renders with the thread's own renderer. The harness is
 * PocketOurStateThread.sentWithKey.test.ts's.
 * BASE (3b0960a30): a one-line textarea with a fixed 120 px ceiling, no handle, no toolbar, no preview.
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
/* the test DOM lays nothing out: the pane reports the height a test gives it, and the textarea the text height a test
   gives it (scrollHeight), as a browser's layout would */
let paneH = 800
const clientHeightDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight')
function textHeight(el: Element, px: number) { Object.defineProperty(el, 'scrollHeight', { configurable: true, get: () => px }) }

async function open() {
  h.chat.getMessages = vi.fn().mockResolvedValue({ messages: [], last_seq: 0, page_bound: 40, kind: 'dm', my_state: 'active',
    my_last_read_seq: 0, counterparty: { kind: 'developer', id: 2, display_name: 'Mira' } })
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.postMessage = vi.fn().mockResolvedValue({ message: { id: 'm1', seq: 1, kind: 'text', body: 'x', sender_ptype: 'developer', sender_id: 6 } })
  const w = mount(PocketOurStateThread, opts)
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
const box = (w: any) => w.find('[data-testid="ost-input"]').element as HTMLTextAreaElement
async function type(w: any, text: string, textPx?: number) {
  if (textPx != null) textHeight(box(w), textPx)
  await w.find('[data-testid="ost-input"]').setValue(text)
  for (let i = 0; i < 3; i++) await flushPromises()
}
async function select(w: any, a: number, b: number) {
  const el = box(w)
  el.focus()
  el.setSelectionRange(a, b)
}
const px = (w: any) => box(w).style.height

beforeEach(() => {
  setActivePinia(createPinia())
  h.chat = {}
  h.route.params.id = 'room-a'
  h.auth.activeAgent = null
  localStorage.clear()
  paneH = 800
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', { configurable: true,
    get() { return (this as HTMLElement).classList?.contains('ost') ? paneH : 0 } })
})
afterEach(() => {
  document.body.innerHTML = ''
  if (clientHeightDesc) Object.defineProperty(HTMLElement.prototype, 'clientHeight', clientHeightDesc)
})

describe('the composer grows with the text', () => {
  it('is one line when empty, follows the text, and stops at 40% of the pane', async () => {
    const w = await open()
    expect(px(w)).toBe('44px')
    await type(w, 'a few lines of text', 200)
    expect(px(w)).toBe('200px')
    expect(box(w).style.overflowY).toBe('hidden')
    await type(w, 'a very long text', 900)
    expect(px(w)).toBe('320px')                       // 40% of the 800 px pane
    expect(box(w).style.overflowY).toBe('auto')        // and it scrolls inside itself past that
  })

  it('takes the 40% of the pane it is in: a short pane caps lower', async () => {
    paneH = 500
    const w = await open()
    await type(w, 'a very long text', 900)
    expect(px(w)).toBe('200px')
  })

  it('goes back to one line once the message is sent', async () => {
    const w = await open()
    await type(w, 'hello there', 200)
    expect(px(w)).toBe('200px')
    textHeight(box(w), 0)
    await w.find('[data-testid="ost-send"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(box(w).value).toBe('')
    expect(px(w)).toBe('44px')
  })
})

describe('the handle', () => {
  const grip = (w: any) => w.find('[data-testid="ost-grip"]')

  it('drags the box taller as the pointer moves up, and remembers the height on this device', async () => {
    const w = await open()
    await grip(w).trigger('pointerdown', { clientY: 500, pointerId: 1 })
    await grip(w).trigger('pointermove', { clientY: 400, pointerId: 1 })
    await flushPromises()
    expect(px(w)).toBe('144px')                        // 44 + the 100 px the pointer moved up
    await grip(w).trigger('pointerup', { pointerId: 1 })
    expect(localStorage.getItem('os_composer_h')).toBe('144')
  })

  it('does not move without a press, and cannot go past 70% of the pane', async () => {
    const w = await open()
    await grip(w).trigger('pointermove', { clientY: 100, pointerId: 1 })
    await flushPromises()
    expect(px(w)).toBe('44px')
    await grip(w).trigger('pointerdown', { clientY: 700, pointerId: 1 })
    await grip(w).trigger('pointermove', { clientY: -4000, pointerId: 1 })
    await flushPromises()
    expect(px(w)).toBe('560px')                        // 70% of 800
  })

  it('opens at the height it was left at, and ignores a damaged value', async () => {
    localStorage.setItem('os_composer_h', '260')
    const w = await open()
    expect(px(w)).toBe('260px')
    w.unmount()
    localStorage.setItem('os_composer_h', 'abc')
    const w2 = await open()
    expect(px(w2)).toBe('44px')
  })

  it('moves with the arrow keys, and Enter gives the size back', async () => {
    const w = await open()
    await grip(w).trigger('keydown', { key: 'ArrowUp' })
    await grip(w).trigger('keydown', { key: 'ArrowUp' })
    await flushPromises()
    expect(px(w)).toBe('92px')                         // 44 + 2 x 24
    expect(localStorage.getItem('os_composer_h')).toBe('92')
    await grip(w).trigger('keydown', { key: 'ArrowDown' })
    await flushPromises()
    expect(px(w)).toBe('68px')
    await grip(w).trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(px(w)).toBe('44px')
    expect(localStorage.getItem('os_composer_h')).toBeNull()
  })

  it('a double click gives the size back too', async () => {
    localStorage.setItem('os_composer_h', '300')
    const w = await open()
    expect(px(w)).toBe('300px')
    await grip(w).trigger('dblclick')
    await flushPromises()
    expect(px(w)).toBe('44px')
    expect(localStorage.getItem('os_composer_h')).toBeNull()
  })

  it('is a separator a keyboard can reach and a screen reader can name', async () => {
    const w = await open()
    expect(grip(w).attributes('role')).toBe('separator')
    expect(grip(w).attributes('tabindex')).toBe('0')
    expect(grip(w).attributes('aria-label')).toBe('Resize the message box')
  })
})

describe('the full-height editor', () => {
  it('takes 85% of the pane and goes back to what it was', async () => {
    const w = await open()
    const btn = w.find('[data-testid="ost-expand"]')
    expect(btn.attributes('aria-pressed')).toBe('false')
    await btn.trigger('click')
    await flushPromises()
    expect(px(w)).toBe('680px')                        // 85% of 800
    expect(btn.attributes('aria-pressed')).toBe('true')
    expect(btn.attributes('aria-label')).toBe('Smaller message box')
    await btn.trigger('click')
    await flushPromises()
    expect(px(w)).toBe('44px')
  })

  it('goes back to a dragged height, not to one line', async () => {
    localStorage.setItem('os_composer_h', '260')
    const w = await open()
    await w.find('[data-testid="ost-expand"]').trigger('click')
    await flushPromises()
    expect(px(w)).toBe('680px')
    await w.find('[data-testid="ost-expand"]').trigger('click')
    await flushPromises()
    expect(px(w)).toBe('260px')
  })

  it('is not remembered: the next open is not full-height', async () => {
    const w = await open()
    await w.find('[data-testid="ost-expand"]').trigger('click')
    await flushPromises()
    expect(localStorage.getItem('os_composer_h')).toBeNull()
  })
})

describe('the toolbar', () => {
  async function withTools() {
    const w = await open()
    if (!w.find('[data-testid="ost-tools"]').exists()) {
      await w.find('[data-testid="ost-tools-toggle"]').trigger('click')
      await flushPromises()
    }
    return w
  }

  it('opens and closes, and remembers which', async () => {
    const w = await open()
    const closedAtStart = !w.find('[data-testid="ost-tools"]').exists()
    const t = w.find('[data-testid="ost-tools-toggle"]')
    await t.trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-tools"]').exists()).toBe(closedAtStart)
    expect(localStorage.getItem('os_composer_tools')).toBe(closedAtStart ? '1' : '0')
  })

  it('bold wraps the selection, keeps it selected and leaves the caret in the box', async () => {
    const w = await withTools()
    await type(w, 'hello world')
    await select(w, 6, 11)
    await w.find('[data-testid="ost-fmt-bold"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('hello **world**')
    expect([box(w).selectionStart, box(w).selectionEnd]).toEqual([8, 13])
  })

  it('takes bold off again with a second press', async () => {
    const w = await withTools()
    await type(w, 'hello world')
    await select(w, 6, 11)
    await w.find('[data-testid="ost-fmt-bold"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    await w.find('[data-testid="ost-fmt-bold"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('hello world')
  })

  it('quote, list, code and link each edit the text', async () => {
    const w = await withTools()
    await type(w, 'one')
    await select(w, 0, 3)
    await w.find('[data-testid="ost-fmt-quote"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('> one')
    await w.find('[data-testid="ost-fmt-quote"]').trigger('click')
    await w.find('[data-testid="ost-fmt-list"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('- one')
    await type(w, 'run ls now')
    await select(w, 4, 6)
    await w.find('[data-testid="ost-fmt-code"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('run `ls` now')
    await type(w, 'see docs')
    await select(w, 4, 8)
    await w.find('[data-testid="ost-fmt-link"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('see [docs](https://)')
  })

  it('Ctrl+B and Ctrl+I format the selection, and an unmodified key does not', async () => {
    const w = await open()
    await type(w, 'hello world')
    await select(w, 6, 11)
    await w.find('[data-testid="ost-input"]').trigger('keydown', { key: 'b', ctrlKey: true })
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('hello **world**')
    await select(w, 0, 5)
    await w.find('[data-testid="ost-input"]').trigger('keydown', { key: 'i', metaKey: true })
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('*hello* **world**')
    await w.find('[data-testid="ost-input"]').trigger('keydown', { key: 'b' })
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(box(w).value).toBe('*hello* **world**')
  })

  it('Enter still sends and a shortcut does not', async () => {
    const w = await open()
    await type(w, 'hello')
    await w.find('[data-testid="ost-input"]').trigger('keydown', { key: 'Enter' })
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.chat.postMessage).toHaveBeenCalledTimes(1)
    expect(h.chat.postMessage.mock.calls[0][2].body).toBe('hello')
  })
})

describe('Write and Preview', () => {
  async function withTools() {
    const w = await open()
    if (!w.find('[data-testid="ost-tools"]').exists()) {
      await w.find('[data-testid="ost-tools-toggle"]').trigger('click')
      await flushPromises()
    }
    return w
  }

  it('shows the text the way the thread will render it, and Write brings the box back', async () => {
    const w = await withTools()
    await type(w, '**big** news\n\n- one\n- two')
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    const pv = w.find('[data-testid="ost-preview"]')
    expect(pv.exists()).toBe(true)
    expect(pv.html()).toContain('<strong>big</strong>')
    expect(pv.html()).toContain('<li>one</li>')
    expect(w.find('[data-testid="ost-input"]').attributes('style')).toContain('display: none')
    await w.find('[data-testid="ost-write"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-preview"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-input"]').attributes('style') || '').not.toContain('display: none')
    expect(box(w).value).toBe('**big** news\n\n- one\n- two')
  })

  it('never renders raw HTML: a script in the text is shown as text', async () => {
    const w = await withTools()
    await type(w, '<script>alert(1)</script> <img src=x onerror=alert(2)>')
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    const html = w.find('[data-testid="ost-preview"]').html()
    expect(html).not.toContain('<script')
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;script&gt;')
  })

  it('says so when there is nothing to preview', async () => {
    const w = await withTools()
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-preview"]').text()).toBe('Nothing to preview yet.')
  })

  it('pressing a format button while previewing goes back to writing', async () => {
    const w = await withTools()
    await type(w, 'hello')
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    await w.find('[data-testid="ost-fmt-bold"]').trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(w.find('[data-testid="ost-preview"]').exists()).toBe(false)
    expect(box(w).value).toBe('hello****')
  })

  it('still sends what is written while the preview is showing', async () => {
    const w = await withTools()
    await type(w, 'sent from preview')
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    await w.find('[data-testid="ost-send"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.chat.postMessage.mock.calls[0][2].body).toBe('sent from preview')
  })

  it('IS the posted message: the same component, so a status chip, a table and a code block\'s copy button are all there', async () => {
    const w = await withTools()
    await type(w, 'DONE: shipped\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n```bash\nmake ship\n```')
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    const pv = w.find('[data-testid="ost-preview"]')
    expect(pv.find('.cm-chip').text()).toBe('DONE')
    expect(pv.find('table').exists()).toBe(true)
    expect(pv.find('.cm-copy').exists()).toBe(true)
    expect(pv.find('[data-testid="cm"]').exists()).toBe(true)
  })

  it('a button typed into the text is text in the preview too', async () => {
    const w = await withTools()
    await type(w, '<button class="cm-copy">Copy</button>')
    await w.find('[data-testid="ost-preview-tab"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-preview"] button.cm-copy').exists()).toBe(false)
  })
})
