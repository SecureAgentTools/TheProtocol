/**
 * §FESUITE (V0578): the settlements desk kept the previous answer whatever its latest read did. A failed read after a
 * filter change left the earlier filter's rows under the new filter's chip ("No settlements match this filter." when that
 * list was empty); a failed poll left the list as if it were current, saying so only in a passing toast. Now the list is always the answer to the chip it sits under, and
 * a failed read of the same filter says the list is from the last read that answered.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ list: vi.fn(), showError: vi.fn() }))
vi.mock('@/services/api/settlementsAdmin', () => ({
  settlementsAdminService: { list: (...a: unknown[]) => h.list(...a), approve: vi.fn(), reject: vi.fn() },
}))
vi.mock('@/composables/usePolledData', () => ({
  // the fetcher runs once, as `immediate` does; no timers
  usePolledData: (fn: () => unknown) => { fn(); return { pause() {}, resume() {} } },
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError, showWarning: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import AdminSettlements from './AdminSettlements.vue'

const stats = { total: 1, pending: 0, settled: 1, slashed: 0, failed: 0, expired: 0, total_requested_avt: 5, total_slashed_avt: 5, total_minted_avt: 5 }
const row = (id: string, status: string) => ({
  id, dispute_id: 7, status, complainant_did: 'did:theprotocol:c', defendant_did: 'did:theprotocol:d',
  requested_amount: 5, slashed_amount: 5, minted_amount: 5, shortfall: 0, is_partial: false, ruling: 'for_complainant',
  origin_registry_url: 'https://eu.example', defendant_registry_url: 'https://asia.example',
  requested_at: '2026-10-05T14:00:00Z', slashed_at: null, settled_at: null,
})
const answer = (rows: any[]) => ({ count: rows.length, stats: { ...stats, total: rows.length }, settlements: rows })
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

let w: VueWrapper | null = null
async function desk() {
  w = mount(AdminSettlements, { global: { stubs: { Icon: true, ConfirmActionModal: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
async function chip(label: string) {
  const b = w!.findAll('.as-chip-btn').find(x => x.text() === label)
  expect(b, `no ${label} chip`).toBeTruthy()
  await b!.trigger('click')
  for (let i = 0; i < 4; i++) await flushPromises()
}
const body = () => w!.find('.as-body').text()

describe('the settlements desk lists only what its latest read answered', () => {
  beforeEach(() => { h.list.mockReset(); h.showError.mockReset() })
  afterEach(() => { w?.unmount(); w = null })

  it('a failed read after a filter change does not keep the earlier filter\'s rows under the new chip', async () => {
    h.list.mockResolvedValueOnce(answer([row('st-all-1', 'SETTLED')]))
    await desk()
    expect(w!.findAll('.as-feed-row')).toHaveLength(1)
    h.list.mockRejectedValueOnce(badGateway())
    await chip('Failed')
    expect(h.list).toHaveBeenLastCalledWith('FAILED')
    expect(w!.findAll('.as-feed-row'), 'kept the "All" rows under the "Failed" chip after its read failed').toHaveLength(0)
    expect(body()).not.toContain('No settlements match this filter.')
  })

  it('a failed read of an empty list under a new filter never says "No settlements match this filter."', async () => {
    h.list.mockResolvedValueOnce(answer([]))
    await desk()
    expect(body()).toContain('No settlements match this filter.')
    h.list.mockRejectedValueOnce(badGateway())
    await chip('Expired')
    expect(body(), 'said none for "Expired" over a read that failed').not.toContain('No settlements match this filter.')
  })

  it('a failed poll of the same filter says the list is from the last read that answered', async () => {
    h.list.mockResolvedValueOnce(answer([]))
    await desk()
    h.list.mockRejectedValueOnce(badGateway())
    await w!.find('.as-toolbar-meta .as-btn--ghost').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w!.find('[data-read-failed]').exists(), 'a failed read said nothing on the page').toBe(true)
    expect(w!.find('[data-testid="as-stale"]').text()).toContain('from the read at')
  })
})
