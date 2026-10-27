/**
 * §FESUITE 135 (agentvault2-5b, 2026-10-15; agentvault2-61's finding): the organization picked last owns the screen.
 * On an org switch every open tab reloads, and no load checked on arrival that its organization was still the current
 * one: picking A, then B before A's answers came back left A's treasury and account in the page under B's header (every
 * action there keys on B's id), and the Treasury tab showed them again on return because a held answer is not re-read.
 * The audit trail's in-flight guard dropped B's read while A's ran, so A's rows stood under B; and the money account was
 * kept over a switch made on another tab. Each test switches through the org picker (handleOrgSwitch, which also returns
 * to the Teams tab) and holds A's answers back until B's have landed; all three fail on the unguarded view.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h as render, reactive, ref } from 'vue'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'

type Pending = { resolve: (v: unknown) => void }
const h = vi.hoisted(() => ({ pending: {} as Record<string, Pending>, calls: [] as string[], store: null as any }))
/** A read that answers only when the test says so, keyed `<read>:<organization>`. */
function held(name: string, orgId: string): Promise<unknown> {
  h.calls.push(`${name}:${orgId}`)
  return new Promise((resolve) => { h.pending[`${name}:${orgId}`] = { resolve } })
}
async function answer(key: string, value: unknown) {
  const p = h.pending[key]
  if (!p) throw new Error(`no read in flight for ${key} (asked so far: ${h.calls.join(', ')})`)
  delete h.pending[key]
  p.resolve(value)
  await flushPromises()
}

vi.mock('@/stores/organizations', () => ({
  useOrganizationStore: () => (h.store ??= reactive({
    currentOrganization: null as any, organizations: [] as any[], teams: [], members: [], isLoading: false,
    isLoadingTeams: false, isLoadingMembers: false, currentUserRole: 'owner', currentUserId: 7, canManageOrganization: true,
    canManageTeams: true, canInviteMembers: true, listRead: true, listFailed: false,
    fetchOrganizations: async () => {}, fetchMembers: async () => {}, fetchTeams: async () => {},
    selectOrganization: async (id: string) => { h.store.currentOrganization = h.store.organizations.find((o: any) => o.id === id) },
  })),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, token: 'dev.jwt', isAuthenticated: true }) }))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [{ did: 'did:theprotocol:a1' }], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showWarning: vi.fn(), showInfo: vi.fn() }) }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: async () => ({ data: { agents: [] } }) } }))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: new Proxy({}, {
    get: (_t, k: string) => {
      if (k === 'getOrgTreasuryAccount') return (oid: string) => held('account', oid)
      // the same read serves the audit trail and the account's money movements: told apart by what they ask for
      if (k === 'getOrgAuditEvents') return (oid: string, o?: { eventTypes?: string }) => held(o?.eventTypes ? 'moves' : 'audit', oid)
      return async () => ({ items: [], agents: [], events: [], proposals: [], approvals: [] })
    },
  }),
}))
vi.mock('@/services/api/exchangeService', () => ({
  exchangeService: new Proxy({}, { get: (_t, k: string) => (k === 'orgTreasury' ? (oid: string) => held('listings', oid) : async () => null) }),
}))
vi.mock('@/services/api/forge', () => ({ getForgeStatus: async () => ({ enabled: false }) }))
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useRegistryConfig: () => ({ config: ref({}) }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn(async () => {}) }),
  RouterLink: defineComponent({ name: 'RouterLink', setup: (_p, { slots }) => () => render('a', slots.default?.()) }),
}))

import { useOrganizationStore } from '@/stores/organizations'
import OrganizationDashboard from './OrganizationDashboard.vue'

const A = { id: 'org-a', name: 'Alder Freight', slug: 'alder', description: '', website: '' }
const B = { id: 'org-b', name: 'Birch Ledger', slug: 'birch', description: '', website: '' }
const account = (did: string) => ({ treasury_agent_did: did, source: 'org', balance: '10', exists: true })
const money = { raised: '0', balance: '10', fees_earned: '0', dividends_paid: '0' }
const listings = (symbol: string) => ({ listing_count: 1, currency: 'ECU', totals: money,
  listings: [{ symbol, status: 'active', currency: 'ECU', ...money }] })
const trail = (type: string) => ({ events: [{ event_type: type, timestamp: null, data: {} }] })

async function mounted(): Promise<VueWrapper> {
  const s = useOrganizationStore() as any
  s.organizations = [A, B]
  s.currentOrganization = A
  const w = shallowMount(OrganizationDashboard, { global: { stubs: { ReadFailedNotice: false, Icon: true } } })
  await flushPromises()
  return w
}
async function tab(w: VueWrapper, id: string) {
  await w.find(`[data-tour="org-tab-${id}"]`).trigger('click')
  await flushPromises()
}
/** Pick an organization with the page's own picker (handleOrgSwitch: select it, then back to the Teams tab). */
async function pick(w: VueWrapper, org: typeof A) {
  await w.find('select.org-selector').setValue(org.id)
  await flushPromises()
}

describe('the organization picked last owns the screen', () => {
  beforeEach(() => {
    h.pending = {}
    h.calls = []
    h.store = null
  })

  it("A's listings and account, answering after B's, never stand under B", async () => {
    const w = await mounted()
    await tab(w, 'treasury')
    expect(h.calls).toEqual(expect.arrayContaining(['listings:org-a', 'account:org-a']))
    await pick(w, B)
    expect(h.calls).toEqual(expect.arrayContaining(['listings:org-b', 'account:org-b']))
    await answer('listings:org-b', listings('BIRCH'))
    await answer('account:org-b', account('did:theprotocol:treasury-b'))
    await answer('listings:org-a', listings('ALDER'))
    await answer('account:org-a', account('did:theprotocol:treasury-a'))
    await tab(w, 'treasury')
    expect(w.find('.oa-did').text()).toBe('did:theprotocol:treasury-b')
    expect(w.text()).toContain('$BIRCH')
    expect(w.text()).not.toContain('$ALDER')
  })

  it("the audit trail reads B's while A's read runs, and A's rows never show under B", async () => {
    const w = await mounted()
    await tab(w, 'audit')
    expect(h.calls).toContain('audit:org-a')
    await pick(w, B)
    expect(h.calls, "B's trail was never asked for while A's read ran").toContain('audit:org-b')
    await answer('audit:org-b', trail('BirchMemberAdded'))
    await answer('audit:org-a', trail('AlderMemberAdded'))
    await tab(w, 'audit')   // the tab reads again on opening; what stands while that read runs is B's
    expect(w.text()).not.toContain('AlderMemberAdded')
    await answer('audit:org-b', trail('BirchMemberAdded'))
    expect(w.text()).toContain('BirchMemberAdded')
    expect(w.text()).not.toContain('AlderMemberAdded')
  })

  it("a switch made on another tab: the Treasury tab reads B's account and never shows A's", async () => {
    const w = await mounted()
    await tab(w, 'treasury')
    await answer('listings:org-a', listings('ALDER'))
    await answer('account:org-a', account('did:theprotocol:treasury-a'))
    expect(w.find('.oa-did').text()).toBe('did:theprotocol:treasury-a')
    await tab(w, 'members')
    await pick(w, B)
    await tab(w, 'treasury')
    expect(h.calls, "B's account was never read").toContain('account:org-b')
    expect(w.text()).not.toContain('did:theprotocol:treasury-a')
    await answer('listings:org-b', listings('BIRCH'))
    await answer('account:org-b', account('did:theprotocol:treasury-b'))
    expect(w.find('.oa-did').text()).toBe('did:theprotocol:treasury-b')
  })

  it('every organization panel starts over for the picked organization (none keeps what it read for A)', async () => {
    const w = await mounted()
    // the tabs stay mounted (v-show): a panel that read once on mount (OrgOwnershipCard, OrgRoomCard) kept A's answer
    const panels = ['OrgSetupChecklist', 'OrgOwnershipCard', 'OrgRoomCard', 'OrgPolicySettings', 'OrgRoomModeration', 'OrgActivityRollup']
    const before = panels.map((name) => w.findComponent({ name }))
    before.forEach((c, i) => expect(c.exists(), `${panels[i]} is on the page`).toBe(true))
    const vms = before.map((c) => c.vm)
    await pick(w, B)
    panels.forEach((name, i) => {
      const now = w.findComponent({ name })
      expect(now.vm, `${name} is still the instance that read for A`).not.toBe(vms[i])
      expect(now.props('orgId')).toBe('org-b')
    })
  })
})
