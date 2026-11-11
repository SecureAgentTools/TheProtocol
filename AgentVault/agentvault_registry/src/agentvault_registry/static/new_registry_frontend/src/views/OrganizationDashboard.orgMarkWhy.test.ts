/**
 * V0658 (r): the organization's page and its settings tell the people who can change it why its mark does not show
 * (the sessions' room seq 2136), and a member sees nothing new.
 *  - on the page (the identity panel) and, on the settings tab, in the settings: one notice at a time (OrgMarkWhy), fed
 *    the organization's listing, hosted logo and old logo address;
 *  - a change made from the notice, the logo panel or the policy form re-reads the organization and updates its public
 *    face IN PLACE: selectOrganization reused the list's cached row, so a new logo or listing never showed, and a new
 *    object would reset the details form's unsaved edits (the watcher on org); the policy form is told the listing
 *    (re-mounting it, as the first cut did, threw away its own unsaved edits);
 *  - a member's page mounts no panel that reads an admin-only route (the authority grants answered 403 on every visit
 *    a member paid the page, which the browser load of this order meets first).
 * RED on v0657/cut: the dashboard mounts no notice, and the logo panel's change re-read nothing.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h as render, reactive, ref } from 'vue'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'

const OLD = 'https://old.example/brand/logo.png'
const HOSTED = '/api/v1/organizations/o1/logo?v=abc123def456'
const h = vi.hoisted(() => ({ getOrganization: vi.fn(), selectOrganization: vi.fn(), store: null as any }))

function storeFor(role: 'owner' | 'admin' | 'member' | 'guest') {
  const org = { id: 'o1', name: 'Halden Analytics', slug: 'halden', description: 'old words', website: '',
    listed: false, logo: null as string | null, logo_url: OLD, settings: {} as Record<string, unknown> }
  return reactive({
    currentOrganization: org as any, organizations: [org] as any[], teams: [], members: [], isLoading: false,
    isLoadingTeams: false, isLoadingMembers: false, currentUserRole: role, currentUserId: 7,
    canManageOrganization: role === 'owner' || role === 'admin', canManageTeams: role === 'owner' || role === 'admin',
    canInviteMembers: role === 'owner' || role === 'admin', listRead: true, listFailed: false,
    fetchOrganizations: async () => {}, fetchMembers: async () => {}, fetchTeams: async () => {},
    selectOrganization: h.selectOrganization,
  })
}
vi.mock('@/stores/organizations', () => ({ useOrganizationStore: () => h.store }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, token: 'dev.jwt', isAuthenticated: true }) }))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [{ did: 'did:theprotocol:a1' }], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showWarning: vi.fn(), showInfo: vi.fn() }) }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: async () => ({ data: { agents: [] } }) } }))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: new Proxy({}, {
    get: (_t, k: string) => (k === 'getOrganization' ? h.getOrganization
      : async () => ({ items: [], agents: [], events: [], proposals: [], approvals: [] })),
  }),
}))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: new Proxy({}, { get: () => async () => null }) }))
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

async function open(role: 'owner' | 'admin' | 'member' | 'guest' = 'owner') {
  h.store = storeFor(role)
  const w = shallowMount(OrganizationDashboard, { global: { stubs: { ReadFailedNotice: false, Icon: true } } })
  await flushPromises()
  return w
}
const notices = (w: VueWrapper) => w.findAllComponents({ name: 'OrgMarkWhy' })
const inIdentity = (n: { element: Element }) => !!n.element.closest('.identity-panel')
async function settingsTab(w: VueWrapper) {
  await w.find('[data-tour="org-tab-settings"]').trigger('click')
  await flushPromises()
}

beforeEach(() => {
  h.getOrganization.mockReset()
  h.selectOrganization.mockReset()
  h.selectOrganization.mockResolvedValue(undefined)
})

describe('the organization\'s page and settings say why its mark does not show', () => {
  it('the owner reads it on the organization\'s page, with the organization\'s facts', async () => {
    const w = await open('owner')
    const found = notices(w)
    expect(found, 'one notice on the page').toHaveLength(1)
    expect(inIdentity(found[0]), 'in the identity panel, at the top of the page').toBe(true)
    expect(found[0].props()).toMatchObject({ orgId: 'o1', listed: false, logo: null, logoUrl: OLD, canFix: true })
    expect(found[0].props('uploadHere'), 'the page\'s notice carries its own upload control').not.toBe(false)
  })

  it('on the settings tab it is in the settings, once, pointing at the logo panel\'s upload', async () => {
    const w = await open('owner')
    await settingsTab(w)
    const found = notices(w)
    expect(found, 'one notice, never two on one screen').toHaveLength(1)
    expect(inIdentity(found[0]), 'not in the identity panel on this tab').toBe(false)
    expect(found[0].props()).toMatchObject({ orgId: 'o1', listed: false, logoUrl: OLD, canFix: true, uploadHere: false })
  })

  it('an admin, who may change the listing and the logo too, reads it as the owner does', async () => {
    const w = await open('admin')
    expect(notices(w)).toHaveLength(1)
    expect(notices(w)[0].props('canFix')).toBe(true)
  })

  it('a member and a guest see nothing new, on the page or in the settings (a guard: nothing showed before either)', async () => {
    for (const role of ['member', 'guest'] as const) {
      const w = await open(role)
      expect(notices(w), `${role} on the page`).toHaveLength(0)
      await settingsTab(w)
      expect(notices(w), `${role} in the settings`).toHaveLength(0)
    }
  })
})

describe('a member\'s page reads nothing an admin alone may read', () => {
  // The review of V0658 (r): the authority tab is offered to owners and admins only, but its body is v-show, so the
  // panel mounted for everyone and asked GET /organizations/{id}/agents/authority (admin only): a 403 and a console
  // error on every member's visit. It mounts for the roles it is for now.
  it('the authority panel mounts for the owner and an admin, never for a member or a guest', async () => {
    for (const role of ['owner', 'admin'] as const) {
      expect((await open(role)).findAllComponents({ name: 'AgentAuthorityPanel' }), role).toHaveLength(1)
    }
    for (const role of ['member', 'guest'] as const) {
      expect((await open(role)).findAllComponents({ name: 'AgentAuthorityPanel' }), role).toHaveLength(0)
    }
  })

  it('the setup guide is told who may manage (it reads nothing for anyone else: OrgSetupChecklist.test.ts)', async () => {
    expect((await open('member')).findComponent({ name: 'OrgSetupChecklist' }).props('canManage')).toBe(false)
    expect((await open('owner')).findComponent({ name: 'OrgSetupChecklist' }).props('canManage')).toBe(true)
  })
})

describe('a change re-reads the organization\'s public face, in place', () => {
  it('listing it from the notice updates the page at once, re-reads it, keeps the unsaved details, and tells the policy form', async () => {
    const w = await open('owner')
    await settingsTab(w)
    const description = w.find('textarea.form-textarea')
    await description.setValue('new words, not saved yet')
    const policyBefore = w.findComponent({ name: 'OrgPolicySettings' }).vm
    const orgBefore = h.store.currentOrganization
    h.getOrganization.mockResolvedValue({ id: 'o1', name: 'Halden Analytics', slug: 'halden', listed: true, logo: null,
      logo_url: OLD, settings: { public_listing: true } })

    notices(w)[0].vm.$emit('changed', { listed: true })
    expect(h.store.currentOrganization.listed, 'the notice\'s own answer shows at once').toBe(true)
    await flushPromises()

    expect(h.getOrganization).toHaveBeenCalledWith('o1')
    expect(h.store.currentOrganization, 'the same row, updated in place').toBe(orgBefore)
    expect(h.store.currentOrganization.settings).toEqual({ public_listing: true })
    expect((w.find('textarea.form-textarea').element as HTMLTextAreaElement).value, 'the details form kept its edits')
      .toBe('new words, not saved yet')
    expect(notices(w)[0].props('listed')).toBe(true)
    // the review of V0658 (r): re-keying the policy form to re-read its switch threw away its unsaved edits; it is the
    // same form now, told the listing
    const policy = w.findComponent({ name: 'OrgPolicySettings' })
    expect(policy.vm, 'the policy form is the same one: its unsaved edits stay').toBe(policyBefore)
    expect(policy.props('listed'), 'and its listing switch is told the listing').toBe(true)
  })

  it('an upload from the notice shows the hosted logo, and drops the old address only if the server did', async () => {
    const w = await open('owner')
    h.getOrganization.mockResolvedValue({ id: 'o1', listed: false, logo: HOSTED, logo_url: OLD, settings: {} })
    notices(w)[0].vm.$emit('changed', { logo: HOSTED })
    expect(h.store.currentOrganization.logo).toBe(HOSTED)
    await flushPromises()
    expect(h.getOrganization).toHaveBeenCalledWith('o1')
    expect(h.store.organizations[0].logo, 'the list\'s row too').toBe(HOSTED)
    expect(notices(w)[0].props('logo')).toBe(HOSTED)
    expect(h.store.currentOrganization.logo_url, 'the server kept the old address: so does the page').toBe(OLD)
    expect(notices(w)[0].props('logoUrl')).toBe(OLD)
  })

  it('an old address the server no longer names leaves the page too', async () => {
    const w = await open('owner')
    h.getOrganization.mockResolvedValue({ id: 'o1', listed: false, logo: HOSTED, logo_url: null, settings: {} })
    notices(w)[0].vm.$emit('changed', { logo: HOSTED })
    await flushPromises()
    expect(h.store.currentOrganization.logo_url).toBeNull()
    expect(h.store.organizations[0].logo_url, 'the list\'s row too').toBeNull()
  })

  it('the logo panel\'s upload and the policy form\'s save re-read it too (selectOrganization re-read nothing)', async () => {
    const w = await open('owner')
    await settingsTab(w)
    h.getOrganization.mockResolvedValue({ id: 'o1', listed: false, logo: HOSTED, logo_url: OLD, settings: {} })
    w.findComponent({ name: 'OrgPublicFace' }).vm.$emit('changed')
    await flushPromises()
    expect(h.getOrganization).toHaveBeenCalledTimes(1)
    expect(h.store.currentOrganization.logo).toBe(HOSTED)
    expect(notices(w)[0].props('logo')).toBe(HOSTED)

    h.getOrganization.mockResolvedValue({ id: 'o1', listed: true, logo: HOSTED, logo_url: OLD,
      settings: { public_listing: true } })
    w.findComponent({ name: 'OrgPolicySettings' }).vm.$emit('saved', { public_listing: true })
    await flushPromises()
    expect(h.getOrganization).toHaveBeenCalledTimes(2)
    expect(h.store.currentOrganization.listed).toBe(true)
  })

  it('a re-read that fails keeps what the change itself answered', async () => {
    const w = await open('owner')
    h.getOrganization.mockRejectedValue(new Error('Network Error'))
    notices(w)[0].vm.$emit('changed', { listed: true })
    await flushPromises()
    expect(h.store.currentOrganization.listed).toBe(true)
    expect(h.store.currentOrganization.logo_url).toBe(OLD)
  })
})
