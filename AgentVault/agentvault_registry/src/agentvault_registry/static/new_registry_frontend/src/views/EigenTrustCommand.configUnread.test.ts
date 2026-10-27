import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-09): the simulation console (EigenTrust Command) took a registry config that did not answer for
 * "on" (only an explicit simulation_enabled false is off), so a page opened while the registry could not answer polled
 * /admin/simulation rails that answer 503 where the console is off (sweeps/recovery on V0587, the shared admin). It now
 * starts nothing until a config read answered, says so, and starts once one does (off: the AGORA panels only).
 */
const h = vi.hoisted(() => ({ getStatus: vi.fn(), getMetrics: vi.fn(), readCb: null as null | ((c: any) => void) }))
vi.mock('@/services/api/simulation', () => ({
  simulationApi: {
    getStatus: h.getStatus, getMetrics: h.getMetrics, getDeadmanStatus: vi.fn().mockResolvedValue(null),
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
const cfgState = vi.hoisted(() => ({ ok: false }))
vi.mock('@/composables/useRegistryConfig', async () => {
  const { ref, computed } = await import('vue')
  const ok = ref(false)
  return {
    useRegistryConfig: () => {
      ok.value = cfgState.ok
      return { simulationEnabled: computed(() => true), readOk: computed(() => ok.value), readFailed: computed(() => !ok.value) }
    },
    // a failed read answers the empty config (every flag at its default), as the composable does
    loadRegistryConfig: async () => ({}),
    onRegistryConfigRead: (cb: (c: any) => void) => { h.readCb = cb; return () => { h.readCb = null } },
    __setOk: (v: boolean) => { ok.value = v },
  }
})
vi.mock('@/composables/useCurrency', async () => {
  const { ref } = await import('vue')
  return { useCurrency: () => ({ localCurrency: ref('ECU'), currencyForItem: () => 'ECU' }) }
})

import EigenTrustCommand from './EigenTrustCommand.vue'
import * as cfgMod from '@/composables/useRegistryConfig'

const opts = { global: { stubs: { Icon: true, EigenTrustTopology: true, ConfirmActionModal: true, teleport: true } } }
const idle = { running: false, instances: 0, container_ids: [], uptime_seconds: 0, params: {} }

describe('the simulation console before its registry config answered', () => {
  beforeEach(() => {
    h.getStatus.mockReset(); h.getStatus.mockResolvedValue(idle)
    h.getMetrics.mockReset(); h.getMetrics.mockResolvedValue(null)
    h.readCb = null
    cfgState.ok = false
  })

  it('starts nothing over an unread config and says so (it polled the simulation rails as if the console were on)', async () => {
    const w = mount(EigenTrustCommand, opts)
    await flushPromises()
    expect(h.getStatus, 'a status read over an unread config').not.toHaveBeenCalled()
    expect(h.getMetrics, 'a telemetry poll over an unread config').not.toHaveBeenCalled()
    expect(w.find('[data-testid="et-config-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('starts the console once a read answers that it is on', async () => {
    const w = mount(EigenTrustCommand, opts)
    await flushPromises()
    ;(cfgMod as any).__setOk(true)
    h.readCb?.({ simulation_enabled: true })
    await flushPromises()
    expect(h.getStatus).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('starts no simulation read once a read answers that it is off', async () => {
    const w = mount(EigenTrustCommand, opts)
    await flushPromises()
    ;(cfgMod as any).__setOk(true)
    h.readCb?.({ simulation_enabled: false })
    await flushPromises()
    expect(h.getStatus).not.toHaveBeenCalled()
    expect(h.getMetrics).not.toHaveBeenCalled()
    w.unmount()
  })
})
