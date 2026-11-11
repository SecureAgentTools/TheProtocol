/**
 * V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf: the settlements desk shows the new end states in plain words and
 * offers Close (with a reason) only on a settlement the registry closes; a refusal is shown in the registry's words.
 * RED on 4b79322d7: no Close, no words for the new states.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ list: vi.fn(), close: vi.fn(), showError: vi.fn(), showSuccess: vi.fn() }))
vi.mock('@/services/api/settlementsAdmin', () => ({
  settlementsAdminService: { list: (...a: unknown[]) => h.list(...a), approve: vi.fn(), reject: vi.fn(),
    close: (...a: unknown[]) => h.close(...a) },
}))
vi.mock('@/composables/usePolledData', () => ({
  usePolledData: (fn: () => unknown) => { fn(); return { pause() {}, resume() {} } },
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('SBXB') }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError, showWarning: vi.fn(), showSuccess: h.showSuccess }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import AdminSettlements from './AdminSettlements.vue'

const row = (id: string, status: string, held = '') => ({
  id, dispute_id: 50, status, complainant_did: 'did:theprotocol:c', defendant_did: 'did:theprotocol:d',
  requested_amount: 3, slashed_amount: 0, minted_amount: 0, shortfall: 3, is_partial: false, ruling: 'IN_FAVOR_OF_COMPLAINANT',
  origin_registry_url: 'https://sandbox-b.theprotocol.cloud:8443', defendant_registry_url: held,
  requested_at: '2026-11-07T14:00:00Z', slashed_at: null, settled_at: null,
  error_message: status === 'REFUSED' ? 'Refused by every peer registry: Sandbox Alpha 400' : null,
})
const ROWS = [row('s-refused', 'REFUSED'), row('s-off', 'NOT_DELIVERED'), row('s-held', 'PENDING_SLASH', 'https://sandbox-a.theprotocol.cloud:8443'),
  row('s-settled', 'SETTLED'), row('s-closed', 'CLOSED')]
const stats = { total: 5, pending: 1, settled: 1, slashed: 0, failed: 0, expired: 0, not_delivered: 1, refused: 1, closed: 1,
  total_requested_avt: 15, total_slashed_avt: 0, total_minted_avt: 0 }

let w: VueWrapper | null = null
async function desk() {
  h.list.mockResolvedValue({ count: ROWS.length, stats, settlements: ROWS })
  w = mount(AdminSettlements, { global: { stubs: { Icon: true, SlashOrderPanel: true, PeerAutoSlashPanel: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
// the desk lists the rows in the order the registry answered them
const feedRow = (id: string) => w!.findAll('.as-feed-row')[ROWS.findIndex(r => r.id === id)]

describe('the settlements desk and the end states', () => {
  beforeEach(() => { h.list.mockReset(); h.close.mockReset(); h.showError.mockReset(); h.showSuccess.mockReset() })
  afterEach(() => { w?.unmount(); w = null })

  it('says the new states in plain words', async () => {
    await desk()
    expect(feedRow('s-refused').text()).toContain('Refused by every peer')
    expect(feedRow('s-off').text()).toContain('Not delivered')
    expect(feedRow('s-off').find('[data-testid="as-state-note"]').text()).toMatch(/no slash request was sent/i)
    expect(feedRow('s-closed').text()).toContain('Closed')
  })

  it('offers Close only on a settlement no peer holds and nothing moved on', async () => {
    await desk()
    const has = (id: string) => feedRow(id).find('[data-testid="as-close"]').exists()
    expect(has('s-refused')).toBe(true)
    expect(has('s-off')).toBe(true)
    expect(has('s-held')).toBe(false)
    expect(has('s-settled')).toBe(false)
    expect(has('s-closed')).toBe(false)
  })

  it('closes with the reason the administrator wrote', async () => {
    await desk()
    h.close.mockResolvedValueOnce({ settlement_id: 's-refused', status: 'CLOSED' })
    await feedRow('s-refused').find('[data-testid="as-close"]').trigger('click')
    await flushPromises()
    const modal = w!.find('[data-testid="as-close-modal"]')
    expect(modal.exists()).toBe(true)
    await modal.find('textarea').setValue('the peers never knew this address')
    await modal.findAll('button').find(b => b.text() === 'Close settlement')!.trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.close).toHaveBeenCalledWith('s-refused', 'the peers never knew this address')
  })

  it("shows a refusal in the registry's words", async () => {
    await desk()
    const detail = 'Settlement s-refused is CLOSED: it was closed already'
    h.close.mockRejectedValueOnce(new AxiosError('Request failed with status code 409', 'ERR_BAD_REQUEST', undefined, undefined,
      { status: 409, statusText: '', data: { detail }, headers: {}, config: {} } as any))
    await feedRow('s-refused').find('[data-testid="as-close"]').trigger('click')
    await flushPromises()
    const modal = w!.find('[data-testid="as-close-modal"]')
    await modal.find('textarea').setValue('the peers never knew this address')
    await modal.findAll('button').find(b => b.text() === 'Close settlement')!.trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w!.find('[data-testid="as-close-refused"]').text()).toContain(detail)
  })
})
