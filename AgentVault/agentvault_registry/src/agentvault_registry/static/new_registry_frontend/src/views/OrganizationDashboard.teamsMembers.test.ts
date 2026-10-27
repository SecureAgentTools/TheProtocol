/**
 * §FESUITE (V0577): the org dashboard's Teams and Members tabs read through the organizations store, whose fetchTeams and
 * fetchMembers turned a failed read into [] without a word. The dashboard then said "no teams" / "no members" with counts
 * of 0, and, the viewer's role being read off the members, an owner saw the organization as a stranger would: no role
 * badge and every owner control gone. Each tab now says its read failed (Try again), an unread list has no count, and
 * the role badge says the role is unread. The real store, the registry answered per test.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h as render, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const ORG = { id: 'o1', name: 'Halden Analytics', slug: 'halden', description: '', website: '' }
const OWNER = { id: 'm1', developer_id: 7, role: 'owner', email: 'owner@halden.example', developer_name: 'Owner' }
const h = vi.hoisted(() => ({ listTeams: vi.fn(), listMembers: vi.fn(), svc: {} as Record<string, any> }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 7, email: 'owner@halden.example' }, token: 'dev.jwt', isAuthenticated: true }),
}))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [{ did: 'did:theprotocol:a1' }], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showSuccess: vi.fn(), showError: vi.fn(), showWarning: vi.fn(), showInfo: vi.fn() }) }))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: new Proxy({}, {
    get: (_t, k: string) => (k === 'listOrganizations' ? async () => [ORG]
      : k === 'listTeams' ? h.listTeams
      : k === 'listMembers' ? h.listMembers
      : (h.svc[k] ??= vi.fn(async () => ({ items: [], agents: [], events: [], proposals: [] })))),
  }),
}))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: new Proxy({}, { get: () => vi.fn(async () => null) }) }))
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

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')

async function dashboard() {
  const w = shallowMount(OrganizationDashboard, { global: { stubs: { ReadFailedNotice: false, Icon: true } } })
  for (let i = 0; i < 3; i++) await flushPromises()
  return w
}
const tabCount = (w: any, id: string) => w.find(`[data-tour="org-tab-${id}"] .tab-count`)

describe("the org dashboard when its teams and members reads fail", () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.listTeams.mockReset(); h.listMembers.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('says each read failed, counts nothing, and calls the role unread instead of hiding it', async () => {
    h.listTeams.mockRejectedValue(noAnswer())
    h.listMembers.mockRejectedValue(noAnswer())
    const w = await dashboard()
    expect(tabCount(w, 'teams').exists(), 'counted 0 teams over a failed read').toBe(false)
    expect(tabCount(w, 'members').exists(), 'counted 0 members over a failed read').toBe(false)
    expect(w.find('[data-testid="org-role-unread"]').exists(), 'the owner lost the role without a word').toBe(true)
    expect(w.find('[data-testid="org-teams-failed"]').exists()).toBe(true)
    await w.find('[data-tour="org-tab-members"]').trigger('click')
    const notice = w.find('[data-testid="org-members-failed"]')
    expect(notice.exists()).toBe(true)

    h.listMembers.mockResolvedValue([OWNER])
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="org-members-failed"]').exists()).toBe(false)
    expect(w.find('[data-testid="org-role-unread"]').exists()).toBe(false)
    expect(w.find('.role-badge').text()).toBe('OWNER')
  })

  it('answered reads count as before', async () => {
    h.listTeams.mockResolvedValue([])
    h.listMembers.mockResolvedValue([OWNER])
    const w = await dashboard()
    expect(tabCount(w, 'teams').text()).toBe('0')
    expect(tabCount(w, 'members').text()).toBe('1')
    expect(w.find('.role-badge').text()).toBe('OWNER')
  })
})
