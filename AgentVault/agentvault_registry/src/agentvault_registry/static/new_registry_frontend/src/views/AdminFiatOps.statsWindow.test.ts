/**
 * §FESUITE (V0578): the fiat desk's overview drew whatever stats it last held under whichever window button was
 * selected. A failed read for another window left the earlier window's KPIs under the new button, and the window buttons
 * stay live during a read, so an earlier window's answer landing after a later one replaced it. Now the KPIs answer the
 * selected window or are not drawn (the picker stays, to choose another window), and a failed read of the same window
 * says the figures are from the last read that answered.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getStats: vi.fn() }))
vi.mock('@/services/api/fiatOnramp', () => ({
  fiatOpsAdminService: {
    getStats: (...a: unknown[]) => h.getStats(...a),
    listPurchases: async () => ({ rows: [], total: 0 }),
    getPurchase: vi.fn(), replayPurchase: vi.fn(), resendMagicLink: vi.fn(), refund: vi.fn(),
  },
  fiatPricingAdminService: { getPricing: async () => ({ active: null, history: [], fallback_in_use: false }) },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: async () => ({ data: [] }), post: vi.fn() } }))

import AdminFiatOps from './AdminFiatOps.vue'

const stats = (days: number, eur: string) => ({
  window_days: days, total_eur: eur, total_avt: '0', completed_count: 1, pending_count: 0, failed_count: 0, refunded_count: 0,
  success_rate_pct: '100', anonymous_devs_created: 0, avg_purchase_eur: eur, status_breakdown: [], daily_revenue: [],
  tier_share: [], treasury_consumed_estimate_avt: '0',
})
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

let w: VueWrapper
async function desk() {
  w = mount(AdminFiatOps, { global: { stubs: { Icon: true, FlareBadge: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function window_(days: number) {
  const b = w.findAll('.afo-window-btn').find(x => x.text() === `${days}d`)
  expect(b, `no ${days}d button`).toBeTruthy()
  await b!.trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}
const kpis = () => w.find('.afo-kpi-grid').exists() ? w.find('.afo-kpi-grid').text() : ''

describe("the fiat desk's stats answer the selected window", () => {
  beforeEach(() => { h.getStats.mockReset(); vi.spyOn(console, 'error').mockImplementation(() => {}) })

  it('a failed read for another window does not leave the earlier window\'s KPIs under its button', async () => {
    h.getStats.mockResolvedValueOnce(stats(30, '4321'))
    await desk()
    expect(kpis()).toContain('4,321')
    h.getStats.mockRejectedValueOnce(badGateway())
    await window_(7)
    expect(kpis(), 'drew the 30-day revenue under the 7-day button after its read failed').not.toContain('4,321')
    expect(w.find('[data-testid="afo-stats-window-unread"]').exists()).toBe(true)
    expect(w.findAll('.afo-window-btn').length, 'the picker went away with the figures').toBe(5)
  })

  it('an earlier window\'s answer landing after a later one never replaces it', async () => {
    h.getStats.mockResolvedValueOnce(stats(30, '4321'))
    await desk()
    let release7!: (v: unknown) => void
    h.getStats.mockImplementationOnce(() => new Promise(r => { release7 = r }))   // 7d, slow
    h.getStats.mockResolvedValueOnce(stats(90, '9876'))                           // 90d, fast
    await window_(7)
    await window_(90)
    release7(stats(7, '1111'))
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(kpis(), 'the late 7-day answer replaced the 90-day one').toContain('9,876')
    expect(kpis()).not.toContain('1,111')
  })

  it('a failed read of the same window says the figures are from the last read', async () => {
    h.getStats.mockResolvedValueOnce(stats(30, '4321'))
    await desk()
    h.getStats.mockRejectedValueOnce(badGateway())
    await window_(30)
    expect(kpis()).toContain('4,321')
    expect(w.find('[data-testid="afo-stats-stale"]').exists(), 'a failed read said nothing on the page').toBe(true)
  })
})
