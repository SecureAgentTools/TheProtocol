import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the OurChat thread list (Pocket and the desktop /ourchat shell) over three
 * side reads that failed silently:
 *  - the Requests lane's badge: a failed requests read hid it, as if no stranger's first message waited;
 *  - the Protocol row's unread notices: a failed count read showed no badge, as if none waited;
 *  - the starter agents under "Pick one to start": a failed read left the line over nothing to pick.
 * The badges say '—' (titled) until a read answers, and the starters say their read failed, with Try again. The list's
 * own failure was already said (the error replaces the list). Answered reads keep their counts and rows (the control).
 */
const h = vi.hoisted(() => ({
  listConversations: vi.fn(), orgRooms: vi.fn(), awayDigest: vi.fn(), discover: vi.fn(), fetch: vi.fn(),
}))
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
const failed = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const AGENT = { did: 'did:theprotocol:a1', name: 'Atlas', card_data: { pricing: { payment_required: true, base_rate: 1 } } }
const has = (w: ReturnType<typeof mount>, id: string) => w.find(`[data-testid="${id}"]`).exists()

function answer(requests: 'fail' | number, starters: 'fail' | 'ok', notices: 'fail' | 'down' | number) {
  h.listConversations.mockImplementation(async (_tok: string, lane: string) => {
    if (lane === 'requests') {
      if (requests === 'fail') throw failed()
      return { conversations: Array.from({ length: requests }, (_, i) => ({ id: `r${i}` })) }
    }
    return { conversations: [], next_cursor: null, cross_registry: false }
  })
  h.orgRooms.mockResolvedValue({ rooms: [], enableable: [] })
  h.awayDigest.mockResolvedValue({ threads: [] })
  if (starters === 'fail') h.discover.mockRejectedValue(failed())
  else h.discover.mockResolvedValue({ results: [AGENT] })
  h.fetch.mockImplementation(async (url: string) => {
    if (String(url).includes('unread-count')) {
      if (notices === 'fail') throw new TypeError('Failed to fetch')
      if (notices === 'down') return { ok: false, status: 502, json: async () => ({}) }
      return { ok: true, status: 200, json: async () => ({ count: notices }) }
    }
    return { ok: false, status: 404, json: async () => ({}) }
  })
}

describe('the OurChat list says what its side reads answered', () => {
  beforeEach(() => {
    for (const f of Object.values(h)) f.mockReset()
    vi.stubGlobal('fetch', h.fetch)
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('failed reads: the Requests badge and the Protocol count say "—", the starters say their read failed', async () => {
    answer('fail', 'fail', 'down')
    const w = mount(PocketOurState, opts)
    await flushPromises()
    expect(has(w, 'os-req-count-unread'), 'the Requests badge over a failed read').toBe(true)
    expect(has(w, 'os-protocol-unread-unknown'), 'the Protocol count over a failed read').toBe(true)
    expect(has(w, 'os-cast-unread'), 'the starters over a failed read').toBe(true)
    h.discover.mockResolvedValue({ results: [AGENT] })
    await w.find('[data-testid="os-cast-unread"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(has(w, 'os-cast-unread')).toBe(false)
    expect(has(w, `os-cast-${AGENT.did}`)).toBe(true)
    w.unmount()
  })

  it('no answer at all on the unread count: "—" as well', async () => {
    answer(0, 'ok', 'fail')
    const w = mount(PocketOurState, opts)
    await flushPromises()
    expect(has(w, 'os-protocol-unread-unknown')).toBe(true)
    w.unmount()
  })

  it('control: answered reads keep their counts, rows and words', async () => {
    answer(2, 'ok', 3)
    const w = mount(PocketOurState, opts)
    await flushPromises()
    expect(w.find('[data-testid="os-req-count"]').text()).toBe('2')
    expect(w.find('[data-testid="os-protocol"] .os-unread').text()).toBe('3')
    expect(has(w, `os-cast-${AGENT.did}`)).toBe(true)
    expect(w.text()).toContain('No threads yet')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    expect(has(w, 'os-req-count-unread') || has(w, 'os-protocol-unread-unknown')).toBe(false)
    w.unmount()
  })

  it('control: answered zeros show no badge at all', async () => {
    answer(0, 'ok', 0)
    const w = mount(PocketOurState, opts)
    await flushPromises()
    expect(w.find('.os-lane-badge').exists()).toBe(false)
    expect(w.find('[data-testid="os-protocol"] .os-unread').exists()).toBe(false)
    w.unmount()
  })
})
