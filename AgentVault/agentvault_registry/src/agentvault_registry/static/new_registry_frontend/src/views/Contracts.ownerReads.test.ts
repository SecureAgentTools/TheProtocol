/**
 * V0658 (q) (order gwo_c3eacb96b7ca74510052c55c), item 2, on the Contracts page's contract rail.
 *
 * On a registry that retired the legacy list (EU, ASIA) the rail is where a v2 contract shows, and it was the ACTING
 * agent's (/contracts/v2/mine on its token): the developer saw none of his other agents' contracts until he selected the
 * right one, and nothing at all with no agent acting. Reading follows ownership: the rail reads /contracts/v2/owned on
 * his own token, every agent and organization he owns, each row naming his agent; acting stays the acting agent's, so a
 * replica's door (accept, deliver, cancel, all signed as the acting agent) opens only on that agent's own row.
 * BASE: the rail asks /contracts/v2/mine, and asks nothing with no agent acting.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

const LEAD = 'did:theprotocol:eu.test:session-lead'
const SHELDON = 'did:theprotocol:eu.test:shadowban-sheldon'
const ASIA_CLIENT = 'did:theprotocol:asia.test:client'

const h = vi.hoisted(() => ({ auth: null as any, v2: {} as Record<string, any> }))
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, path: '/contracts' }), useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('@/composables/useCurrency', async () => {
  const { computed } = await import('vue')
  return { useCurrency: () => ({ localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/stores/contracts', async () => {
  const { reactive } = await import('vue')
  const store = reactive({
    contracts: [], filteredContracts: [], loading: false, loaded: true, error: null, legacyRetired: true,
    statusFilter: 'ALL', drawerOpen: false, activeContract: null,
    stats: { total: 0, proposed: 0, accepted: 0, pendingMerge: 0, completed: 0, totalValue: 0, completedValue: 0,
      successRate: 0, avgPayment: 0 },
    fetchContracts: async () => {}, setStatusFilter: () => {}, setRoleFilter: () => {}, setSearch: () => {},
    clearFilters: () => {}, openDrawer: () => {}, closeDrawer: () => {},
    ctrRef: (c: any) => String(c?.id ?? ''), ctrLabel: (c: any) => String(c?.id ?? ''),
  })
  return { useContractStore: () => store }
})
vi.mock('@/services/api/contractsV2', () => ({
  contractsV2Api: new Proxy({}, { get: (_t, k: string) => (h.v2[k] ??= vi.fn().mockResolvedValue({ items: [] })) }),
}))

import Contracts from './Contracts.vue'

const replica = {
  id: 'ctr_r1', replica: true, home_registry: 'https://asia.example', client_did: ASIA_CLIENT, provider_did: LEAD,
  title: 'Translate the docs', total_amount: '4', currency: 'ACU', status: 'offered',
  my_parties: [{ role: 'provider', agent_did: LEAD, name: 'session-lead', via: 'agent' }],
}
const home = {
  id: 'ctr_h1', client_did: LEAD, provider_did: 'did:theprotocol:eu.test:someone', title: 'Review the cut',
  total_amount: '2', currency: 'ECU', status: 'agreed',
  my_parties: [{ role: 'client', agent_did: LEAD, name: 'session-lead', via: 'agent' }],
}

const stubs = { Icon: true, ReadFailedNotice: true, TemplatesTab: true, CreateContractModal: true,
  AcceptContractModal: true, SubmitWorkModal: true, ApproveCompletionModal: true, MalpracticeModal: true,
  ReplicaContractDoor: { template: '<div data-testid="replica-door-stub" />' } }

function acting(did: string | null) {
  h.auth = { activeAgent: did ? { did, name: did === LEAD ? 'session-lead' : 'Shadowban Sheldon' } : null, token: 'dev-tok' }
}

describe('the contract rail follows ownership', () => {
  beforeEach(() => {
    h.v2 = { mine: vi.fn().mockResolvedValue({ items: [] }), owned: vi.fn().mockResolvedValue({ items: [home, replica] }) }
  })

  it('with another of his agents acting, his agents\' contracts are listed, each naming his agent', async () => {
    acting(SHELDON)
    const w = mount(Contracts, { global: { stubs } })
    await flushPromises()
    expect(h.v2.owned).toHaveBeenCalled()
    expect(h.v2.mine, 'not the acting agent\'s rail').not.toHaveBeenCalled()
    expect(w.find('[data-testid="ctr-home-row"]').text()).toContain('Review the cut')
    expect(w.find('[data-testid="ctr-home-row"]').text()).toContain('session-lead')
    expect(w.find('[data-testid="ctr-replica-row"]').text()).toContain('Translate the docs')
    w.unmount()
  })

  it('with no agent acting, the rail still reads his contracts', async () => {
    acting(null)
    const w = mount(Contracts, { global: { stubs } })
    await flushPromises()
    expect(h.v2.owned).toHaveBeenCalled()
    expect(w.findAll('[data-testid="ctr-home-row"]').length).toBe(1)
    w.unmount()
  })

  it("a replica's door opens on the acting agent's own row only; another agent's row names the one that acts", async () => {
    acting(SHELDON)
    const w = mount(Contracts, { global: { stubs } })
    await flushPromises()
    await w.find(`[data-testid="ctr-replica-open-${replica.id}"]`).trigger('click')
    expect(w.find('[data-testid="replica-door-stub"]').exists(), 'no relay signed as Sheldon for a contract of the lead').toBe(false)
    const note = w.find('[data-testid="ctr-replica-owner"]')
    expect(note.exists()).toBe(true)
    expect(note.text()).toContain('session-lead')
    expect(note.text()).toContain('provider')
    w.unmount()
  })

  it('control: with the party agent acting, its door opens as before', async () => {
    acting(LEAD)
    h.v2.mine = vi.fn().mockResolvedValue({ items: [replica] })     // its own rail on BASE, the owner's here
    const w = mount(Contracts, { global: { stubs } })
    await flushPromises()
    await w.find(`[data-testid="ctr-replica-open-${replica.id}"]`).trigger('click')
    expect(w.find('[data-testid="replica-door-stub"]').exists()).toBe(true)
    expect(w.find('[data-testid="ctr-replica-owner"]').exists()).toBe(false)
    w.unmount()
  })
})
