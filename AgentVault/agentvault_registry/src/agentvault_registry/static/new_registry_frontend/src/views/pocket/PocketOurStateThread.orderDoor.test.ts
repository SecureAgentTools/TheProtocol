import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), item 1: the order card's door in the chat follows the landing
 * decision. This thread is mounted by both shells (/pocket/ourchat/:id and the desktop /ourchat/:id), and its order card
 * (guild.order.live) and work card (guild.order) both opened Pocket's order sheet, /pocket/payments?order=, in every
 * mode: in the desktop chat the maintainer landed in Pocket (sessions' room seq 2105). Like the quick-create modal's
 * doors, the order's door now asks services/uiMode: Pocket's sheet on a phone (or a saved Pocket choice), the order on
 * the desktop Guild board otherwise. BASE: /pocket/payments?order= at every width.
 */
const h = vi.hoisted(() => ({
  chat: {} as Record<string, ReturnType<typeof vi.fn>>,
  route: null as unknown as { params: { id: string }, query: Record<string, string>, path: string },
  push: null as unknown as Mock<(to: unknown) => Promise<undefined>>,
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
vi.mock('@/composables/useChatStream', () => ({ useChatStream: () => {} }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/ourchat') }) }
})
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
    useRouter: () => ({ push: (to: unknown) => h.push(to), replace: vi.fn().mockResolvedValue(undefined) }),
  }
})

import PocketOurStateThread from './PocketOurStateThread.vue'

const opts = {
  global: {
    stubs: { Icon: true, OurStateIdentity: true, UserAvatar: true, AgentSwitchList: true, TrustLinesRow: true,
      ActingContextNotice: true, PocketSend: true, Teleport: true, teleport: true, StepUpConfirm: true },
  },
}
const OID = 'gwo_c3eacb96b7ca74510052c55c'
const liveCard = {
  id: 'm2', seq: 2, kind: 'card', body: null, card_rev: 1, card_updated_at: '2026-11-07T19:12:09Z',
  sender_ptype: 'system', sender_id: 'guild', created_at: '2026-11-07T19:12:09Z',
  card: { v: 1, type: 'guild.order.live', refs: { order_id: OID }, data: { order_id: OID, title: 'V0658 (q)',
    status: 'open', bounty: '35', currency: 'ECU', bids: 1, events: [{ type: 'posted', at: null }] } },
}
const page = (messages: unknown[]) => ({ messages, last_seq: messages.length, page_bound: 40, kind: 'dm',
  my_state: 'active', counterparty: null })

function atWidth(px: number) { Object.defineProperty(window, 'innerWidth', { configurable: true, value: px }) }

async function pressTheOrder(): Promise<string> {
  h.chat.getMessages = vi.fn().mockResolvedValue(page([liveCard]))
  const w = mount(PocketOurStateThread, opts)
  await flushPromises()
  const open = w.find('[data-testid="osc-guild-open"]')
  expect(open.exists(), 'the order card offers its door').toBe(true)
  await open.trigger('click')
  await flushPromises()
  w.unmount()
  expect(h.push).toHaveBeenCalledTimes(1)
  const to = h.push.mock.calls[0][0]
  return typeof to === 'string' ? to : String((to as { path?: string } | null)?.path ?? '')
}

describe("the chat's Guild order card opens the order where the landing would", () => {
  const width = window.innerWidth
  beforeEach(() => {
    setActivePinia(createPinia())
    h.chat = {}
    h.push = vi.fn(async (_to: unknown) => undefined)
    try { localStorage.clear() } catch { /* no storage */ }
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, status: 404, json: async () => ({}) }))
  })
  afterEach(() => { vi.unstubAllGlobals(); atWidth(width) })

  it('on a desktop it opens the order on the Guild board, not the Pocket sheet', async () => {
    atWidth(1440)
    expect(await pressTheOrder()).toBe(`/guild?order=${OID}`)
  })

  it('on a phone it opens the Pocket order sheet, as before', async () => {
    atWidth(390)
    expect(await pressTheOrder()).toBe(`/pocket/payments?order=${OID}`)
  })

  it('a saved desktop choice on a narrow window opens the Guild board', async () => {
    atWidth(390)
    localStorage.setItem('tp_ui_mode', 'advanced')
    expect(await pressTheOrder()).toBe(`/guild?order=${OID}`)
  })
})
