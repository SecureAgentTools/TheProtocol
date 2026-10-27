/**
 * §FESUITE (V0577): the member CI/CD page (/agents/:did/cicd) read pipelines, versions and deployments through the CI/CD
 * store, which swallowed each failure. Over reads that never answered the page said "No pipelines configured", "No
 * versions yet" and "No deployments found", counted 0 of each, and painted a red "0.0%" success rate. It now says which
 * read failed (with Try again) and counts "—". And an agent never deployed reads a success rate of "—", not a red 0.0%:
 * never-observed is not zero percent. The real store, the registry answered per test.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({
  listPipelines: vi.fn(), listVersions: vi.fn(), listDeployments: vi.fn(), getDeploymentLogs: vi.fn(), listTemplates: vi.fn(),
}))
vi.mock('@/services/api/cicdService', () => ({ cicdService: h }))
vi.mock('@/composables/useToast', () => ({ useToast: () => ({ success: vi.fn(), error: vi.fn(), info: vi.fn(), warning: vi.fn() }) }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { did: 'did:theprotocol:mine' }, query: {} }),
  useRouter: () => ({ push: vi.fn(async () => {}) }),
}))
vi.mock('@/services/api/client', () => ({
  apiClient: { get: vi.fn(async () => ({ data: { name: 'My Agent', creator_developer_id: 7 } })), post: vi.fn() },
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: false, user: { id: 7 } }) }))
vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => null } }))
vi.mock('@/services/api/cicdAdmin', () => ({ cicdAdminService: {} }))

import AgentCICD from './AgentCICD.vue'

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const stubs = { PipelineBuilder: true, CreateVersionModal: true, DeploymentModal: true, DeploymentLogsModal: true, ConfirmActionModal: true }

async function page() {
  const w = mount(AgentCICD, { global: { stubs } })
  for (let i = 0; i < 3; i++) await flushPromises()
  return w
}
/** the first stat row, read by its structure (both versions have it): pipelines, versions, deployments, success rate */
const stats = (w: any) => w.findAll('.cicd-stat-tile .stat-value').slice(0, 4).map((v: any) => v.text().trim())
async function tab(w: any, id: string) { await w.find(`[data-tab="${id}"]`).trigger('click') }

describe('the member CI/CD page when its reads fail', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    for (const f of Object.values(h)) f.mockReset()
    vi.spyOn(console, 'error').mockImplementation(() => {})
  })

  it('counts "—" and says each list could not be read, never "No pipelines/versions/deployments" or a red 0.0%', async () => {
    h.listPipelines.mockRejectedValue(noAnswer())
    h.listVersions.mockRejectedValue(noAnswer())
    h.listDeployments.mockRejectedValue(noAnswer())
    const w = await page()
    expect(stats(w), 'counted 0 (and rated 0.0%) over reads that never answered').toEqual(['—', '—', '—', '—'])

    await tab(w, 'pipelines')
    expect(w.text()).not.toContain('No pipelines configured')
    expect(w.find('[data-testid="cicd-pipelines-failed"]').exists()).toBe(true)
    await tab(w, 'versions')
    expect(w.text()).not.toContain('No versions yet')
    expect(w.find('[data-testid="cicd-versions-failed"]').exists()).toBe(true)
    await tab(w, 'deployments')
    expect(w.text()).not.toContain('No deployments found')
    expect(w.find('[data-testid="cicd-deployments-failed"]').exists()).toBe(true)

    h.listDeployments.mockResolvedValue([])
    await w.find('[data-testid="cicd-deployments-failed"] [data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('No deployments found')
  })

  it('answered lists still say none, and an agent never deployed has no success rate (not a red 0.0%)', async () => {
    h.listPipelines.mockResolvedValue([])
    h.listVersions.mockResolvedValue([])
    h.listDeployments.mockResolvedValue([])
    const w = await page()
    expect(stats(w), 'rated an agent never deployed at 0.0%').toEqual(['0', '0', '0', '—'])
    await tab(w, 'pipelines')
    expect(w.text()).toContain('No pipelines configured')
  })
})
