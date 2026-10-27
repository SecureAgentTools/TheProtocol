/**
 * §FESUITE (V0578): the Disputes page's Analytics tab read the store's zeros whatever the reads did: with the disputes
 * list failed it drew a 0.0% resolution rate, "No disputes on record", "No disputes in the last 14 days" and a 0/0/0/0
 * ruling breakdown. Two of its trends were literals: "+5.2%" whenever any dispute existed and "↓ 2h" always. The tab
 * now draws what the list and the stats answered (the store's listRead, listFailed and statsRead), and no trend.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/api/disputes', () => ({ disputesApi: { getDisputes: vi.fn(), getStats: vi.fn() } }))

import { useDisputesStore } from '@/stores/disputes'
import DisputeAnalytics from './DisputeAnalytics.vue'

const dispute = (id: number, status: string) => ({
  id, status, claimant_did: `did:theprotocol:c${id}`, respondent_did: 'did:theprotocol:r', reason: 'Late delivery',
  description: 'The work arrived after the deadline', created_at: new Date().toISOString(), evidence: [],
})
let store: ReturnType<typeof useDisputesStore>
const tab = () => mount(DisputeAnalytics, { global: { stubs: { Icon: true } } })

describe('the Disputes analytics tab draws what its reads answered', () => {
  beforeEach(() => { setActivePinia(createPinia()); store = useDisputesStore() })

  it('over a failed disputes read: no zeros, no "none", no trend, and it says the read failed', () => {
    store.$patch({ listFailed: true, listRead: false, statsRead: false })
    const w = tab()
    const text = w.text()
    expect(text, 'drew a 0.0% resolution rate over reads that failed').not.toContain('0.0%')
    expect(text, 'said "none" about a list that never answered').not.toContain('No disputes on record')
    expect(text).not.toContain('No disputes in the last 14 days')
    expect(text).not.toMatch(/↓ 2h|\+5\.2%/)
    expect(w.findAll('.da-ruling-stat__value').map(v => v.text())).toEqual(['—', '—', '—', '—'])
    expect(w.find('[data-testid="da-read-failed"]').exists()).toBe(true)
  })

  it('answered disputes draw their figures, and no invented trend', () => {
    store.$patch({
      listRead: true, listFailed: false, statsRead: true,
      disputes: [dispute(1, 'open'), dispute(2, 'resolved'), dispute(3, 'resolved')] as any,
      stats: { total_disputes: 3, open_disputes: 1, resolved_disputes: 2, resolution_rate: 66.7, average_resolution_time: 30 },
    })
    const w = tab()
    expect(w.text(), 'drew a resolution trend nothing reads').not.toContain('+5.2%')
    expect(w.text(), 'drew a time trend nothing reads').not.toContain('↓ 2h')
    expect(w.find('[data-testid="da-resolution-rate"]').text()).toBe('66.7%')
    expect(w.findAll('.da-ruling-stat__value').map(v => v.text())).toEqual(['1', '2', '0', '0'])
    expect(w.find('[data-read-failed]').exists()).toBe(false)
  })

  it('an answered empty list says there are none', () => {
    store.$patch({ listRead: true, listFailed: false, statsRead: true, disputes: [] })
    const w = tab()
    expect(w.text()).toContain('No disputes on record')
    expect(w.text()).toContain('No disputes in the last 14 days')
  })

  it('a failed re-read keeps the last answer and says so', () => {
    store.$patch({ listRead: true, listFailed: true, statsRead: true, disputes: [dispute(1, 'open')] as any })
    const w = tab()
    expect(w.find('[data-testid="da-stale"]').exists()).toBe(true)
    expect(w.findAll('.da-ruling-stat__value').map(v => v.text())[0]).toBe('1')
  })
})
