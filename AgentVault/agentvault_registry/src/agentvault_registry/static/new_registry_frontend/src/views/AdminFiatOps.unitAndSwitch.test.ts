import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * D6-835 and D6-836 (agentvault2-d6, 2026-10-25; his words through agentvault2-69: "sweep for avt again", "make fiat
 * operations inaccessible if deactivated. or best just greyed out so you cant use it"). Fiat Operations said AVT on
 * every frame (the hero "EUR → AVT", the KPIs, the tables, the pricing editor), also on EU, whose unit is ECU and whose
 * on-ramp is off. Now every label names the registry's own unit (a neutral word while the config is unread, never a
 * wrong unit), and the page says when the on-ramp is off; the sidebar greys it out then (requiresFiat).
 * RED control: against V0641's AdminFiatOps.vue the hero says AVT and no notice shows.
 * The registry config and the fiat services are mocked; the view is real.
 */
const h = vi.hoisted(() => ({
  cfg: { local_currency: 'ECU', fiat_onramp_enabled: false } as Record<string, unknown>,
  ok: true,
  stats: {
    window_days: 30, total_eur: '10.00', total_avt: '25000', completed_count: 1, pending_count: 0, failed_count: 0,
    refunded_count: 0, success_rate_pct: '100', anonymous_devs_created: 0, avg_purchase_eur: '10.00',
    status_breakdown: [{ status: 'completed', count: 1 }], daily_revenue: [{ day: '2026-10-01', eur: '10.00', avt: '25000', purchases: 1 }],
    tier_share: [{ tier_label: 'tier_2', count: 1, total_eur: '10.00', total_avt: '25000' }], treasury_consumed_estimate_avt: '25000',
  },
  row: {
    id: 'p1-0000-0000', stripe_session_id: 'cs_test_1', stripe_event_id: null, stripe_payment_intent_id: null,
    developer_id: 7, agent_did: 'did:theprotocol:0001', customer_email: null, amount_eur: '10.00', amount_avt: '25000',
    avt_per_eur_rate: '2500', tier_label: 'tier_2', status: 'completed', failure_reason: null, avt_transfer_tx_id: null,
    anonymous_flow: false, created_at: '2026-10-01T00:00:00Z', completed_at: '2026-10-01T00:00:05Z', refunded_at: null,
  },
}))

vi.mock('@/composables/useRegistryConfig', async () => {
  const { computed } = await import('vue')
  return {
    useRegistryConfig: () => ({
      config: computed(() => (h.ok ? h.cfg : {})),
      readOk: computed(() => h.ok),
      readFailed: computed(() => !h.ok),
      localCurrency: computed(() => (h.ok ? String(h.cfg.local_currency || '') : '')),
    }),
  }
})
vi.mock('@/services/api/fiatOnramp', () => ({
  fiatPricingAdminService: {
    getPricing: vi.fn().mockResolvedValue({ active: null, history: [], fallback_in_use: true }),
    validatePricing: vi.fn(), putPricing: vi.fn(), simulate: vi.fn(),
  },
  fiatOpsAdminService: {
    getStats: vi.fn(async () => h.stats),
    listPurchases: vi.fn(async () => ({ total: 1, limit: 10, offset: 0, rows: [h.row] })),
    getPurchase: vi.fn(async () => ({ purchase: h.row, developer: null, agent: null, stripe_session: null, events: [] })),
    replayPurchase: vi.fn(), resendMagicLink: vi.fn(), refund: vi.fn(),
  },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn().mockResolvedValue({ data: [] }), post: vi.fn() } }))

import AdminFiatOps from './AdminFiatOps.vue'

const opts = { global: { stubs: { Icon: true, FlareBadge: true, Teleport: true, teleport: true } } }
const AVT = /\bAVT\b/

async function page() {
  const w = mount(AdminFiatOps, opts)
  await flushPromises()
  return w
}

describe('Fiat Operations names the registry\'s unit and says when the on-ramp is off', () => {
  beforeEach(() => {
    h.cfg = { local_currency: 'ECU', fiat_onramp_enabled: false }
    h.ok = true
  })

  it('on EU (ECU, the on-ramp off): every label says ECU, none AVT, and the notice shows', async () => {
    const w = await page()
    expect(w.find('h1').text()).toContain('EUR → ECU')
    expect(w.html()).not.toMatch(AVT)
    expect(w.text()).toContain('ECU distributed')
    expect(w.text()).toContain('Starting treasury ECU')
    const notice = w.find('[data-testid="afo-fiat-off"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('FIAT_ONRAMP_ENABLED')
    expect(notice.text()).toContain('refund')
    w.unmount()
  })

  it('on the fiat genesis registry with the switch on (sbx-alpha, SBXA): its unit, no notice', async () => {
    h.cfg = { local_currency: 'SBXA', fiat_onramp_enabled: true }
    const w = await page()
    expect(w.find('h1').text()).toContain('EUR → SBXA')
    expect(w.html()).not.toMatch(AVT)
    expect(w.find('[data-testid="afo-fiat-off"]').exists()).toBe(false)
    w.unmount()
  })

  it('the config unread: a neutral word, never a unit it does not know, and no claim about the switch', async () => {
    h.ok = false
    const w = await page()
    expect(w.find('h1').text()).toContain('EUR → units')
    expect(w.html()).not.toMatch(AVT)
    expect(w.find('[data-testid="afo-fiat-off"]').exists()).toBe(false)
    w.unmount()
  })

  it('the tools stay with the on-ramp off: a completed purchase can still be refunded, and its unit is ECU', async () => {
    const w = await page()
    expect(w.find('[data-testid="afo-fiat-off"]').exists()).toBe(true)
    await w.find('.afo-explorer-row').trigger('click')
    await flushPromises()
    const refund = w.findAll('.afo-detail-actions button').find((b) => b.text().includes('Refund'))
    expect(refund, 'the detail strip\'s refund button').toBeDefined()
    expect(refund!.attributes('disabled')).toBeUndefined()
    expect(w.find('.afo-detail').text()).toContain('25,000 ECU')
    await refund!.trigger('click')
    expect(w.html()).toContain('ECU credited')
    expect(w.html()).not.toMatch(AVT)
    w.unmount()
  })
})
