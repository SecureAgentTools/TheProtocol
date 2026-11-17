import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0663 (order gwo_7dd5a9be91eede9c2cc35376, his request seq 3349): the room list shows an @ apart from the unread count when
 * the registry counted a mention of YOU above the room's read mark. Not for 0, and not for a count the registry could not take
 * (null): a row says nothing rather than "none". The harness is PocketOurState.reads.test.ts's.
 */
const h = vi.hoisted(() => ({ listConversations: vi.fn(), orgRooms: vi.fn(), awayDigest: vi.fn(), discover: vi.fn(), fetch: vi.fn() }))
vi.mock('@/services/api/chat', () => ({
  chatApi: { listConversations: h.listConversations, orgRooms: h.orgRooms, awayDigest: h.awayDigest },
}))
vi.mock('@/services/api/discovery', () => ({ discoveryService: { discover: h.discover } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'tok' }) }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'tok' }))
vi.mock('@/composables/useChatStream', () => ({ useChatStream: () => {} }))
vi.mock('@/composables/useOurChatBase', async () => {
  const { ref } = await import('vue')
  return { useOurChatBase: () => ({ base: ref('/pocket/ourstate') }) }
})
vi.mock('@/composables/useFrames', async () => {
  const { ref } = await import('vue')
  return { useFrames: () => ({ localCurrency: ref('ECU') }) }
})
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, path: '/pocket/ourstate' }),
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
}))

import PocketOurState from './PocketOurState.vue'

const opts = {
  global: {
    stubs: { Icon: true, UserAvatar: true, PocketProfile: true, TrustLinesRow: true, OurStateFind: true, OurStateIdentity: true,
      Teleport: true, teleport: true },
  },
}
const row = (id: string, over: Record<string, any> = {}) => ({ id, kind: 'room', title: `Room ${id}`, topic: 't', last_seq: 5, unread: 3,
  unread_mentions: 0, last_preview: 'x', last_message_at: new Date().toISOString(), muted: false, counterparty: null, ...over })

beforeEach(() => {
  for (const f of Object.values(h)) f.mockReset()
  h.orgRooms.mockResolvedValue({ rooms: [], enableable: [] })
  h.awayDigest.mockResolvedValue({ threads: [] })
  h.discover.mockResolvedValue({ results: [] })
  h.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ count: 0 }) })
  vi.stubGlobal('fetch', h.fetch)
})
afterEach(() => { vi.unstubAllGlobals() })

describe('the room list @ mark', () => {
  it('shows an @ for a room with a mention of you, apart from the unread count, and for no other', async () => {
    h.listConversations.mockImplementation(async (_t: string, lane: string) => lane === 'requests'
      ? { conversations: [] }
      : { conversations: [row('a', { unread_mentions: 2 }), row('b', { unread_mentions: 0 }), row('c', { unread_mentions: null })], next_cursor: null })
    const w = mount(PocketOurState, opts)
    await flushPromises()
    const marks = w.findAll('[data-testid="os-at"]')
    expect(marks).toHaveLength(1)
    expect(marks[0].text()).toBe('@')
    const rows = w.findAll('.os-row-meta').filter((r) => r.find('[data-testid="os-unread"]').exists())
    expect(rows).toHaveLength(3)                                              // every room still carries its own count
    expect(rows[0].find('[data-testid="os-at"]').exists()).toBe(true)         // the first row: @ beside "3"
    expect(rows[0].find('[data-testid="os-unread"]').text()).toBe('3')
    expect(rows[1].find('[data-testid="os-at"]').exists()).toBe(false)
    expect(rows[2].find('[data-testid="os-at"]').exists()).toBe(false)
    w.unmount()
  })
})
