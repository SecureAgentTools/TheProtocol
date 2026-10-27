/**
 * §FESUITE (V0594): the flare shop over reads the registry did not answer. A failed catalog read showed the banner
 * "This lane is open" (prices in a blank currency): the off banner waited for the catalog, the open one only for the
 * attempt. A failed receipts read showed no "Your purchases" at all, as if nothing had been bought (named in the
 * findings at V0592: "the flare shop's receipts read swallows a failure as 'no receipts'"). Each now says the read failed,
 * with Try again; answered reads draw as before.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, reactive } from 'vue'

const h = vi.hoisted(() => ({ getCatalog: vi.fn(), myPurchases: vi.fn() }))
vi.mock('@/services/api/flareShop', () => ({
  flareShopApi: { getCatalog: () => h.getCatalog(), myPurchases: () => h.myPurchases(), purchase: vi.fn() },
}))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: async () => [] } }))
vi.mock('@/services/api/client', () => ({ apiClient: { patch: vi.fn(async () => ({ data: {} })), get: vi.fn() } }))
vi.mock('@/composables/useRegistryConfig', () => ({ loadRegistryConfig: async () => ({ fiat_onramp_enabled: false }) }))
vi.mock('@/composables/useFrames', () => ({ useFrames: () => ({ localCurrency: computed(() => 'ECU') }) }))
vi.mock('@/composables/useI18n', () => ({ useI18n: () => ({ t: (k: string, fb?: unknown) => (typeof fb === 'string' ? fb : k) }) }))
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => reactive({ isAuthenticated: true, user: { name: 'Dev', email: 'dev@example.com', flare_tier: null }, refreshProfile: async () => {} }),
}))

import FlareShop from './FlareShop.vue'

const CATALOG = {
  enabled: true, currency: 'ECU', tiers: [], encirclement_variants: [], encirclement_overlays: [], corner_badges: [],
}
const RECEIPT = { purchase_id: 'p1', tier: 'architect', price: '25', currency: 'ECU', status: 'completed', failure_reason: null, created_at: '2026-10-11T06:00:00Z', completed_at: '2026-10-11T06:00:01Z' }
const gone = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

async function page() {
  const w = mount(FlareShop, {
    global: { stubs: { Icon: true, FlareEncirclement: true, EarnedMarkTiers: true, BaseModal: true, RouterLink: true, 'router-link': true } },
  })
  for (let i = 0; i < 5; i++) await flushPromises()
  return w
}

describe('the flare shop over reads that failed', () => {
  beforeEach(() => { h.getCatalog.mockReset(); h.myPurchases.mockReset() })

  it('a catalog that was not read is not called an open lane', async () => {
    h.getCatalog.mockRejectedValue(gone())
    h.myPurchases.mockResolvedValue({ currency: 'ECU', current_flare_tier: null, purchases: [] })
    const w = await page()
    expect(w.find('[data-testid="fsh-lane-on"]').exists(), 'said "This lane is open" over a catalog it never read').toBe(false)
    expect(w.find('[data-testid="fsh-lane-off"]').exists()).toBe(false)
    expect(w.find('[data-read-failed]').exists(), 'the page says the read failed').toBe(true)
  })

  it('receipts that were not read are not "no purchases"', async () => {
    h.getCatalog.mockResolvedValue(CATALOG)
    h.myPurchases.mockRejectedValue(gone())
    const w = await page()
    const section = w.find('[data-testid="fsh-receipts"]')
    expect(section.exists(), 'the purchases section is there to say the read failed').toBe(true)
    expect(section.find('[data-read-failed]').exists()).toBe(true)
    expect(section.findAll('.fsh-receipt').length).toBe(0)
  })

  it('answered reads draw the open lane and the purchases, no failure', async () => {
    h.getCatalog.mockResolvedValue(CATALOG)
    h.myPurchases.mockResolvedValue({ currency: 'ECU', current_flare_tier: 'architect', purchases: [RECEIPT] })
    const w = await page()
    expect(w.find('[data-testid="fsh-lane-on"]').exists()).toBe(true)
    expect(w.findAll('[data-testid="fsh-receipt-completed"]').length).toBe(1)
    expect(w.find('[data-read-failed]').exists()).toBe(false)
  })
})
