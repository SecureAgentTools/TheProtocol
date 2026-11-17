import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0663 (order gwo_be8899e9eb589224813ec90a, his yes at room seq 3182): the funding preview is removed. POST
 * /admin/simulation/funding-preview ran the retired network's host script through a docker socket no current registry
 * has, so the Preview button answered "Preview failed" on every frame; it was also the only way to the bar that issues
 * units on the simulation's frames (shown with the preview's panel). The button and its call are gone; the issue bar
 * opens from its own button, one press as before, and keeps its confirm step (session-lead, room seq 3502: only its door
 * moves; a test that the confirm still stands between the press and the issue).
 * Red on b27f2ebaf: the Preview button is there and the issue bar has no button of its own.
 */
const h = vi.hoisted(() => ({ getStatus: vi.fn(), mintTokens: vi.fn() }))
vi.mock('@/services/api/simulation', () => ({
  simulationApi: {
    getStatus: h.getStatus,
    getMetrics: vi.fn().mockResolvedValue(null), getDeadmanStatus: vi.fn().mockResolvedValue(null),
    getAgents: vi.fn().mockResolvedValue({ registries: [] }), getTopology: vi.fn().mockResolvedValue({ registries: [], edges: [] }),
    getLogs: vi.fn().mockResolvedValue({ lines: [] }), getSupplyAudit: vi.fn().mockResolvedValue({}),
    start: vi.fn(), stop: vi.fn(),
    mintTokens: h.mintTokens,
  },
}))
vi.mock('@/services/api/exchangeAdminService', () => ({
  exchangeAdminService: {
    getCampaignPresets: vi.fn().mockRejectedValue(new Error('x')), getCampaignStatus: vi.fn().mockRejectedValue(new Error('x')),
    getDemandDirector: vi.fn().mockRejectedValue(new Error('x')), setDemandDirector: vi.fn(), startCampaign: vi.fn(), stopCampaign: vi.fn(),
  },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn().mockRejectedValue(new Error('x')), post: vi.fn() } }))
vi.mock('@/composables/useRegistryConfig', async () => {
  const { computed } = await import('vue')
  return {
    useRegistryConfig: () => ({ simulationEnabled: computed(() => true), readOk: computed(() => true), readFailed: computed(() => false) }),
    loadRegistryConfig: async () => ({ simulation_enabled: true }),
    onRegistryConfigRead: () => () => {},
  }
})
vi.mock('@/composables/useCurrency', async () => {
  const { ref } = await import('vue')
  return { useCurrency: () => ({ localCurrency: ref('ECU'), currencyForItem: () => 'ECU' }) }
})

import EigenTrustCommand from './EigenTrustCommand.vue'

const opts = { global: { stubs: { Icon: true, EigenTrustTopology: true, ConfirmActionModal: true, teleport: true } } }

async function agentsTab() {
  h.getStatus.mockResolvedValue({ running: false, instances: 0, container_ids: [], uptime_seconds: 0, params: {} })
  const w = mount(EigenTrustCommand, opts)
  await flushPromises()
  const tab = w.findAll('button.et-tab').find((b) => b.text() && /agent/i.test(b.text()))!
  await tab.trigger('click')
  await flushPromises()
  return w
}

describe('the simulation console has no funding preview', () => {
  it('no Preview button; the issue bar opens from its own button', async () => {
    const w = await agentsTab()
    expect(w.findAll('button').filter((b) => /^\s*Preview\s*$/.test(b.text()))).toHaveLength(0)
    expect(w.find('.et-mint-bar').exists()).toBe(false)
    await w.find('[data-testid="et-mint-toggle"]').trigger('click')
    expect(w.find('.et-mint-bar').exists()).toBe(true)
    expect(w.find('.et-preview-grid').exists()).toBe(false)
  })

  it('the confirm still stands between the press and the issue', async () => {
    h.mintTokens.mockReset()
    h.mintTokens.mockResolvedValue({})
    const w = await agentsTab()
    await w.find('[data-testid="et-mint-toggle"]').trigger('click')
    const issueA = w.findAll('.et-mint-bar button').find((b) => /Frame A/.test(b.text()))!
    await issueA.trigger('click')
    await flushPromises()
    expect(h.mintTokens, 'the press alone issues nothing').not.toHaveBeenCalled()
    const confirm = w.findAllComponents({ name: 'ConfirmActionModal' }).find((m) => m.props('title') === '// ISSUE AVT UNITS')!
    expect(confirm.props('show'), 'the press opens the confirm').toBe(true)
    confirm.vm.$emit('confirm')
    await flushPromises()
    expect(h.mintTokens).toHaveBeenCalledTimes(1)
  })

  it('the API module has no funding preview call', async () => {
    const { simulationApi } = await vi.importActual<typeof import('@/services/api/simulation')>('@/services/api/simulation')
    expect('fundingPreview' in simulationApi).toBe(false)
    expect(typeof simulationApi.mintTokens).toBe('function')   // V0664: the bulk funding call went with its route; the control is the issue call
  })
})
