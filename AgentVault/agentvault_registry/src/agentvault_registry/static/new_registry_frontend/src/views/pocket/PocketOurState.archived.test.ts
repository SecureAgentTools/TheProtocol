import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0663 (order gwo_daf7fc3c8b3174f6f73c0d8a): the list's Archived lane. An archived room is in that lane only, asked for with
 * state=archived; the lane says so when empty; and it never touches the Requests badge (an archived room is not a request).
 * The harness is PocketOurState.mentions.test.ts's.
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
const row = (id: string, over: Record<string, any> = {}) => ({ id, kind: 'room', title: `Room ${id}`, topic: 't', last_seq: 5, unread: 0,
  last_preview: 'x', last_message_at: new Date().toISOString(), muted: false, counterparty: null, ...over })

beforeEach(() => {
  for (const f of Object.values(h)) f.mockReset()
  h.orgRooms.mockResolvedValue({ rooms: [], enableable: [] })
  h.awayDigest.mockResolvedValue({ threads: [] })
  h.discover.mockResolvedValue({ results: [] })
  h.fetch.mockResolvedValue({ ok: true, status: 200, json: async () => ({ count: 0 }) })
  vi.stubGlobal('fetch', h.fetch)
})
afterEach(() => { vi.unstubAllGlobals() })

describe('the Archived lane', () => {
  it('asks for state=archived, lists those rooms there, and leaves the Requests badge alone', async () => {
    h.listConversations.mockImplementation(async (_t: string, lane: string) => {
      if (lane === 'archived') return { conversations: [row('old1'), row('old2')], next_cursor: null }
      if (lane === 'requests') return { conversations: [{ id: 'q1' }] }
      return { conversations: [row('live')], next_cursor: null }
    })
    const w = mount(PocketOurState, opts)
    await flushPromises()
    expect(w.find('[data-testid="os-req-count"]').text()).toBe('1')
    await w.find('[data-testid="os-lane-archived"]').trigger('click')
    await flushPromises()
    expect(h.listConversations.mock.calls.some((c) => c[1] === 'archived')).toBe(true)
    expect(w.text()).toContain('Room old1')
    expect(w.text()).not.toContain('Room live')
    expect(w.find('[data-testid="os-req-count"]').text()).toBe('1')          // two archived rooms did not become two requests
    expect(w.find('[data-testid="os-lane-archived"]').attributes('aria-selected')).toBe('true')
    w.unmount()
  })

  it('says so when nothing is archived', async () => {
    h.listConversations.mockImplementation(async (_t: string, lane: string) => ({ conversations: lane === 'active' ? [row('live')] : [], next_cursor: null }))
    const w = mount(PocketOurState, opts)
    await flushPromises()
    await w.find('[data-testid="os-lane-archived"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="os-archived-empty"]').text()).toContain('No archived rooms')
    w.unmount()
  })
})
