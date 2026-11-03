import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0654 (aq) (order gwo_238870d0f3c281c7d870554d): the room's member sheet shows what of the room wakes each member, and
 * the room's owner (signed in) switches a session's there: listen, on call, off. The registry posts the line; the sheet
 * and the side panel follow. The harness is PocketOurStateThread.settings.test.ts's. BASE (V0653): no mode, no switch.
 */
const AGENT = { did: 'did:theprotocol:eu.theprotocol.cloud:19c1aa48', name: 'session-tester' }   // the harness's own agent
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

const TESTER = 'did:theprotocol:eu.test:tester'
const TKEY = 'agt:' + TESTER
const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, RouterLink: true, 'router-link': true,
      ChatYouSettings: true },
  },
}
const ROOM = { title: 'TheProtocol Sessions', mode: 'open', my_is_operator: true, my_org_role: 'owner', member_count: 3,
  wake_modes: { 'dev:6': 'listen', [TKEY]: 'listen' }, can_set_wake: true }
const thread = () => ({ messages: [], last_seq: 0, page_bound: 40, kind: 'org', my_state: 'active', my_last_read_seq: 0,
  counterparty: null, room: ROOM, hosting: { registry: 'EU', copies: [] }, retention_hours: null, muted: false, muted_until: null })
const sheet = (canSet: boolean, mode = 'listen') => ({ conversation_id: 'room-a', org_id: 'org1', can_set_wake: canSet, members: [
  { ptype: 'developer', developer_id: 6, agent_did: null, name: 'maintainer', org_role: 'owner', can_post: true, is_me: true,
    key: 'dev:6', wake_mode: 'listen' },
  { ptype: 'agent', developer_id: null, agent_did: TESTER, name: 'session-tester', org_role: null, can_post: true, is_me: false,
    key: TKEY, wake_mode: mode },
] })

async function openSheet(canSet: boolean, mode = 'listen') {
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }) as any
  h.chat.getMessages = vi.fn().mockResolvedValue(thread())
  h.chat.markRead = vi.fn().mockResolvedValue({})
  h.chat.roomMembers = vi.fn().mockResolvedValue(sheet(canSet, mode))
  const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('[data-testid="ost-menu"]').trigger('click')
  await w.find('[data-testid="ost-room-members"]').trigger('click')
  for (let i = 0; i < 3; i++) await flushPromises()
  return w
}

describe('a member\'s wake mode in the member sheet', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.user = { developer_id: 6, name: 'maintainer' } as any
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('the room\'s owner switches a session on call: one call by its key, the sheet follows, the line lands', async () => {
    const w = await openSheet(true)
    expect(w.find(`[data-testid="wake-switch-${TESTER}"]`).attributes('data-mode')).toBe('listen')
    h.chat.setWakeMode = vi.fn().mockResolvedValue({ conversation_id: 'room-a', member: TKEY, wake_mode: 'on-call',
      previous: 'listen', changed: true, system_message: { id: 'm-w1', seq: 1, kind: 'system', body: 'room.wake',
        card: { by: 'dev:6', by_name: 'maintainer', action: 'wake', target_name: 'session-tester', value: 'on-call', target: TKEY },
        sender_ptype: 'developer', sender_id: 6, created_at: '2026-11-02T16:30:00Z' } })
    await w.find(`[data-testid="wake-on-call-${TESTER}"]`).trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(h.chat.setWakeMode).toHaveBeenCalledWith('dev.tok', 'room-a', 'on-call', TKEY)
    expect(w.find(`[data-testid="wake-switch-${TESTER}"]`).attributes('data-mode')).toBe('on-call')
    expect(w.find('[data-testid="ost-sysrow-1"]').text()).toContain('maintainer put session-tester on call')
  })

  it('no switch for the owner\'s own row, and anyone else reads the mode without one', async () => {
    const own = await openSheet(true)
    expect(own.find('[data-testid^="wake-switch-"]').attributes('data-testid')).toBe(`wake-switch-${TESTER}`)
    own.unmount()
    document.body.innerHTML = ''
    const w = await openSheet(false, 'off')
    expect(w.find('[data-testid^="wake-switch-"]').exists()).toBe(false)
    expect(w.find(`[data-testid="ost-wake-${TESTER}"]`).text()).toBe('Off')
  })

  it('a refusal says why, and the sheet keeps the mode it had', async () => {
    const w = await openSheet(true)
    h.chat.setWakeMode = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { status: 403,
      detail: "only the room's owner sets another member's wake mode, from a signed-in console" }))
    await w.find(`[data-testid="wake-off-${TESTER}"]`).trigger('click')
    for (let i = 0; i < 3; i++) await flushPromises()
    expect(w.find(`[data-testid="wake-switch-${TESTER}"]`).attributes('data-mode')).toBe('listen')
    expect(w.find('[data-testid="ost-hint"]').text()).toContain("only the room's owner")
  })
})
