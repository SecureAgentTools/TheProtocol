/**
 * §FESUITE (V0578): the bridge desk kept the previous answer whatever its latest read did. A failed read after a period
 * change left the earlier window's figures under the new period's label ("No SF-3 transfers in this window" about a
 * window never read); a failed 30 s poll left the figures looking current, saying so only in a passing toast. Now the
 * figures always answer the period they are labelled with, and a failed read of the same period says they are from the
 * last read that answered.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ aggregate: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/bridgeAdmin', () => ({ bridgeAdminService: { aggregate: (...a: unknown[]) => h.aggregate(...a) } }))
vi.mock('@/composables/usePolledData', () => ({
  // the fetcher runs once, as `immediate` does; no timers
  usePolledData: (fn: () => unknown) => { fn(); return { pause() {}, resume() {} } },
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import AdminBridge from './AdminBridge.vue'

const SF3_NONE = 'No SF-3 transfers in this window'
const aggregate = (period: string, asyncTotal: number) => ({
  period, as_of: '2026-10-05T14:40:00Z',
  async: { status_counts: {}, total: asyncTotal, settled: asyncTotal, refunded: 0, locked: 0, settle_rate_pct: 100,
    refund_rate_pct: 0, avg_settled_ms: 900, p50_settled_ms: 800, p95_settled_ms: 1500, inflight_locked: 0, expiring_5min: 0 },
  inbound: { status_counts: {}, total: 0 },
  sync_sf3: { status_counts: {}, total: 0 },
  recent_async: [], recent_sync: [],
})
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

let w: VueWrapper | null = null
async function desk() {
  w = mount(AdminBridge, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function period(label: string) {
  const b = w!.findAll('.ab-period-btn').find(x => x.text() === label)
  expect(b, `no ${label} period`).toBeTruthy()
  await b!.trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}
const body = () => w!.find('.ab-body').text()

describe('the bridge desk shows only what its latest read answered', () => {
  beforeEach(() => { h.aggregate.mockReset(); h.showError.mockReset() })
  afterEach(() => { w?.unmount(); w = null })

  it('a failed read after a period change does not label the earlier window\'s figures with the new period', async () => {
    h.aggregate.mockResolvedValueOnce(aggregate('24h', 17))
    await desk()
    expect(body()).toContain(SF3_NONE)
    h.aggregate.mockRejectedValueOnce(badGateway())
    await period('7 days')
    expect(h.aggregate).toHaveBeenLastCalledWith('7d')
    expect(body(), 'said "no SF-3 transfers" for a window whose read failed').not.toContain(SF3_NONE)
    expect(body(), 'showed the 24h figures under the 7-day label').not.toContain('7 days')
  })

  it('a failed poll of the same period says the figures are from the last read that answered', async () => {
    h.aggregate.mockResolvedValueOnce(aggregate('24h', 17))
    await desk()
    h.aggregate.mockRejectedValueOnce(badGateway())
    await w!.find('.ab-toolbar-meta .ab-btn--ghost').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w!.find('[data-read-failed]').exists(), 'a failed read said nothing on the page').toBe(true)
    expect(w!.find('[data-testid="ab-stale"]').text()).toContain('from the read at')
  })

  it('a later read of the new period that answers shows that period\'s figures', async () => {
    h.aggregate.mockResolvedValueOnce(aggregate('24h', 17))
    await desk()
    h.aggregate.mockResolvedValueOnce(aggregate('7d', 230))
    await period('7 days')
    expect(body()).toContain('230')
    expect(body()).toContain('7 days')
    expect(w!.find('[data-read-failed]').exists()).toBe(false)
  })
})
