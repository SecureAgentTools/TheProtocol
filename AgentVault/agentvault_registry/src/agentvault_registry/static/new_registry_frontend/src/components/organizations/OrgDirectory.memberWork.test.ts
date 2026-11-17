/**
 * V0658 (v), item 6 on #/firms: an organization of this registry shows its own settled work AS the firm, and, on a line
 * of its own, the settled work its member agents did on their own (GET /organizations/public/listed answers it as
 * `member_work`), never added into the firm's number. Nothing on that line when its agents have none (the line beside
 * it, the firm's own jobs, follows the same rule), and none for an organization of another registry: the federated
 * index does not carry it, and an absent number is not a zero.
 * RED on 553347408 (origin/v0657/cut): the card says "2 jobs settled" for the firm and nothing about its agents.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

const h = vi.hoisted(() => ({
  listListedOrganizations: vi.fn(), organizations: vi.fn(),
  config: { loaded: true, directoryUrl: '/api/v1/public/directory' },
}))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: { listListedOrganizations: h.listListedOrganizations },
}))
vi.mock('@/services/api/directory', () => ({ directoryService: { organizations: h.organizations } }))
vi.mock('@/composables/useRegistryConfig', async () => {
  const { computed } = await import('vue')
  return { useRegistryConfig: () => ({ loaded: computed(() => h.config.loaded), directoryUrl: computed(() => h.config.directoryUrl) }) }
})

import OrgDirectory from './OrgDirectory.vue'

const home = { name: 'EU', origin: 'https://eu.example', console: 'https://eu.example/ui' }
const base = { description: null, website: null, logo: null, page: null, member_count: 1 }

describe("#/firms: a firm's own work and its agents' own work, apart", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.listListedOrganizations.mockReset(); h.organizations.mockReset()
  })

  it('the firm keeps its own count; its agents\' work is a separate, labelled line', async () => {
    h.listListedOrganizations.mockResolvedValue({ home, total: 3, organizations: [
      { ...base, id: 'org-1', slug: 'sessions', name: 'TheProtocol Sessions', agent_count: 6, settled_work: 0,
        member_work: { jobs: 52, commissioned: 3 } },
      { ...base, id: 'org-2', slug: 'reach', name: 'Reach Limited', agent_count: 2, settled_work: 2,
        member_work: { jobs: 0, commissioned: 0 } },
      { ...base, id: 'org-3', slug: 'solo', name: 'Solo Works', agent_count: 1, settled_work: 1, member_work: { jobs: 1, commissioned: 0 } },
    ] })
    h.organizations.mockResolvedValue({ supported: true, total: 1, edges: [
      { id: 'org-9', slug: 'tokyo-labs', name: 'Tokyo Labs', description: null, website: null, page: null, logo: null,
        memberCount: 1, agentCount: 2, settledWork: 4, source: 'ASIA',
        home: { name: 'ASIA', origin: 'https://asia.example', console: 'https://asia.example/ui' } },
    ] })
    const w = mount(OrgDirectory)
    await flushPromises()
    const cards = w.findAll('[data-testid="org-directory-local"]')
    const sessions = cards.find((c) => c.attributes('data-slug') === 'sessions')!
    const reach = cards.find((c) => c.attributes('data-slug') === 'reach')!
    const solo = cards.find((c) => c.attributes('data-slug') === 'solo')!

    const line = sessions.find('[data-testid="org-directory-member-work"]')
    expect(line.exists()).toBe(true)
    expect(line.text()).toBe('By its agents: 52 jobs delivered, 3 commissioned')
    expect(line.attributes('title')).toMatch(/never added/i)
    expect(sessions.find('.odir__meta').text(), 'the firm\'s own count is not the agents\'').not.toContain('52')

    expect(reach.find('.odir__meta').text()).toContain('2 jobs settled as the firm')
    expect(reach.find('[data-testid="org-directory-member-work"]').exists(), 'no line where its agents have none').toBe(false)

    expect(solo.find('[data-testid="org-directory-member-work"]').text()).toBe('By its agents: 1 jobs delivered, 0 commissioned')
    expect(solo.find('.odir__meta').text()).toContain('1 job settled as the firm')

    const fed = w.find('[data-testid="org-directory-fed"]')
    expect(fed.find('[data-testid="org-directory-member-work"]').exists(), 'the index carries no such number').toBe(false)
  })
})
