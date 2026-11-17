/**
 * V0662 (order gwo_16d8fb21303f269406eb772f, his suggestions 4 and 8):
 *  - the order page copies a link to the order (this console, #/guild?order=<id>);
 *  - "Post as the firm" in the Guild form, for an admin of an organization: the form posts through the organization's
 *    existing work-order door (POST /organizations/{id}/work-orders: the bounty leaves the firm's treasury under its
 *    procurement cap, an Idempotency-Key per form), never a new money path. A firm the person is only a member of is
 *    not offered; an admin without an acting agent can still post as the firm.
 * Red on f569f6a6e: no copy link, no choice of poster.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  route: null as any, replace: null as any, auth: null as any, guild: {} as Record<string, any>, copy: null as any,
  orgs: [] as any[], postOrg: null as any,
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
vi.mock('@/services/api/organizationService', () => ({
  organizationService: { listOrganizations: vi.fn(async () => h.orgs), postOrgWorkOrder: (...a: any[]) => h.postOrg(...a) },
}))
vi.mock('@/utils/copyText', () => ({ copyText: (...a: any[]) => h.copy(...a) }))

import GuildBoard from './GuildBoard.vue'

const opts = { global: { stubs: { Icon: true, ReadFailedNotice: true } } }

describe('a link to the order', () => {
  beforeEach(() => {
    h.guild = {}; h.orgs = []
    h.replace = vi.fn(async (to: any) => { h.route.query = { ...(to?.query || {}) } })
    h.copy = vi.fn().mockResolvedValue(true)
    h.auth = { token: 'dev-tok', isAuthenticated: true, user: { id: 6, is_admin: false }, isAdmin: false, agentToken: null, activeAgent: null }
  })

  it('the order page copies this console\'s link to the order', async () => {
    h.guild.detail = vi.fn(async () => ({ order: { id: 'gwo_link', title: 'Linked', status: 'open', bounty: '5', currency: 'ECU',
      poster_did: 'did:theprotocol:p', deliverable: null }, bids: [], events: [], names: {} }))
    h.route.query = { order: 'gwo_link' }
    const w = mount(GuildBoard, opts)
    try {
      await flushPromises()
      await w.find('[data-testid="gld-copy-link"]').trigger('click')
      expect(h.copy).toHaveBeenCalledWith(`${window.location.origin}${window.location.pathname}#/guild?order=gwo_link`)
    } finally { w.unmount() }
  })
})

describe('post as the firm', () => {
  beforeEach(() => {
    h.guild = {}
    h.replace = vi.fn(async (to: any) => { h.route.query = { ...(to?.query || {}) } })
    h.route.query = {}
    h.copy = vi.fn().mockResolvedValue(true)
    h.orgs = [
      { id: 'org-a', name: 'Lattice Works', my_role: 'admin', is_active: true },
      { id: 'org-o', name: 'Owned Firm', my_role: 'owner', is_active: true },
      { id: 'org-m', name: 'Member Only', my_role: 'member', is_active: true },
    ]
    h.postOrg = vi.fn(async () => ({ order_id: 'gwo_firm', org_id: 'org-a' }))
    // the page opens the order it just posted
    h.guild.detail = vi.fn(async (id: string) => ({ order: { id, title: 'Posted', status: 'open', bounty: '10', currency: 'ECU',
      poster_did: 'did:theprotocol:me', deliverable: null }, bids: [], events: [], names: {} }))
  })

  it('an admin picks the firm; the order goes through the firm\'s work-order door with a key, not the agent\'s post', async () => {
    h.auth = { token: 'dev-tok', isAuthenticated: true, user: { id: 6 }, isAdmin: false, agentToken: 'agent-tok',
      activeAgent: { did: 'did:theprotocol:me', name: 'Me' } }
    const w = mount(GuildBoard, opts)
    try {
      await flushPromises()
      await w.find('[data-tour="guild-post"]').trigger('click'); await flushPromises()
      const as = w.find('[data-testid="gld-post-as"]')
      expect(as.findAll('option').map((o) => o.attributes('value'))).toEqual(['agent', 'org-a', 'org-o'])
      await as.setValue('org-a')
      await w.find('#gld-post-name').setValue('Index the ledger')
      await w.find('.gld-modal-actions .gld-btn-primary').trigger('click'); await flushPromises()
      expect(h.postOrg).toHaveBeenCalledTimes(1)
      const [orgId, body, key] = h.postOrg.mock.calls[0]
      expect(orgId).toBe('org-a')
      expect(body).toMatchObject({ title: 'Index the ledger', bounty: '10', deadline_seconds: 86400 })
      expect(typeof key).toBe('string')
      expect(key.length).toBeGreaterThan(8)
      expect(h.guild.post?.mock?.calls?.length || 0, 'never the agent\'s own post').toBe(0)
    } finally { w.unmount() }
  })

  it('the agent stays the default; posting as it is the post it always was (control)', async () => {
    h.auth = { token: 'dev-tok', isAuthenticated: true, user: { id: 6 }, isAdmin: false, agentToken: 'agent-tok',
      activeAgent: { did: 'did:theprotocol:me', name: 'Me' } }
    h.guild.post = vi.fn(async () => ({ order_id: 'gwo_mine' }))
    const w = mount(GuildBoard, opts)
    try {
      await flushPromises()
      await w.find('[data-tour="guild-post"]').trigger('click'); await flushPromises()
      await w.find('#gld-post-name').setValue('Mine')
      await w.find('.gld-modal-actions .gld-btn-primary').trigger('click'); await flushPromises()
      expect(h.guild.post).toHaveBeenCalledTimes(1)
      expect(h.postOrg).not.toHaveBeenCalled()
    } finally { w.unmount() }
  })

  it('an admin without an acting agent can post as the firm', async () => {
    h.auth = { token: 'dev-tok', isAuthenticated: true, user: { id: 6 }, isAdmin: false, agentToken: null, activeAgent: null }
    const w = mount(GuildBoard, opts)
    try {
      await flushPromises()
      await w.find('[data-tour="guild-post"]').trigger('click'); await flushPromises()
      const as = w.find('[data-testid="gld-post-as"]')
      expect(as.findAll('option').map((o) => o.attributes('value'))).toEqual(['org-a', 'org-o'])
    } finally { w.unmount() }
  })
})
