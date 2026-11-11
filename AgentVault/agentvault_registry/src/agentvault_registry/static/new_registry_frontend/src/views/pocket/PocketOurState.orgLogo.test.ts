import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0658 (t), session-code 2026-11-08: an organization's room wears its organization's hosted logo in the chat list, the
 * sidebar the desktop's /ourchat shell and Pocket both mount. The maintainer's check (the sessions' room seq 2156-2157):
 * the logo showed next to the room's name at the top of the thread (V0657 (b) item 5) and the room's entry in the list
 * still showed the generic room avatar.
 *
 *  - an opened room's row, a room not opened yet and an organization without a room show the logo the registry hosts
 *    (services/orgMark.ts safeLogo: a path on this registry, never another host's address);
 *  - no hosted logo, an older registry's row without the block, an address on another host, or a logo that does not
 *    load: today's room avatar;
 *  - a block that names a home origin cannot open another host either (the review of 5b12cf182: the avatar passed the
 *    block's `home` to safeLogo, which a room's block never carries; the thread's header passes none);
 *  - a thread with a person keeps its person's identity (the control).
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
  return { useOurChatBase: () => ({ base: ref('/pocket/ourchat') }) }
})
vi.mock('@/composables/useFrames', async () => {
  const { ref } = await import('vue')
  return { useFrames: () => ({ localCurrency: ref('ECU') }) }
})
vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {}, path: '/pocket/ourchat' }),
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn().mockResolvedValue(undefined) }),
}))

import PocketOurState from './PocketOurState.vue'

const opts = {
  global: {
    stubs: { Icon: true, UserAvatar: true, PocketProfile: true, TrustLinesRow: true, OurStateFind: true, OurStateIdentity: true,
      ChatYouPanel: true, Teleport: true, teleport: true },
  },
}

const id = (n: number) => `4f3c1b2a-0000-4000-8000-00000000000${n}`
const logoOf = (n: number) => `/api/v1/organizations/${id(n)}/logo?v=${String(n).repeat(12)}`
const block = (n: number, logo: string | null) => ({ id: id(n), slug: `org-${n}`, name: `Org ${n}`, logo, listed: false })
const room = (cid: string, org: any) => ({
  id: cid, kind: 'org', title: org?.name || 'Old Name', org_id: org?.id || id(9), mode: 'open', topic: null,
  last_preview: 'the last words', last_message_at: new Date().toISOString(), unread: 0, muted: false,
  counterparty: null, ...(org === undefined ? {} : { org }),
})
const ROWS = [
  room('c-logo', block(1, logoOf(1))),
  room('c-plain', block(2, null)),
  room('c-far', block(3, 'https://tracker.example/logo.png')),
  room('c-old', undefined),
  { id: 'c-dm', kind: 'dm', title: null, last_preview: 'hi', last_message_at: new Date().toISOString(), unread: 0,
    muted: false, counterparty: { ptype: 'developer', developer_id: 9, name: 'Kestrel' }, org: null },
]

function answer() {
  h.listConversations.mockImplementation(async (_tok: string, lane: string) =>
    lane === 'requests' ? { conversations: [] } : { conversations: ROWS, next_cursor: null, cross_registry: false })
  h.orgRooms.mockResolvedValue({
    rooms: [{ org_id: id(5), org_name: 'Org 5', my_org_role: 'member', conversation_id: null, mode: 'open', topic: null,
      last_message_at: null, last_preview: null, unread: 0, policy: 'owner_admin', may_disable: false,
      org: block(5, logoOf(5)) }],
    enableable: [{ org_id: id(6), org_name: 'Org 6', my_org_role: 'owner', policy: 'owner_admin', may_enable: true,
      org: block(6, logoOf(6)) }],
  })
  h.awayDigest.mockResolvedValue({ threads: [] })
  h.discover.mockResolvedValue({ results: [] })
  h.fetch.mockResolvedValue({ ok: false, status: 404, json: async () => ({}) })
}

const GROUP = 'icon-stub[name="mdi:account-group"]'

describe('an organization\'s room in the chat list wears its organization\'s logo', () => {
  beforeEach(() => {
    for (const f of Object.values(h)) f.mockReset()
    vi.stubGlobal('fetch', h.fetch)
    answer()
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('an opened room\'s entry shows the logo this registry hosts, in place of the room avatar', async () => {
    const w = mount(PocketOurState, opts)
    await flushPromises()
    const row = w.find('[data-testid="os-row-c-logo"]')
    expect(row.exists()).toBe(true)
    const img = row.find('img')
    expect(img.exists(), 'the room\'s entry shows its organization\'s logo').toBe(true)
    expect(img.attributes('src')).toBe(logoOf(1))
    expect(img.attributes('alt'), 'decorative: the room\'s name is beside it').toBe('')
    expect(row.find(GROUP).exists(), 'not the generic room avatar as well').toBe(false)
    w.unmount()
  })

  it('no hosted logo, an older registry\'s row, or an address on another host: today\'s room avatar', async () => {
    const w = mount(PocketOurState, opts)
    await flushPromises()
    for (const cid of ['c-plain', 'c-old', 'c-far']) {
      const row = w.find(`[data-testid="os-row-${cid}"]`)
      expect(row.exists(), cid).toBe(true)
      expect(row.find('img').exists(), `${cid}: no image`).toBe(false)
      expect(row.find(GROUP).exists(), `${cid}: the room avatar`).toBe(true)
    }
    expect(w.html()).not.toContain('tracker.example')
    w.unmount()
  })

  it('a block that names another home cannot send the browser there: only a path on this registry loads', async () => {
    // a room's block names no home (the organization is this registry's own), so an absolute address is never loaded,
    // not even one under an origin the block itself would name: the thread's header reads the same rule
    const far = { ...block(7, `https://tracker.example/api/v1/organizations/${id(7)}/logo`),
      home: { origin: 'https://tracker.example' } }
    h.listConversations.mockImplementation(async (_tok: string, lane: string) => lane === 'requests'
      ? { conversations: [] }
      : { conversations: [...ROWS, room('c-home', far)], next_cursor: null, cross_registry: false })
    const w = mount(PocketOurState, opts)
    await flushPromises()
    const row = w.find('[data-testid="os-row-c-home"]')
    expect(row.exists()).toBe(true)
    expect(row.find('img').exists(), 'no image from another host').toBe(false)
    expect(row.find(GROUP).exists(), 'today\'s room avatar').toBe(true)
    expect(w.html()).not.toContain('tracker.example')
    w.unmount()
  })

  it('a logo that does not load gives way to today\'s room avatar', async () => {
    const w = mount(PocketOurState, opts)
    await flushPromises()
    const row = () => w.find('[data-testid="os-row-c-logo"]')
    expect(row().find('img').exists(), 'the logo first').toBe(true)
    await row().find('img').trigger('error')
    expect(row().find('img').exists()).toBe(false)
    expect(row().find(GROUP).exists(), 'then the room avatar').toBe(true)
    w.unmount()
  })

  it('a room not opened yet and an organization without a room show their logos too', async () => {
    const w = mount(PocketOurState, opts)
    await flushPromises()
    const door = w.find(`[data-testid="os-room-${id(5)}"]`)
    expect(door.exists()).toBe(true)
    expect(door.find('img').exists(), 'the room\'s door in the Rooms section').toBe(true)
    expect(door.find('img').attributes('src')).toBe(logoOf(5))
    expect(door.find(GROUP).exists()).toBe(false)
    const off = w.find(`[data-testid="os-room-off-${id(6)}"]`)
    expect(off.exists()).toBe(true)
    expect(off.find('img').exists(), 'an organization without a room').toBe(true)
    expect(off.find('img').attributes('src')).toBe(logoOf(6))
    w.unmount()
  })

  it('control: a thread with a person keeps its person\'s identity', async () => {
    const w = mount(PocketOurState, opts)
    await flushPromises()
    const row = w.find('[data-testid="os-row-c-dm"]')
    expect(row.find('our-state-identity-stub').exists()).toBe(true)
    expect(row.find('img').exists() || row.find(GROUP).exists()).toBe(false)
    w.unmount()
  })
})
