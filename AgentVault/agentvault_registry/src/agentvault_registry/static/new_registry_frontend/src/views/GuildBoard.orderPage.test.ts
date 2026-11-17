/**
 * V0662 console polish, item 3 (order gwo_0aa7b875cbf65b6347f5f775): the order page shows the delivery as fields a
 * person can copy, each event as a word (its stored name on hover), and each party by name (its DID on hover), from the
 * `names` the order's answer now carries. Red on f569f6a6e: raw JSON, stored names, shortened DIDs.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const POSTER = 'did:theprotocol:eu.test:poster-agent-0001'
const WORKER = 'did:theprotocol:eu.test:worker-agent-0002'

const h = vi.hoisted(() => ({
  route: null as any,
  replace: null as any,
  auth: null as any,
  guild: {} as Record<string, any>,
  copy: null as any,
}))

vi.mock('vue-router', async () => {
  const { reactive } = await import('vue')
  h.route = reactive({ path: '/guild', query: {} as Record<string, string>, params: {} })
  return {
    useRoute: () => h.route,
    useRouter: () => ({ replace: (...a: any[]) => h.replace(...a), push: vi.fn().mockResolvedValue(undefined) }),
  }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn() }) }))
vi.mock('@/composables/useCurrency', async () => {
  const { computed } = await import('vue')
  return { useCurrency: () => ({ localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/services/api/guild', () => ({
  guildApi: new Proxy({}, { get: (_t, k: string) => (h.guild[k] ??= vi.fn().mockResolvedValue({ orders: [], total: 0 })) }),
}))
vi.mock('@/utils/copyText', () => ({ copyText: (...a: any[]) => h.copy(...a) }))

import GuildBoard from './GuildBoard.vue'

const opts = { global: { stubs: { Icon: true, ReadFailedNotice: true } } }

const detail = () => ({
  order: { id: 'gwo_p', title: 'Named order', status: 'verified', bounty: '5', currency: 'ECU',
    poster_did: POSTER, worker_did: WORKER,
    deliverable: { uri: 'https://git.example/branch', text: 'Done, the branch has it',
      commits: [{ repo: 'theprotocol/AgentVault', commit: 'c4a6b49ab' }] } },
  bids: [],
  events: [
    { seq: 1, event_type: 'posted', actor_did: POSTER, payload: {}, created_at: '2026-11-13T10:00:00Z' },
    { seq: 2, event_type: 'submitted', actor_did: WORKER, payload: {}, created_at: '2026-11-13T11:00:00Z' },
    { seq: 3, event_type: 'xf_new_thing', actor_did: null, payload: {}, created_at: '2026-11-13T12:00:00Z' },
  ],
  names: { [POSTER]: null, [WORKER]: 'session-code' },
})

async function openOrder() {
  h.guild.detail = vi.fn(async () => detail())
  h.route.query = { order: 'gwo_p' }
  const w = mount(GuildBoard, opts)
  await flushPromises()
  return w
}

describe('the order page in words', () => {
  beforeEach(() => {
    h.guild = {}
    h.replace = vi.fn(async (to: any) => { h.route.query = { ...(to?.query || {}) } })
    h.route.query = {}
    h.copy = vi.fn().mockResolvedValue(true)
    h.auth = { token: 'dev-tok', user: { id: 6, is_admin: false }, isAdmin: false, agentToken: null, activeAgent: null }
  })

  it('the delivery is fields, each with a copy button, never raw JSON', async () => {
    const w = await openOrder()
    try {
      const deliv = w.find('[data-testid="gld-deliverable"]')
      expect(deliv.exists()).toBe(true)
      expect(deliv.text()).not.toContain('{"')
      expect(deliv.find('[data-testid="gld-deliv-field-uri"] a').attributes('href')).toBe('https://git.example/branch')
      expect(deliv.find('[data-testid="gld-deliv-field-text"]').text()).toContain('Done, the branch has it')
      expect(deliv.find('[data-testid="gld-deliv-field-commit:0"]').text()).toContain('c4a6b49ab')
      await deliv.find('[data-testid="gld-copy-commit:0"]').trigger('click')
      expect(h.copy).toHaveBeenCalledWith('c4a6b49ab')
    } finally { w.unmount() }
  })

  it('each event is a word, its stored name on hover', async () => {
    const w = await openOrder()
    try {
      const types = w.findAll('.gld-tl-type')
      expect(types.map((x) => x.text())).toEqual(['Posted', 'Work submitted', 'Xf new thing'])
      expect(types.map((x) => x.attributes('title'))).toEqual(['posted', 'submitted', 'xf_new_thing'])
    } finally { w.unmount() }
  })

  it('each party by the name the order gives, its DID on hover; a nameless one by its DID', async () => {
    const w = await openOrder()
    try {
      const actors = w.findAll('.gld-tl-actor')
      expect(actors.map((x) => x.text())).toEqual(['did:theprotocol…-0001', 'session-code'])
      expect(actors.map((x) => x.attributes('title'))).toEqual([POSTER, WORKER])
    } finally { w.unmount() }
  })
})
