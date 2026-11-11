/**
 * V0657 (b), orgs v2 in the console:
 *  - OrgMark (items 4, 5): the organization by its logo and name; a local one opens this console's page, a remote one
 *    its home's page apart; an unsafe logo is never loaded;
 *  - OrgAgentRequests (polish 9): an administrator accepts or declines; a member proposes an agent it created;
 *  - OrgPublicFace (items 2, 3): says whether the organization is listed; a logo is a PNG or JPEG of at most 256 KB;
 *  - OrgDirectory (item 6): this registry's listed organizations, then the federation's without them, each with its home;
 *    an index older than the list says so instead of "nobody".
 * RED on e143dd798: none of these components exist.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  listAgentRequests: vi.fn(), decideAgentRequest: vi.fn(), createAgentRequest: vi.fn(), withdrawAgentRequest: vi.fn(),
  uploadLogo: vi.fn(), deleteLogo: vi.fn(), listListedOrganizations: vi.fn(), organizations: vi.fn(),
  config: { loaded: true, directoryUrl: '/api/v1/public/directory' },
}))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: {
    listAgentRequests: h.listAgentRequests, decideAgentRequest: h.decideAgentRequest,
    createAgentRequest: h.createAgentRequest, withdrawAgentRequest: h.withdrawAgentRequest,
    uploadLogo: h.uploadLogo, deleteLogo: h.deleteLogo, listListedOrganizations: h.listListedOrganizations,
  },
}))
vi.mock('@/services/api/directory', () => ({ directoryService: { organizations: h.organizations } }))
vi.mock('@/composables/useRegistryConfig', async () => {
  const { computed } = await import('vue')
  return { useRegistryConfig: () => ({ loaded: computed(() => h.config.loaded),
    directoryUrl: computed(() => h.config.directoryUrl) }) }
})

import OrgMark from '../OrgMark.vue'
import OrgAgentRequests from './OrgAgentRequests.vue'
import OrgPublicFace from './OrgPublicFace.vue'
import OrgDirectory from './OrgDirectory.vue'

const stubs = { RouterLink: { template: '<a data-router :data-to="JSON.stringify(to)"><slot /></a>', props: ['to'] } }
const mark = {
  id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions',
  logo: 'https://eu.example/api/v1/organizations/org-1/logo?v=abc',
  home: { name: 'EU', origin: 'https://eu.example', console: 'https://eu.example/ui' },
  page: 'https://eu.example/ui/#/firms?org=sessions',
}

beforeEach(() => {
  setActivePinia(createPinia())
  Object.values(h).forEach((f: any) => typeof f?.mockReset === 'function' && f.mockReset())
  h.config.loaded = true
  h.config.directoryUrl = '/api/v1/public/directory'
})

describe('OrgMark', () => {
  it('a local organization opens this console\'s page, with its hosted logo', () => {
    const w = mount(OrgMark, { props: { mark, local: true }, global: { stubs } })
    const a = w.find('[data-testid="org-mark"]')
    expect(a.text()).toContain('TheProtocol Sessions')
    expect(a.attributes('data-to')).toContain('"org":"sessions"')
    expect(w.find('img').attributes('src')).toBe(mark.logo)
  })

  it('a remote one opens its home\'s page apart, and an unsafe logo is never loaded', () => {
    const w = mount(OrgMark, { props: { mark: { ...mark, logo: 'https://tracker.example/x.png' } }, global: { stubs } })
    const a = w.find('a[data-testid="org-mark"]')
    expect(a.attributes('href')).toBe(mark.page)
    expect(a.attributes('target')).toBe('_blank')
    expect(a.attributes('rel')).toContain('noopener')
    expect(w.find('img').exists()).toBe(false)
  })

  it('a mark from another registry names its home visibly, beside the name (session-lead, room seq 1608)', () => {
    // organizations are local: a peer may list one with our name and logo, and the home tells the two apart
    const foreign = mount(OrgMark, { props: { mark, local: false }, global: { stubs } })
    expect(foreign.find('[data-testid="org-mark-home"]').text()).toBe('EU')
    expect(foreign.find('[data-testid="org-mark"]').text()).toContain('TheProtocol Sessions')
    const synced = mount(OrgMark, { props: { mark, local: false, homeName: 'ASIA' }, global: { stubs } })
    expect(synced.find('[data-testid="org-mark-home"]').text(), 'the registry this console synced it from').toBe('ASIA')
    const placeholder = mount(OrgMark, { props: { mark, local: false, homeName: 'Federated' }, global: { stubs } })
    expect(placeholder.find('[data-testid="org-mark-home"]').text()).toBe('EU')
    const local = mount(OrgMark, { props: { mark, local: true }, global: { stubs } })
    expect(local.find('[data-testid="org-mark-home"]').exists(), 'an organization of this registry needs no home').toBe(false)
  })

  it('renders nothing without a mark', () => {
    expect(mount(OrgMark, { props: { mark: null }, global: { stubs } }).find('[data-testid="org-mark"]').exists()).toBe(false)
  })
})

describe('OrgAgentRequests', () => {
  const req = { id: 'oar_1', organization_id: 'org-1', agent_did: 'did:theprotocol:eu:agent-1', agent_name: 'session-docs',
    requested_by_kind: 'agent', requested_by_ref: 'did:theprotocol:eu:agent-1', status: 'pending', note: 'I write the docs' }

  it('an administrator accepts a request and the agent joins', async () => {
    h.listAgentRequests.mockResolvedValue({ items: [req], can_decide: true })
    h.decideAgentRequest.mockResolvedValue({ id: 'oar_1', status: 'accepted' })
    const w = mount(OrgAgentRequests, { props: { orgId: 'org-1', myAgents: [] } })
    await flushPromises()
    expect(w.find('[data-testid="org-agent-request"]').text()).toContain('session-docs')
    expect(w.text()).toContain('the agent asked')
    h.listAgentRequests.mockResolvedValue({ items: [], can_decide: true })
    await w.find('[data-testid="org-agent-request-accept"]').trigger('click')
    await flushPromises()
    expect(h.decideAgentRequest).toHaveBeenCalledWith('org-1', 'oar_1', 'accept')
    expect(w.emitted('joined')![0]).toEqual(['did:theprotocol:eu:agent-1'])
  })

  it('a member proposes an agent it created, and withdraws its own request', async () => {
    h.listAgentRequests.mockResolvedValue({ items: [], can_decide: false })
    h.createAgentRequest.mockResolvedValue({ id: 'oar_2', status: 'pending' })
    const w = mount(OrgAgentRequests, { props: { orgId: 'org-1', myAgents: [{ did: 'did:x:mine', name: 'Mine' }] } })
    await flushPromises()
    await w.find('[data-testid="org-agent-propose-pick"]').setValue('did:x:mine')
    await w.find('[data-testid="org-agent-propose-note"]').setValue('It runs our CI')
    await w.find('[data-testid="org-agent-propose"]').trigger('submit')
    await flushPromises()
    expect(h.createAgentRequest).toHaveBeenCalledWith('org-1', { agent_did: 'did:x:mine', note: 'It runs our CI' })

    h.listAgentRequests.mockResolvedValue({ items: [{ ...req, id: 'oar_3', requested_by_kind: 'developer' }], can_decide: false })
    h.withdrawAgentRequest.mockResolvedValue({ id: 'oar_3', status: 'withdrawn' })
    await (w.vm as any).load()
    await flushPromises()
    expect(w.find('[data-testid="org-agent-request-accept"]').exists(), 'a member decides nothing').toBe(false)
    await w.find('[data-testid="org-agent-request-withdraw"]').trigger('click')
    await flushPromises()
    expect(h.withdrawAgentRequest).toHaveBeenCalledWith('org-1', 'oar_3')
  })
})

describe('OrgPublicFace', () => {
  it('says whether the organization is listed', () => {
    expect(mount(OrgPublicFace, { props: { orgId: 'org-1', listed: true } }).find('[data-testid="org-public-face-state"]').text())
      .toContain('Listed')
    expect(mount(OrgPublicFace, { props: { orgId: 'org-1', listed: false } }).find('[data-testid="org-public-face-state"]').text())
      .toContain('Not listed')
  })

  it('uploads a PNG or JPEG of at most 256 KB, refusing others before sending', async () => {
    h.uploadLogo.mockResolvedValue({ logo: '/api/v1/organizations/org-1/logo?v=1' })
    const w = mount(OrgPublicFace, { props: { orgId: 'org-1', canEdit: true } })
    const input = w.find('[data-testid="org-logo-input"]')
    const pick = async (file: File) => {
      Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
      await input.trigger('change')
      await flushPromises()
    }
    await pick(new File([new Uint8Array(300 * 1024)], 'big.png', { type: 'image/png' }))
    expect(w.find('[data-testid="org-logo-error"]').text()).toContain('256 KB')
    await pick(new File(['<svg/>'], 'x.svg', { type: 'image/svg+xml' }))
    expect(w.find('[data-testid="org-logo-error"]').text()).toContain('PNG')
    expect(h.uploadLogo).not.toHaveBeenCalled()
    await pick(new File([new Uint8Array(10)], 'ok.png', { type: 'image/png' }))
    expect(h.uploadLogo).toHaveBeenCalledTimes(1)
    expect(w.emitted('changed')).toBeTruthy()
  })
})

describe('OrgDirectory', () => {
  const local = { id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions', description: 'We ship',
    website: 'https://example.org', logo: 'https://eu.example/api/v1/organizations/org-1/logo?v=1', member_count: 3,
    agent_count: 7, settled_work: 2 }
  const home = { name: 'EU', origin: 'https://eu.example', console: 'https://eu.example/ui' }

  it('lists this registry\'s organizations first, then the federation\'s without them', async () => {
    h.listListedOrganizations.mockResolvedValue({ organizations: [local], total: 1, home })
    h.organizations.mockResolvedValue({ supported: true, total: 2, edges: [
      { ...local, memberCount: 3, agentCount: 7, settledWork: 2, source: 'EU', home, page: null },
      { id: 'org-9', slug: 'tokyo-labs', name: 'Tokyo Labs', description: null, website: null, page: 'https://asia.example/ui/#/firms?org=tokyo-labs',
        logo: 'https://asia.example/api/v1/organizations/org-9/logo?v=2', memberCount: 1, agentCount: 2, settledWork: 0,
        source: 'ASIA', home: { name: 'ASIA', origin: 'https://asia.example', console: 'https://asia.example/ui' } },
    ] })
    const w = mount(OrgDirectory, { props: { highlight: 'sessions' } })
    await flushPromises()
    const mine = w.findAll('[data-testid="org-directory-local"]')
    expect(mine).toHaveLength(1)
    expect(mine[0].classes()).toContain('odir__card--on')
    expect(mine[0].text()).toContain('3 members · 7 agents · 2 jobs settled')
    const fed = w.findAll('[data-testid="org-directory-fed"]')
    expect(fed.map((f) => f.attributes('data-slug'))).toEqual(['tokyo-labs'])
    expect(fed[0].text()).toContain('ASIA')
    expect(fed[0].find('img').attributes('src')).toBe('https://asia.example/api/v1/organizations/org-9/logo?v=2')
    expect(h.organizations).toHaveBeenCalledWith('/api/v1/public/directory', 200)
  })

  it('an older index says it does not list organizations, and no index says so too', async () => {
    h.listListedOrganizations.mockResolvedValue({ organizations: [], total: 0, home })
    h.organizations.mockResolvedValue({ supported: false, total: 0, edges: [] })
    let w = mount(OrgDirectory)
    await flushPromises()
    expect(w.find('[data-testid="org-directory-fed-unsupported"]').exists()).toBe(true)
    expect(w.find('[data-testid="org-directory-local-empty"]').exists()).toBe(true)
    h.config.directoryUrl = ''
    w = mount(OrgDirectory)
    await flushPromises()
    expect(w.find('[data-testid="org-directory-fed-off"]').exists()).toBe(true)
  })
})
