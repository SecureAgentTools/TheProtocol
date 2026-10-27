/**
 * §FESUITE (V0577): the org dashboard's Treasury tab opens with the organization's own money account
 * (getOrgTreasuryAccount). A failed read became null, so the section said badge "none", "This organization has no money
 * account yet." and, to the owner, "Create treasury account" over an account that may exist; and the "none" badge also
 * showed while the read was in flight. It now says the read failed (Try again), and "none" only once the read answered.
 * The AGORA listings roll-up on the same tab (exchangeService.orgTreasury), which the Governance tab also reads, said "No
 * listings yet…" on both tabs over a failed read; it now says the read failed too.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h as render, reactive, ref } from 'vue'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getOrgTreasuryAccount: vi.fn(), orgTreasury: vi.fn(), svc: {} as Record<string, any> }))
const ORG = { id: 'o1', name: 'Halden Analytics', slug: 'halden', description: '', website: '' }
vi.mock('@/stores/organizations', () => ({
  useOrganizationStore: () => reactive({
    currentOrganization: ORG, organizations: [ORG], teams: [], members: [], isLoading: false, isLoadingTeams: false,
    isLoadingMembers: false, currentUserRole: 'owner', currentUserId: 7, canManageOrganization: true, canManageTeams: true,
    canInviteMembers: true, listRead: true, listFailed: false,
    fetchOrganizations: async () => {}, selectOrganization: async () => {}, fetchMembers: async () => {},
  }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, token: 'dev.jwt', isAuthenticated: true }) }))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [{ did: 'did:theprotocol:a1' }], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showWarning: vi.fn(), showInfo: vi.fn() }) }))
// every other read answers empty; the account read is the one under test
vi.mock('@/services/api/organizationService', () => ({
  organizationService: new Proxy({}, {
    get: (_t, k: string) => (k === 'getOrgTreasuryAccount' ? h.getOrgTreasuryAccount
      : (h.svc[k] ??= vi.fn(async () => ({ items: [], agents: [], events: [], proposals: [] })))),
  }),
}))
vi.mock('@/services/api/exchangeService', () => ({
  exchangeService: new Proxy({}, { get: (_t, k: string) => (k === 'orgTreasury' ? h.orgTreasury : vi.fn(async () => null)) }),
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

import OrganizationDashboard from './OrganizationDashboard.vue'

async function treasuryTab() {
  const w = shallowMount(OrganizationDashboard, { global: { stubs: { ReadFailedNotice: false, Icon: true } } })
  await flushPromises()
  await w.find('[data-tour="org-tab-treasury"]').trigger('click')
  await flushPromises()
  return w
}

describe("the org Treasury tab when its reads fail", () => {
  beforeEach(() => {
    h.getOrgTreasuryAccount.mockReset()
    h.orgTreasury.mockReset()
    h.orgTreasury.mockResolvedValue({ listing_count: 0, listings: [], currency: 'ECU' })
  })

  it('says the read failed, never "no money account yet" or "Create treasury account", and reads again', async () => {
    h.getOrgTreasuryAccount.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await treasuryTab()
    expect(w.text()).not.toContain('This organization has no money account yet.')
    expect(w.find('[data-tour="org-treasury-create"]').exists(), 'offered to create an account over a failed read').toBe(false)
    expect(w.find('.oa-badge--none').exists(), 'badged the account "none" over a failed read').toBe(false)
    const notice = w.find('[data-testid="org-account-failed"]')
    expect(notice.exists()).toBe(true)

    h.getOrgTreasuryAccount.mockResolvedValue({ treasury_agent_did: null, source: null, balance: null, exists: false })
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="org-account-failed"]').exists()).toBe(false)
    expect(w.text()).toContain('This organization has no money account yet.')
    expect(w.find('.oa-badge--none').exists()).toBe(true)
  })

  it('a failed listings read is not "No listings yet" on the Treasury or the Governance tab', async () => {
    h.getOrgTreasuryAccount.mockResolvedValue({ treasury_agent_did: null, source: null, balance: null, exists: false })
    h.orgTreasury.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await treasuryTab()
    expect(w.text()).not.toContain('No listings yet, the treasury appears')
    expect(w.find('[data-testid="org-treasury-failed"]').exists()).toBe(true)
    await w.find('[data-tour="org-tab-governance"]').trigger('click')
    await flushPromises()
    expect(w.text()).not.toContain('No listings yet, governance opens')
    expect(w.find('[data-testid="org-gov-listings-failed"]').exists()).toBe(true)
  })

  it('an org with no listings, read, still says "No listings yet"', async () => {
    h.getOrgTreasuryAccount.mockResolvedValue({ treasury_agent_did: null, source: null, balance: null, exists: false })
    const w = await treasuryTab()
    expect(w.text()).toContain('No listings yet, the treasury appears')
  })
})
