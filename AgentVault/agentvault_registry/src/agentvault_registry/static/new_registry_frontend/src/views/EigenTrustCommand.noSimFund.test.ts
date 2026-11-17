import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * V0664 (order gwo_40f159d2a945a7070df20933, room seq 3638): bulk funding of the simulation's agents is
 * removed, as its funding preview was in V0663. POST /admin/simulation/fund ran the retired network's host script through
 * a docker socket the new registries do not have, and GET /admin/simulation/fund-status read that script's progress
 * file. Gone from the console: the overview's Top up field and FUND button, the agents tab's Top up field, Top Up All
 * and Depleted Only, the funding result, the progress log and the bulk-fund confirm, and both calls in the simulation
 * API. Kept: the issue bar, opened from its own button, with its confirm (the console's own confirmed issuing).
 * Red on b7ca684e9: the controls, the confirm and both calls are there.
 */
const h = vi.hoisted(() => ({ getStatus: vi.fn(), mintTokens: vi.fn() }))
vi.mock('@/services/api/simulation', () => ({
  simulationApi: {
    getStatus: h.getStatus,
    getMetrics: vi.fn().mockResolvedValue(null), getDeadmanStatus: vi.fn().mockResolvedValue(null),
    getAgents: vi.fn().mockResolvedValue({ registries: [] }), getTopology: vi.fn().mockResolvedValue({ registries: [], edges: [] }),
    getLogs: vi.fn().mockResolvedValue({ lines: [] }), getSupplyAudit: vi.fn().mockResolvedValue({}),
    start: vi.fn(), stop: vi.fn(), mintTokens: h.mintTokens,
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

async function mounted() {
  h.getStatus.mockResolvedValue({ running: false, instances: 0, container_ids: [], uptime_seconds: 0, params: {} })
  const w = mount(EigenTrustCommand, opts)
  await flushPromises()
  return w
}

async function agentsTab() {
  const w = await mounted()
  const tab = w.findAll('button.et-tab').find((b) => b.text() && /agent/i.test(b.text()))!
  await tab.trigger('click')
  await flushPromises()
  return w
}

const named = (w: Awaited<ReturnType<typeof mounted>>, re: RegExp) => w.findAll('button').filter((b) => re.test(b.text()))

describe('the simulation console funds no agents in bulk', () => {
  it('the overview has no Top up field and no FUND button', async () => {
    const w = await mounted()
    expect(w.find('#et-fund-target').exists()).toBe(false)
    expect(named(w, /^\s*(FUND|Funding\.\.\.)\s*$/)).toHaveLength(0)
  })

  it('the agents tab has no Top Up All, no Depleted Only and no progress log; the issue bar still opens', async () => {
    const w = await agentsTab()
    expect(named(w, /Top Up All|Depleted Only/)).toHaveLength(0)
    expect(w.find('.et-fund-inline').exists()).toBe(false)
    expect(w.find('.et-fund-log').exists()).toBe(false)
    await w.find('[data-testid="et-mint-toggle"]').trigger('click')
    expect(w.find('.et-mint-bar').exists()).toBe(true)
  })

  it('no bulk-fund confirm is left, and the issue confirm stays', async () => {
    const w = await agentsTab()
    const titles = w.findAllComponents({ name: 'ConfirmActionModal' }).map((m) => m.props('title'))
    expect(titles).not.toContain('// BULK FUND AGENTS')
    expect(titles).toContain('// ISSUE AVT UNITS')
  })

  it('the simulation API no longer calls either route', async () => {
    const fs = await import('node:fs')
    const path = await import('node:path')
    const src = fs.readFileSync(path.resolve(__dirname, '../services/api/simulation.ts'), 'utf8')
    expect(src).not.toMatch(/\/simulation\/fund(?!ing)/)
    expect(src).not.toMatch(/fundAgents|getFundStatus/)
  })
})
