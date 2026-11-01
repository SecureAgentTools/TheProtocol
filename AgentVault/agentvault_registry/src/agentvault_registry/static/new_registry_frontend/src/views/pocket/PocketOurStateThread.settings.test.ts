import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0652 (ak) (order gwo_8c69cc0fd1f3033a35f47969): the thread's settings, wired. The button names itself; on a wide
 * screen the menu opens under it, on a phone as a sheet; the menu shows the thread's own mute (read with the thread);
 * each row opens its sheet; Escape closes each; the timer has a Cancel and is read only for a room's member; a mute for
 * a while goes to the server with its end. BASE (V0651): a bare dots button and an inline list (no states, no Cancel,
 * Escape closing 9 of the 17 sheets).
 */
const AGENT = { did: 'did:theprotocol:eu.theprotocol.cloud:19c1aa48', name: 'session-tester' }
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
  return { usePocketAgent: () => ({ credAgents: ref([{ did: AGENT.did, name: AGENT.name }]), ensureAgentFor: vi.fn().mockResolvedValue(true),
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
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, RouterLink: true, 'router-link': true,
      ChatYouSettings: true },
  },
}
const ROOM = { title: 'TheProtocol Sessions', topic: 'the sessions coordinate here', mode: 'open', my_is_operator: true,
  my_org_role: 'owner', assistant_present: false, member_count: 6, genesis: { stated: 'One point per message.' } }
const thread = (over: Record<string, any> = {}) => ({ messages: [], last_seq: 0, page_bound: 40, kind: 'org', my_state: 'active',
  my_last_read_seq: 0, counterparty: null, room: ROOM, hosting: { registry: 'EU', copies: [] }, retention_hours: null,
  muted: false, muted_until: null, ...over })
function wide(on: boolean) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: on, addEventListener: () => {}, removeEventListener: () => {} }) as any
}
async function open(over: Record<string, any> = {}) {
  h.chat.getMessages = vi.fn().mockResolvedValue(thread(over))
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
const esc = () => window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))

describe('the thread\'s settings', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.user = { developer_id: 6, name: 'maintainer' } as any
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('the button names itself and opens a menu under it on a wide screen', async () => {
    wide(true)
    const w = await open()
    const btn = w.find('[data-testid="ost-menu"]')
    expect(btn.text()).toContain('Settings')
    expect(btn.attributes('aria-expanded')).toBe('false')
    await btn.trigger('click')
    expect(btn.attributes('aria-expanded')).toBe('true')
    expect(w.find('[data-testid="ost-menu-sheet"]').attributes('data-surface')).toBe('popover')
    expect(w.find('[data-testid="ost-room-members"]').text()).toContain('6')
  })

  it('on a phone it is a sheet', async () => {
    wide(false)
    const w = await open()
    await w.find('[data-testid="ost-menu"]').trigger('click')
    expect(w.find('[data-testid="ost-menu-sheet"]').attributes('data-surface')).toBe('sheet')
  })

  it('shows the thread\'s own mute, read with the thread', async () => {
    wide(true)
    const w = await open({ muted: true, muted_until: new Date(Date.now() + 3600e3).toISOString() })
    await w.find('[data-testid="ost-menu"]').trigger('click')
    expect(w.find('[data-testid="csm-notify-val"]').text()).toMatch(/^Only asks for me · until /)
  })

  it('a mute for a while goes to the server with its end', async () => {
    wide(true)
    const w = await open()
    h.chat.mute = vi.fn().mockResolvedValue({ muted: true, muted_until: '2099-01-01T08:00:00+00:00' })
    await w.find('[data-testid="ost-menu"]').trigger('click')
    await w.find('[data-testid="ost-notify"]').trigger('click')
    await w.find('[data-testid="cns-level-muted"]').trigger('click')
    await w.find('[data-testid="cns-for-1h"]').trigger('click')
    await w.find('[data-testid="cns-done"]').trigger('click')
    await flushPromises()
    const [tok, conv, muted, until] = h.chat.mute.mock.calls[0]
    expect([tok, conv, muted]).toEqual(['dev.tok', 'room-a', true])
    expect(Math.abs(Date.parse(until) - (Date.now() + 3600e3))).toBeLessThan(60e3)
    expect(w.find('[data-testid="ost-notify-sheet"]').exists()).toBe(false)
  })

  it.each([
    ['ost-notify', 'ost-notify-sheet'],
    ['ost-timer-open', 'ost-timer-sheet'],
    ['ost-burn', 'ost-burn-confirm'],
    ['ost-leave', 'ost-leave-confirm'],
    ['ost-room-settings', 'ost-room-dialog'],
    ['ost-you-settings', 'chat-you-panel'],
  ])('%s opens %s, and Escape closes it', async (row, sheet) => {
    wide(true)
    h.chat.reviewState = vi.fn().mockResolvedValue({ grants: [] })
    const w = await open()
    await w.find('[data-testid="ost-menu"]').trigger('click')
    await w.find(`[data-testid="${row}"]`).trigger('click')
    await flushPromises()
    expect(w.find(`[data-testid="${sheet}"]`).exists()).toBe(true)
    expect(w.find('[data-testid="ost-menu-sheet"]').exists()).toBe(false)
    esc()
    await flushPromises()
    expect(w.find(`[data-testid="${sheet}"]`).exists()).toBe(false)
  })

  it('the timer has a Cancel, and is read only for a room\'s member', async () => {
    wide(true)
    const w = await open({ room: { ...ROOM, my_is_operator: false, my_org_role: 'member' } })
    await w.find('[data-testid="ost-menu"]').trigger('click')
    await w.find('[data-testid="ost-timer-open"]').trigger('click')
    expect(w.find('[data-testid="ost-timer-readonly"]').exists()).toBe(true)
    expect(w.find('[data-testid="ost-timer-24"]').attributes('disabled')).toBeDefined()
    await w.find('[data-testid="ost-timer-cancel"]').trigger('click')
    expect(w.find('[data-testid="ost-timer-sheet"]').exists()).toBe(false)
  })

  it('a support thread offers no block, no timer and no leave', async () => {
    wide(true)
    h.chat.supportTicket = vi.fn().mockResolvedValue({ ticket_id: 1, status: 'open', subject: 'x' })
    const w = await open({ kind: 'support', room: null })
    await w.find('[data-testid="ost-menu"]').trigger('click')
    for (const absent of ['ost-block', 'ost-timer-open', 'ost-leave', 'ost-away-here']) {
      expect(w.find(`[data-testid="${absent}"]`).exists()).toBe(false)
    }
    expect(w.find('[data-testid="ost-burn"]').exists()).toBe(true)
  })
})

describe('the phone\'s back gesture closes the sheet, not the thread', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.route.query = {}
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('the open sheet is one history entry; back (the entry gone) closes it', async () => {
    wide(false)
    const w = await open()
    await w.find('[data-testid="ost-menu"]').trigger('click')
    expect(w.find('[data-testid="ost-menu-sheet"]').exists()).toBe(true)
    h.route.query = { settings: '1' }            // what the router's push did
    await flushPromises()
    h.route.query = {}                           // the back gesture
    await flushPromises()
    expect(w.find('[data-testid="ost-menu-sheet"]').exists()).toBe(false)
  })
})

describe('back closes the top settings sheet, not the thread (session-lead, seq 406)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.route.query = {}
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('the entry holds while the sheet a row opened is open; back closes that sheet', async () => {
    wide(false)
    const w = await open()
    await w.find('[data-testid="ost-menu"]').trigger('click')
    h.route.query = { settings: '1' }            // the router's push
    await flushPromises()
    await w.find('[data-testid="ost-notify"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="ost-notify-sheet"]').exists()).toBe(true)
    expect(h.route.query).toEqual({ settings: '1' })      // the menu closed, the layer did not: the entry stays
    h.route.query = {}                           // the back gesture
    await flushPromises()
    expect(w.find('[data-testid="ost-notify-sheet"]').exists()).toBe(false)
    expect(w.find('[data-testid="ost-root"]').exists()).toBe(true)
  })
})
