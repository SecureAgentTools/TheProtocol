/**
 * V0660 (k), Guild order gwo_9230be3d156cc3ce58699aaf: the settlements overview says the new end states in plain words
 * and offers Close (a reason required) only on a settlement the registry closes. RED on 4b79322d7.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'

const h = vi.hoisted(() => ({ list: vi.fn(), close: vi.fn() }))
vi.mock('@/services/api/settlements', () => ({
  settlementsApi: { list: (...a: unknown[]) => h.list(...a), close: (...a: unknown[]) => h.close(...a),
    approve: vi.fn(), reject: vi.fn(), listPeerConfigs: async () => ({ peers: [] }), updatePeerConfig: vi.fn() },
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('SBXB') }) }))
vi.mock('@/composables/useFrameManifest', () => ({ useFrameManifest: () => ({ manifest: ref(null) }) }))

import Settlements from './Settlements.vue'

const row = (id: string, status: string, held = '') => ({
  id, dispute_id: 50, status, complainant_did: 'did:theprotocol:c', defendant_did: 'did:theprotocol:d',
  requested_amount: 3, slashed_amount: 0, minted_amount: 0, shortfall: 3, is_partial: false, ruling: 'IN_FAVOR_OF_COMPLAINANT',
  origin_registry_url: 'https://sandbox-b.theprotocol.cloud:8443', defendant_registry_url: held,
  slash_tx_id: '', mint_tx_id: '', requested_at: '2026-11-07T14:00:00Z', slashed_at: null, settled_at: null, error_message: null,
})

let w: VueWrapper | null = null
async function page() {
  h.list.mockResolvedValue({ count: 3, stats: null, settlements: [row('s-refused', 'REFUSED'), row('s-held', 'PENDING_SLASH', 'https://x'),
    row('s-settled', 'SETTLED')] })
  w = mount(Settlements, { global: { stubs: { Icon: true, 'router-link': { template: '<a><slot /></a>' }, Teleport: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
// the cards in the order the registry answered them
const IDS = ['s-refused', 's-held', 's-settled']
const card = (id: string) => w!.findAll('div.overflow-hidden.transition-all')[IDS.indexOf(id)]

describe('the settlements overview and the end states', () => {
  beforeEach(() => { setActivePinia(createPinia()); h.list.mockReset(); h.close.mockReset() })
  afterEach(() => { w?.unmount(); w = null })

  it('says a refused settlement in plain words and offers Close only where it may', async () => {
    await page()
    expect(card('s-refused').text()).toContain('Refused by every peer')
    expect(card('s-refused').find('[data-testid="stl-close"]').exists()).toBe(true)
    expect(card('s-held').find('[data-testid="stl-close"]').exists()).toBe(false)
    expect(card('s-settled').find('[data-testid="stl-close"]').exists()).toBe(false)
  })

  it('closes only with a reason', async () => {
    await page()
    await card('s-refused').find('[data-testid="stl-close"]').trigger('click')
    await flushPromises()
    const confirm = w!.find('[data-testid="stl-decision-confirm"]')
    expect(confirm.attributes('disabled')).toBeDefined()
    await w!.find('[data-testid="stl-decision-reason"]').setValue('the peers never knew this address')
    expect(w!.find('[data-testid="stl-decision-confirm"]').attributes('disabled')).toBeUndefined()
    h.close.mockResolvedValueOnce({ status: 'CLOSED' })
    await w!.find('[data-testid="stl-decision-confirm"]').trigger('click')
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.close).toHaveBeenCalledWith('s-refused', 'the peers never knew this address')
  })
})
