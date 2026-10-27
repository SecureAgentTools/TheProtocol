/**
 * §FESUITE (V0578): the attestation analytics page kept the previous answer whatever its latest read did. A failed read
 * after a period change left the earlier window's figures under the new period's label ("No attestations submitted in
 * the last 7 days" about a window never read), a failed 60 s poll said so only in a passing toast, and the circuits list
 * (its service answered [] for a failed read) was drawn as "Available circuits (0):".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ analytics: vi.fn(), circuits: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: (url: string) => (url === '/circuits/' ? h.circuits() : Promise.reject(new Error(url))) } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import { attestationsAdminService } from '@/services/api/attestationsAdmin'
import AdminAttestationAnalytics from './AdminAttestationAnalytics.vue'

const analytics = (period: string) => ({
  as_of: '2026-10-05T14:50:00Z', period,
  stats: { total: 0, verified: 0, failed: 0, revoked: 0, expired: 0, active: 0, expiring_24h: 0, circuits_available: 3 },
  by_circuit: [], top_agents: [], recent: [], cadence: [],
  zkp_phases: { phase_1: true, phase_2: true, phase_3: false, phase_4: false, phase_5: false, phase_6: true },
})
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

let w: VueWrapper | null = null
async function page() {
  w = mount(AdminAttestationAnalytics, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function period(label: string) {
  const b = w!.findAll('.aa-period-btn').find(x => x.text() === label)
  expect(b, `no ${label} period`).toBeTruthy()
  await b!.trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}
const body = () => w!.find('.aa-body').text()

describe('the attestation analytics page shows only what its reads answered', () => {
  beforeEach(() => {
    h.analytics.mockReset(); h.circuits.mockReset(); h.showError.mockReset()
    vi.spyOn(attestationsAdminService, 'analytics').mockImplementation((...a: any[]) => h.analytics(...a))
    vi.spyOn(console, 'error').mockImplementation(() => {})
    h.circuits.mockResolvedValue({ data: { circuits: [{ circuit_id: 'fairMarkupPolicy', name: 'Fair markup', acir_url: '', source_url: '', nargo_toml_url: '' }] } })
  })
  afterEach(() => { w?.unmount(); w = null; vi.restoreAllMocks() })

  it('a failed read after a period change does not say "none" about the new window', async () => {
    h.analytics.mockResolvedValueOnce(analytics('30d'))
    await page()
    expect(body()).toContain('No attestations submitted in the last 30 days.')
    h.analytics.mockRejectedValueOnce(badGateway())
    await period('7 days')
    expect(body(), 'said none for a 7-day window whose read failed').not.toContain('No attestations submitted in the last 7 days.')
  })

  it('a failed poll of the same period says the figures are from the last read that answered', async () => {
    h.analytics.mockResolvedValueOnce(analytics('30d'))
    await page()
    h.analytics.mockRejectedValueOnce(badGateway())
    await w!.find('.aa-toolbar-meta .aa-btn--ghost').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w!.find('[data-read-failed]').exists(), 'a failed read said nothing on the page').toBe(true)
    expect(w!.find('[data-testid="aa-stale"]').text()).toContain('from the read at')
  })

  it('the phase banner counts the phases the registry reports', async () => {
    h.analytics.mockResolvedValueOnce({ ...analytics('30d'), zkp_phases: { phase_1: true, phase_2: true, phase_3: true, phase_4: true, phase_5: true } })
    await page()
    expect(w!.find('.aa-phase-banner').text()).toContain('all 5 phases on')
    expect(w!.find('.aa-phase-banner').classes()).toContain('aa-phase-banner--ok')
  })

  it('control: an older registry reporting six phases is counted against six', async () => {
    h.analytics.mockResolvedValueOnce(analytics('30d'))
    await page()
    expect(w!.find('.aa-phase-banner').text()).toContain('3/6')
  })

  it('a failed circuits read is never "Available circuits (0)"', async () => {
    h.circuits.mockRejectedValue(badGateway())
    h.analytics.mockResolvedValue(analytics('30d'))
    await page()
    expect(body(), 'drew "Available circuits (0)" for a list that never answered').not.toContain('Available circuits (0)')
    expect(w!.find('[data-testid="aa-circuits-failed"]').exists()).toBe(true)
    h.circuits.mockResolvedValue({ data: { circuits: [{ circuit_id: 'fairMarkupPolicy', name: 'Fair markup', acir_url: '', source_url: '', nargo_toml_url: '' }] } })
    await w!.find('[data-testid="aa-circuits-failed"] [data-testid="read-failed-retry"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(body()).toContain('Available circuits (1)')
  })
})
