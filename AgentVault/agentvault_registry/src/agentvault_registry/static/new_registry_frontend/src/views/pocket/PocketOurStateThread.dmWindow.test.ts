import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0655 (ay) (order gwo_57362aa3484807226198b8de, from the sessions' room, seq 1241): an organization room's side
 * panel on the console draws each member's logo with a ring for its state, and beside the wake switch Message (a small
 * direct-message window over the room, on the chat's own direct-thread routes), Mention (into this room's composer) and
 * Profile. A line sent in the window lands in the direct thread; the room keeps its place under it. The harness is
 * PocketOurStateThread.sidePanel.test.ts's. BASE (V0654): no logo, no ring, no quick action.
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


const LEAD = 'did:theprotocol:eu.test:lead', TESTER = 'did:theprotocol:eu.test:tester'
const member = (did: string, name: string, icon: string | null, status: string | null) => ({ did, name, icon_url: icon,
  owner_developer_id: 6, last_active_at: '2026-11-03T10:00:00Z', account_status: 'active',
  status: status ? { text: status, set_at: null, expires_at: '2099-01-01T00:00:00Z', expires_in_seconds: 9e6 } : null })
const orgPage = (messages: unknown[]) => ({ ...page('org', messages),
  room: { org_id: 'org1', title: 'TheProtocol Sessions', mode: 'open', topic: null,
    wake_modes: { [`agt:${LEAD}`]: 'listen', [`agt:${TESTER}`]: 'off' }, can_set_wake: false } })

describe('the side panel\'s members: logo, ring and quick actions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.base = '/ourchat'
    h.route.path = '/ourchat/room1'
    h.presence.mockReset().mockResolvedValue({ organization_id: 'org1', as_of: '', count: 2, agents: [
      member(LEAD, 'session-lead', 'https://docs.theprotocol.cloud/agents/session-lead/logo.png', 'planning V0655'),
      member(TESTER, 'session-tester', null, null)] })
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
    observed = []
    vi.stubGlobal('ResizeObserver', FakeResizeObserver)
    Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true,
      get() { return (this as HTMLElement).classList?.contains('ost') ? paneW : 0 } })
    paneW = SIDE_PANEL_MIN_PX + 200
    h.chat.getMessages = vi.fn().mockImplementation(async (_tok: string, id: string) => (id === 'room1'
      ? orgPage([text('m1', 1), text('m2', 2), text('m3', 3)])
      : { messages: [{ id: 'd4', seq: 4, kind: 'text', body: 'which proof first?', sender_ptype: 'agent', sender_id: LEAD }] }))
    h.chat.listApprovals = vi.fn().mockResolvedValue({ items: [], can_decide: false, presence: 'off' })
    h.chat.createConversation = vi.fn().mockResolvedValue({ conversation_id: 'dm-lead', created: false })
    h.chat.postMessage = vi.fn().mockImplementation(async (_tok: string, conv: string, p: any) => ({ message: {
      id: 'd5', seq: 5, kind: 'text', body: p.body, sender_ptype: 'developer', sender_id: 6, conversation_id: conv } }))
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    if (desc) Object.defineProperty(HTMLElement.prototype, 'clientWidth', desc)
  })

  it('each member\'s logo (its card\'s picture, else its initial) inside a ring that names its state', async () => {
    const w = mount(PocketOurStateThread, opts)
    await flushPromises()
    const lead = w.find(`[data-testid="csp-ring-${LEAD}"]`)
    expect(lead.attributes('data-ring')).toBe('live')
    expect(lead.attributes('aria-label')).toBe('session-lead: live, a status line is set')
    expect(lead.attributes('role')).toBe('img')
    expect(w.find(`[data-testid="csp-logo-${LEAD}"]`).attributes('src')).toBe('https://docs.theprotocol.cloud/agents/session-lead/logo.png')
    const tester = w.find(`[data-testid="csp-ring-${TESTER}"]`)
    expect(tester.attributes('data-ring')).toBe('off')
    expect(tester.attributes('title')).toBe('session-tester: off, nothing in this room wakes it')
    expect(w.find(`[data-testid="csp-logo-${TESTER}"]`).exists()).toBe(false)
    expect(tester.find('.csp-initial').text()).toBe('S')
    await w.find(`[data-testid="csp-logo-${LEAD}"]`).trigger('error')      // a logo that does not load draws the initial
    expect(w.find(`[data-testid="csp-logo-${LEAD}"]`).exists()).toBe(false)
    expect(w.find(`[data-testid="csp-profile-${LEAD}"]`).attributes('href')).toBe(`#/agent-profile/${encodeURIComponent(LEAD)}`)
    w.unmount()
  })

  it('Message opens the direct thread in a window over the room; a sent line lands there and the room keeps its place', async () => {
    const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
    await flushPromises()
    const list = w.find('[data-testid="ost-messages"]').element as HTMLElement
    list.scrollTop = 137
    const roomLines = () => w.findAll('[data-testid^="ost-msg-"]').map((x) => x.attributes('data-testid'))
    const before = roomLines()
    expect(w.find('[data-testid="cdw"]').exists()).toBe(false)
    await w.find(`[data-testid="csp-dm-${LEAD}"]`).trigger('click')
    await flushPromises()
    expect(h.chat.createConversation).toHaveBeenCalledWith('dev-tok', 'dm', { ptype: 'agent', agent_did: LEAD })
    const win = w.find('[data-testid="cdw"]')
    expect(win.attributes('data-conv')).toBe('dm-lead')
    expect(win.find('[data-testid="cdw-line-4"]').text()).toContain('which proof first?')
    await win.find('[data-testid="cdw-input"]').setValue('the console proof, then the pair proof')
    await win.find('form').trigger('submit')
    await flushPromises()
    expect(h.chat.postMessage).toHaveBeenCalledTimes(1)
    expect(h.chat.postMessage.mock.calls[0].slice(0, 2)).toEqual(['dev-tok', 'dm-lead'])
    expect(h.chat.postMessage.mock.calls[0][2]).toMatchObject({ kind: 'text', body: 'the console proof, then the pair proof' })
    expect(w.find('[data-testid="cdw-line-5"]').text()).toContain('the console proof, then the pair proof')
    expect(list.scrollTop).toBe(137)                      // the room did not move
    expect(roomLines()).toEqual(before)                   // and the line is not in the room
    expect(h.route.path).toBe('/ourchat/room1')           // the room stays open
    await w.find('[data-testid="cdw-close"]').trigger('click')
    expect(w.find('[data-testid="cdw"]').exists()).toBe(false)
    w.unmount()
  })

  it('Mention puts the member\'s name into the room\'s composer, after what is already there', async () => {
    const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
    await flushPromises()
    const box = w.find('[data-testid="ost-input"]')
    await box.setValue('please look at this')
    await w.find(`[data-testid="csp-mention-${LEAD}"]`).trigger('click')
    expect((box.element as HTMLTextAreaElement).value).toBe('please look at this @session-lead ')
    w.unmount()
  })
})
