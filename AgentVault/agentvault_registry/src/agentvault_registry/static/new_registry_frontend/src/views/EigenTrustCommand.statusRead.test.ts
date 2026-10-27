import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the simulation console (EigenTrust Command) swallowed its status read and
 * `running` defaults to false, so a failed read said Idle / Stopped / STOPPED with START pressable, a second simulation
 * one press away from a running one (a running simulation that overloads the registry is exactly when the read fails),
 * and the 5 s poll, which runs only while a simulation runs, never asked again. The status now reads "—" until a read
 * answers, START waits for one, and the failure is said with Try again. An answered status keeps its words.
 */
const h = vi.hoisted(() => ({ getStatus: vi.fn() }))
vi.mock('@/services/api/simulation', () => ({
  simulationApi: {
    getStatus: h.getStatus,
    getMetrics: vi.fn().mockResolvedValue(null), getDeadmanStatus: vi.fn().mockResolvedValue(null),
    getAgents: vi.fn().mockResolvedValue({ registries: [] }), getTopology: vi.fn().mockResolvedValue({ registries: [], edges: [] }),
    getLogs: vi.fn().mockResolvedValue({ lines: [] }), getSupplyAudit: vi.fn().mockResolvedValue({}),
    getFundStatus: vi.fn().mockResolvedValue({ lines: [] }), start: vi.fn(), stop: vi.fn(), fundAgents: vi.fn(),
    fundingPreview: vi.fn(), mintTokens: vi.fn(),
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
const failure = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })
const startButton = (w: ReturnType<typeof mount>) => w.findAll('button.et-btn-green').find((b) => /START/.test(b.text()))!

describe('the simulation console says what its status read answered', () => {
  beforeEach(() => { h.getStatus.mockReset() })

  it('a failed status read: no STOPPED, START waits, and Try again reads it (a running simulation shows)', async () => {
    h.getStatus.mockRejectedValueOnce(failure())
    const w = mount(EigenTrustCommand, opts)
    await flushPromises()
    expect(w.find('.et-stat-value').text()).not.toMatch(/STOPPED|ACTIVE/)
    expect(w.text()).not.toContain('Stopped')
    expect(startButton(w).attributes('disabled'), 'START waits for an answered status').toBeDefined()
    expect(w.find('[data-testid="et-status-unread"]').exists()).toBe(true)
    h.getStatus.mockResolvedValueOnce({ running: true, instances: 1, container_ids: ['c1'], uptime_seconds: 60, params: {} })
    await w.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('.et-stat-value').text()).toContain('ACTIVE')
    expect(startButton(w).attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="et-status-unread"]').exists()).toBe(false)
    w.unmount()
  })

  it('an answered idle status: STOPPED, and START can be pressed', async () => {
    h.getStatus.mockResolvedValueOnce({ running: false, instances: 0, container_ids: [], uptime_seconds: 0, params: {} })
    const w = mount(EigenTrustCommand, opts)
    await flushPromises()
    expect(w.find('.et-stat-value').text()).toContain('STOPPED')
    expect(startButton(w).attributes('disabled')).toBeUndefined()
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })
})
