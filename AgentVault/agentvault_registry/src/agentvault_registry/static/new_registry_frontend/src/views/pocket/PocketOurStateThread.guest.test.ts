import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0662 (OurChat lane, the organizations package's item 8): a guest seat in the member sheet. A guest is listed as a guest; the
 * room's operator sees Remove on a guest and an Add-a-guest field (an agent DID or a developer id), the registry's refusal is
 * said in its sentence; anyone else sees the guest chip and no controls. BASE (2d8181416): no chip, no controls.
 * The harness is PocketOurStateThread.wake.test.ts's.
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

const GUEST = 'did:theprotocol:eu.test:quantum-session'
const GKEY = 'agt:' + GUEST
const opts = {
  global: { stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, OurStateCard: true, TrustLinesRow: true,
    ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, RouterLink: true, 'router-link': true, ChatYouSettings: true } },
}
const room = (op: boolean) => ({ title: 'TheProtocol Sessions', mode: 'open', my_is_operator: op, my_org_role: op ? 'owner' : 'member', member_count: 3,
  wake_modes: {}, can_set_wake: false })
const thread = (op: boolean) => ({ messages: [], last_seq: 0, page_bound: 40, kind: 'org', my_state: 'active', my_last_read_seq: 0,
  counterparty: null, room: room(op), hosting: { registry: 'EU', copies: [] }, retention_hours: null, muted: false, muted_until: null })
const sheet = (withGuest = true) => ({ conversation_id: 'room-a', org_id: 'org1', can_set_wake: false, members: [
  { ptype: 'developer', developer_id: 6, agent_did: null, name: 'maintainer', org_role: 'owner', can_post: true, is_me: true, key: 'dev:6', wake_mode: 'listen', guest: false },
  ...(withGuest ? [{ ptype: 'agent', developer_id: null, agent_did: GUEST, name: 'quantum-session', org_role: null, can_post: true, is_me: false,
    key: GKEY, wake_mode: 'listen', guest: true }] : []),
] })

async function openSheet(op: boolean, answers: any[] = [sheet()]) {
  window.matchMedia = vi.fn().mockReturnValue({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }) as any
  h.chat.getMessages = vi.fn().mockResolvedValue(thread(op))
  h.chat.markRead = vi.fn().mockResolvedValue({})
  const fn = vi.fn()
  answers.forEach((a) => fn.mockResolvedValueOnce(a))
  fn.mockResolvedValue(answers[answers.length - 1])
  h.chat.roomMembers = fn
  const w = mount(PocketOurStateThread, { ...opts, attachTo: document.body })
  for (let i = 0; i < 4; i++) await flushPromises()
  await w.find('[data-testid="ost-menu"]').trigger('click')
  await w.find('[data-testid="ost-room-members"]').trigger('click')
  for (let i = 0; i < 3; i++) await flushPromises()
  return w
}
const settle = async () => { for (let i = 0; i < 3; i++) await flushPromises() }

describe('guests in the member sheet', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.route.params.id = 'room-a'
    h.auth.user = { developer_id: 6, name: 'maintainer' } as any
    localStorage.clear()
  })
  afterEach(() => { document.body.innerHTML = '' })

  it('lists a guest as a guest, and a member as the member they are', async () => {
    const w = await openSheet(false)
    expect(w.find(`[data-testid="ost-guest-${GUEST}"]`).text()).toBe('guest')
    expect(w.find('[data-testid="ost-guest-6"]').exists()).toBe(false)
  })
  it('shows no controls to anyone but the room\'s operator', async () => {
    const w = await openSheet(false)
    expect(w.find('[data-testid="ost-guest-add"]').exists()).toBe(false)
    expect(w.find(`[data-testid="ost-guest-remove-${GUEST}"]`).exists()).toBe(false)
  })
  it('the operator adds a guest by agent DID: one call, then the sheet is read again', async () => {
    h.chat.seatGuest = vi.fn().mockResolvedValue({ guest: { key: GKEY } })
    const w = await openSheet(true, [sheet(false), sheet(true)])
    expect(w.find(`[data-testid="ost-guest-${GUEST}"]`).exists()).toBe(false)
    await w.find('[data-testid="ost-guest-input"]').setValue(`  ${GUEST} `)
    await w.find('[data-testid="ost-guest-add-btn"]').trigger('click')
    await settle()
    expect(h.chat.seatGuest).toHaveBeenCalledWith('dev.tok', 'room-a', { agent_did: GUEST })
    expect(w.find(`[data-testid="ost-guest-${GUEST}"]`).exists()).toBe(true)
    expect((w.find('[data-testid="ost-guest-input"]').element as HTMLInputElement).value).toBe('')
  })
  it('a developer id is sent as a number', async () => {
    h.chat.seatGuest = vi.fn().mockResolvedValue({ guest: {} })
    const w = await openSheet(true)
    await w.find('[data-testid="ost-guest-input"]').setValue('42')
    await w.find('[data-testid="ost-guest-add-btn"]').trigger('click')
    await settle()
    expect(h.chat.seatGuest).toHaveBeenCalledWith('dev.tok', 'room-a', { developer_id: 42 })
  })
  it('says what to give for a name that is neither, and sends nothing', async () => {
    h.chat.seatGuest = vi.fn()
    const w = await openSheet(true)
    await w.find('[data-testid="ost-guest-input"]').setValue('Mira')
    await w.find('[data-testid="ost-guest-add-btn"]').trigger('click')
    await settle()
    expect(h.chat.seatGuest).not.toHaveBeenCalled()
    expect(w.find('[data-testid="ost-guest-err"]').text()).toContain('agent DID')
  })
  it('shows the registry\'s refusal as its sentence', async () => {
    h.chat.seatGuest = vi.fn().mockRejectedValue(Object.assign(new Error('x'), { detail: 'they are already a member of this organization: the room is theirs' }))
    const w = await openSheet(true)
    await w.find('[data-testid="ost-guest-input"]').setValue('7')
    await w.find('[data-testid="ost-guest-add-btn"]').trigger('click')
    await settle()
    expect(w.find('[data-testid="ost-guest-err"]').text()).toContain('already a member of this organization')
  })
  it('the operator removes a guest by the sheet\'s key, and the sheet is read again', async () => {
    h.chat.removeGuest = vi.fn().mockResolvedValue({ guest: false })
    const w = await openSheet(true, [sheet(true), sheet(false)])
    await w.find(`[data-testid="ost-guest-remove-${GUEST}"]`).trigger('click')
    await settle()
    expect(h.chat.removeGuest).toHaveBeenCalledWith('dev.tok', 'room-a', GKEY)
    expect(w.find(`[data-testid="ost-guest-${GUEST}"]`).exists()).toBe(false)
  })
})
