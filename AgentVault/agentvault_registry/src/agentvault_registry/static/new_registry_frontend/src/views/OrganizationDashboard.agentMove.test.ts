/**
 * V0658 (s) (the maintainer's report, sessions' room seq 2150): "your identity can only be part of one org. so i just
 * added and removed you by trying to add you into both as owner ... there should be a warning if you want to add an
 * agent to a new org and it would remove it from an organization it already has joined." The Agents tab's Assign sent
 * the assign and the registry moved the agent out of its organization without a word. The registry now refuses that
 * move (409, AGENT_IN_ANOTHER_ORGANIZATION, naming the organization); the tab names the organization the agent leaves,
 * asks, and sends the assign that names it only once confirmed. Cancelling sends nothing; an assignment that moves
 * nothing is as before. RED on 553347408: the refusal ended in an error notice and nothing asked.
 *
 * The review (V0658 (s), blocking 1): both assigns declare the 409 as an answer the tab handles
 * (`expectedStatuses: [409]`), or the API client's global handler raises its red "Error" toast, the registry's sentence,
 * over the question (services/orgMove.wire.test.ts drives that through the real client). RED on 6194c8fa0: neither
 * assign declared it.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h as render, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'

const ORG = { id: 'org-b', name: 'Birch Ledger', slug: 'birch', description: '', website: '' }
const OWNER = { id: 'm1', developer_id: 7, role: 'owner', email: 'owner@birch.example', developer_name: 'Owner' }
const AGENT = 'did:theprotocol:eu:courier-1'
const h = vi.hoisted(() => ({
  post: vi.fn(), get: vi.fn(), showError: vi.fn(), showSuccess: vi.fn(), agentName: 'Courier',
  svc: {} as Record<string, any>,
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: h.post } }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ user: { id: 7, email: 'owner@birch.example' }, token: 'dev.jwt', isAuthenticated: true,
    availableAgents: [] }),
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({ agents: [{ did: AGENT, name: h.agentName }], fetchMyAgents: async () => {} }),
}))
vi.mock('@/stores/ui', () => ({
  useUIStore: () => ({ showSuccess: h.showSuccess, showError: h.showError, showWarning: vi.fn(), showInfo: vi.fn() }),
}))
vi.mock('@/services/api/organizationService', () => ({
  organizationService: new Proxy({}, {
    get: (_t, k: string) => (k === 'listOrganizations' ? async () => [ORG]
      : k === 'listTeams' ? async () => []
      : k === 'listMembers' ? async () => [OWNER]
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

const ASSIGN = `/organizations/${ORG.id}/agents/${AGENT}/assign`
/** the refusal is an answer the tab handles: the client raises no global alarm over the question */
const ASKS = { expectedStatuses: [409] }

function moveRefused(id: string, name: string) {
  return Object.assign(new Error('Request failed with status code 409'), {
    isAxiosError: true,
    response: { status: 409, data: {
      detail: `The agent is in the organization ${name} (id ${id}).`,
      error: { code: 'AGENT_IN_ANOTHER_ORGANIZATION', context: { current_organization: { id, name } } },
    } },
  })
}

async function dashboard(): Promise<VueWrapper> {
  const w = shallowMount(OrganizationDashboard, { global: { stubs: {
    ReadFailedNotice: false, Icon: true, ConfirmActionModal: false, Teleport: true, teleport: true } } })
  for (let i = 0; i < 3; i++) await flushPromises()
  await w.find('[data-tour="org-tab-agents"]').trigger('click')
  await flushPromises()
  return w
}
const assignButton = (w: VueWrapper) => w.find(`[data-testid="org-assignable"][data-did="${AGENT}"] button`)
const dialog = (w: VueWrapper) => w.find('.ca-modal[role="dialog"]')
const confirmButton = (w: VueWrapper) => dialog(w).find('.ca-modal-footer .ca-btn:not(.ca-btn--ghost)')

describe('assigning an agent that is in another organization', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    h.post.mockReset(); h.get.mockReset(); h.showError.mockReset(); h.showSuccess.mockReset()
    h.agentName = 'Courier'
    h.get.mockResolvedValue({ data: { agents: [] } })
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('names the organization it leaves, asks, and moves it only once confirmed', async () => {
    const w = await dashboard()
    expect(assignButton(w).exists(), 'the Assign door is on the tab').toBe(true)
    h.post.mockRejectedValueOnce(moveRefused('org-a', 'Alder Freight'))
    await assignButton(w).trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledTimes(1)
    expect(h.post, 'the assign declares the 409 it answers with a question').toHaveBeenCalledWith(ASSIGN, undefined, ASKS)
    expect(dialog(w).exists(), 'the tab asks before the agent leaves Alder Freight').toBe(true)
    expect(dialog(w).find('[data-testid="org-move-from"]').text()).toBe('Alder Freight')
    expect(dialog(w).text()).toContain('Courier')
    expect(dialog(w).text()).toContain('Birch Ledger')
    expect(h.showError, 'a question, not an error').not.toHaveBeenCalled()

    h.post.mockResolvedValueOnce({ data: { message: 'assigned', team_id: null, left_organization_id: 'org-a' } })
    await confirmButton(w).trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledTimes(2)
    expect(h.post, 'so does the confirmed one (a stale confirmation is asked again)')
      .toHaveBeenLastCalledWith(ASSIGN, { leave_organization_id: 'org-a' }, ASKS)
    expect(h.showSuccess).toHaveBeenCalledTimes(1)
    expect(dialog(w).exists(), 'the question closes once it is answered').toBe(false)
  })

  it('cancelling sends nothing', async () => {
    const w = await dashboard()
    h.post.mockRejectedValueOnce(moveRefused('org-a', 'Alder Freight'))
    await assignButton(w).trigger('click')
    await flushPromises()
    await dialog(w).find('.ca-btn--ghost').trigger('click')
    await flushPromises()
    expect(dialog(w).exists()).toBe(false)
    expect(h.post).toHaveBeenCalledTimes(1)
    expect(h.showSuccess).not.toHaveBeenCalled()
  })

  it('shows the names as text, never as markup', async () => {
    h.agentName = '<b>Courier</b>'
    const w = await dashboard()
    h.post.mockRejectedValueOnce(moveRefused('org-a', '<img src=x onerror=alert(1)>'))
    await assignButton(w).trigger('click')
    await flushPromises()
    expect(dialog(w).find('img').exists()).toBe(false)
    expect(dialog(w).find('b').exists()).toBe(false)
    expect(dialog(w).find('[data-testid="org-move-from"]').text()).toBe('<img src=x onerror=alert(1)>')
    expect(dialog(w).text()).toContain('<b>Courier</b>')
  })

  it('any other refusal is still the tab\'s own error notice (the agent limit is a 409 too)', async () => {
    const w = await dashboard()
    h.post.mockRejectedValueOnce(Object.assign(new Error('Request failed with status code 409'), { isAxiosError: true,
      response: { status: 409, data: { detail: 'Organization agent limit reached (100/100)', error: { code: 'CONFLICT' } } } }))
    await assignButton(w).trigger('click')
    await flushPromises()
    expect(dialog(w).exists(), 'the limit is not a move').toBe(false)
    expect(h.showError).toHaveBeenCalledWith('Assignment Failed', 'Organization agent limit reached (100/100)')
  })

  it('an assignment that moves nothing is as before (control)', async () => {
    const w = await dashboard()
    h.post.mockResolvedValueOnce({ data: { message: 'assigned', team_id: null, left_organization_id: null } })
    await assignButton(w).trigger('click')
    await flushPromises()
    expect(h.post).toHaveBeenCalledWith(ASSIGN, undefined, ASKS)
    expect(dialog(w).exists()).toBe(false)
    expect(h.showSuccess).toHaveBeenCalledTimes(1)
  })
})
