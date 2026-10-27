/**
 * §BAFIN (agentvault2-d6, 2026-10-23, agentvault2-56's finding on EU's public /#/architecture): the page called its third
 * layer "TOKEN ECONOMY" and drew its locked units as "Staked" in the hero ("1,750 STAKED" on EU), on registries that run
 * no staking (STAKING_ENABLED=false on EU and ASIA, the BaFin letter's posture). The layer is "Units & Fees", as the sibling
 * pages name it, and the figure is units "In locks", as the page's own footer and the layer's detail already said. The
 * staking rate stays where it was: shown only once the registry has said rewards are on (B.5.5, fail-closed).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'

const cfg = ref<Record<string, unknown>>({})
vi.mock('@/composables/useRegistryConfig', () => ({
  useRegistryConfig: () => ({
    config: cfg, loaded: ref(true), readOk: ref(true), readFailed: computed(() => false), reload: () => {},
    localCurrency: ref('ECU'), trustDomain: ref(''),
  }),
}))

import NetworkArchitecture from './NetworkArchitecture.vue'

const stubs = { RouterLink: { template: '<a><slot /></a>' }, 'router-link': { template: '<a><slot /></a>' } }
const ok = (body: unknown) => ({ ok: true, status: 200, json: async () => body })
const down = { ok: false, status: 503, json: async () => ({}) }
function reads(byPath: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = String(url).replace(window.location.origin, '')
    return path in byPath ? byPath[path] : down
  }))
}
async function page() {
  const w = mount(NetworkArchitecture, { global: { stubs } })
  for (let i = 0; i < 6; i++) await flushPromises()
  return w
}
const stakingStats = { '/api/v1/staking/global-stats': ok({ totalValueLocked: 1750, averageApy: 12.5, totalStakers: 3 }) }

afterEach(() => { vi.unstubAllGlobals() })

describe('/architecture speaks of units and locks, not of a token economy or staking', () => {
  it('on a registry with staking and its rewards off: Units & Fees, In locks, no Staked, no APY', async () => {
    cfg.value = { registry_name: 'eu', governance_weight_mode: 'member', staking_enabled: false, staking_rewards_enabled: false }
    reads(stakingStats)
    const w = await page()
    const text = w.text()
    expect(text, 'the layer still called a token economy').not.toMatch(/token economy/i)
    expect(text, 'a figure still labelled Staked').not.toMatch(/\bstaked\b/i)
    expect(text).toContain('UNITS & FEES')
    expect(text).toContain('In locks')
    expect(text, 'the locked units are still shown').toMatch(/1[,.]?750/)
    expect(text, 'a payout rate shown while payouts are off').not.toMatch(/payout rate|\bAPY\b/i)
  })

  it('the control: with payouts on, the payout rate shows (the test sees the gate)', async () => {
    cfg.value = { registry_name: 'sbx-alpha', governance_weight_mode: 'lock', staking_enabled: true, staking_rewards_enabled: true }
    reads(stakingStats)
    const w = await page()
    expect(w.text()).toMatch(/payout rate/i)
    expect(w.text(), 'the old word').not.toMatch(/\bAPY\b/)
    expect(w.text()).not.toMatch(/token economy/i)
  })
})
