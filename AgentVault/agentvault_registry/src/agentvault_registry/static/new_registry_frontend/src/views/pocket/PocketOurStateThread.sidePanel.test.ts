import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (ad) (order gwo_e5e9ad061d6e5be9605a3067): on the console's chat an organization room whose pane is wide enough
 * shows the room's side panel beside the column, and the approvals live there (one place per fact: not also above the
 * history); a narrower pane, Pocket's mount and a direct thread draw the thread as before, the approvals pinned above
 * the history; the pane's own width decides, and a resize across the breakpoint moves the approvals back. BASE (V0651):
 * no side panel on any mount.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  base: '/ourchat',
  presence: vi.fn(),
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  stream: null as null | { onMessage: (env: any) => void },
}))
vi.mock('@/services/api/chat', () => ({
  chatApi: new Proxy({}, { get: (_t, k: string) => (h.chat[k] ??= vi.fn().mockResolvedValue({})) }),
}))
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
  return { useOurChatBase: () => ({ base: ref(h.base) }) }
})
vi.mock('@/services/api/organizationService', () => ({ organizationService: { getOrgPresence: h.presence } }))
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
  h.route = reactive({ params: { id: 'room1' }, query: {}, path: '/ourchat/room1' })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'
import { SIDE_PANEL_MIN_PX } from '@/services/chat/sidePanel'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true },
  },
}
const text = (id: string, seq: number) => ({ id, seq, kind: 'text', body: `m${seq}`, sender_ptype: 'developer', sender_id: '7',
  sender_name: 'Mira', created_at: '2026-10-31T03:00:00Z' })
const page = (kind: string, messages: unknown[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind,
  my_state: 'active', counterparty: null,
  room: kind === 'org' ? { org_id: 'org1', title: 'TheProtocol Sessions', mode: 'open', topic: null } : undefined })
const pending = { items: [{ id: 'apr_1', conversation_id: 'room1', status: 'pending', title: 'Roll V0651',
  requester: { agent_did: 'did:x:aaaaaa', name: 'session-release' }, created_at: '2026-10-31T03:50:00Z',
  expires_at: '2099-01-01T00:00:00Z' }], can_decide: true, presence: 'off' }

/* the test DOM lays nothing out: the thread pane reports the width a test gives it, and a resize is what a browser's
   ResizeObserver reports for the element the thread observes (the pane, never the window) */
let paneW = 0
const desc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth')
let observed: Array<{ el: Element; cb: (e: unknown[], o: unknown) => void }> = []
class FakeResizeObserver {
  cb: (e: unknown[], o: unknown) => void
  constructor(cb: (e: unknown[], o: unknown) => void) { this.cb = cb }
  observe(el: Element) { observed.push({ el, cb: this.cb }) }
  unobserve(el: Element) { observed = observed.filter((x) => x.el !== el) }
  disconnect() { observed = observed.filter((x) => x.cb !== this.cb) }
}
function resizeTo(w: number) {
  paneW = w
  for (const o of observed) if (o.el.classList.contains('ost')) o.cb([{ target: o.el }], null)
}

describe('the side panel beside the column, on the console', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.base = '/ourchat'
    h.route.path = '/ourchat/room1'
    h.presence.mockReset().mockResolvedValue({ organization_id: 'org1', as_of: '', agents: [], count: 0 })
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
    observed = []
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true,
      get() { return (this as HTMLElement).classList?.contains('ost') ? paneW : 0 } })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    if (desc) Object.defineProperty(HTMLElement.prototype, 'clientWidth', desc)
  })

  it('a wide pane in an organization room: the panel beside the column, the approvals in it and not above the history', async () => {
    paneW = SIDE_PANEL_MIN_PX + 200
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1), text('m2', 2)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const side = w.find('[data-testid="ost-side"]')
    expect(side.exists()).toBe(true)
    const panels = w.findAll('[data-testid="ost-approvals"]')
    expect(panels).toHaveLength(1)
    expect(side.element.contains(panels[0].element)).toBe(true)
    expect(w.find('[data-testid="oca-item-apr_1"]').exists()).toBe(true)
    expect(w.find('[data-testid="csp-approvals-count"]').text()).toBe('1')
    expect(h.presence).toHaveBeenCalledWith('org1')
    /* the column comes first and holds the history and the composer; the panel is its sibling */
    const col = w.find('.ost-col')
    expect(col.element.contains(w.find('[data-testid="ost-messages"]').element)).toBe(true)
    expect(col.element.nextElementSibling).toBe(side.element)
    expect(w.find('[data-testid="ost-root"]').classes()).toContain('ost--desk')
    w.unmount()
  })

  it('under the breakpoint the thread draws as before: no panel, the approvals pinned above the history', async () => {
    paneW = SIDE_PANEL_MIN_PX - 1
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-side"]').exists()).toBe(false)
    const panel = w.find('[data-testid="ost-approvals"]')
    const scroll = w.find('[data-testid="ost-messages"]')
    expect(panel.exists()).toBe(true)
    expect(scroll.element.contains(panel.element)).toBe(false)
    expect(panel.element.compareDocumentPosition(scroll.element) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(h.presence).not.toHaveBeenCalled()
    w.unmount()
  })

  it('a resize across the breakpoint moves the approvals into the panel and back', async () => {
    paneW = SIDE_PANEL_MIN_PX - 100
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-side"]').exists()).toBe(false)
    resizeTo(SIDE_PANEL_MIN_PX + 100)
    await flushPromises()
    expect(w.find('[data-testid="ost-side"] [data-testid="ost-approvals"]').exists()).toBe(true)
    resizeTo(SIDE_PANEL_MIN_PX - 100)
    await flushPromises()
    expect(w.find('[data-testid="ost-side"]').exists()).toBe(false)
    expect(w.findAll('[data-testid="ost-approvals"]')).toHaveLength(1)
    w.unmount()
    expect(observed.filter((o) => o.el.classList.contains('ost'))).toHaveLength(0)   // the observer goes with the thread
  })

  it("a phone-width pane marks the thread narrow (the speaker chip drops its 'as'); widened, it is not", async () => {
    h.base = '/pocket/ourchat'
    h.route.path = '/pocket/ourchat/room1'
    paneW = 393
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-root"]').classes()).toContain('ost--narrow')
    expect(w.find('[data-testid="ost-speaker"] .ost-speaker-name').exists()).toBe(true)   // the name stays, the "as" is styled away
    resizeTo(844)
    await flushPromises()
    expect(w.find('[data-testid="ost-root"]').classes()).not.toContain('ost--narrow')
    w.unmount()
  })

  it("Pocket's mount keeps its own layout, however wide", async () => {
    h.base = '/pocket/ourchat'
    h.route.path = '/pocket/ourchat/room1'
    paneW = SIDE_PANEL_MIN_PX + 600
    h.chat.getMessages = vi.fn().mockResolvedValue(page('org', [text('m1', 1)]))
    h.chat.listApprovals = vi.fn().mockResolvedValue(pending)
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-side"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-approvals"]').exists()).toBe(true)
    expect(w.find('[data-testid="ost-root"]').classes()).not.toContain('ost--desk')
    w.unmount()
  })

  it('a direct thread has no side panel and reads no presence', async () => {
    paneW = SIDE_PANEL_MIN_PX + 600
    h.chat.getMessages = vi.fn().mockResolvedValue(page('dm', [text('m1', 1)]))
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    expect(w.find('[data-testid="ost-side"]').exists()).toBe(false)
    expect(h.presence).not.toHaveBeenCalled()
    w.unmount()
  })
})
