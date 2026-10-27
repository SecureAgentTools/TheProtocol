import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): the funding queue opens on Pending and reads one filter at a time, but its
 * four tiles counted whatever list was loaded: under Pending (where it opens) "Approved (24h) 0" and "Rejected (24h) 0"
 * whatever the registry did, because those rows were never asked for. A tile now counts only from a list that holds its
 * whole population ('—' otherwise, with the reason on hover). And a filter switched while a read is in flight takes only
 * the newest answer: a late answer for a filter already left listed its rows under the newer chip.
 */
const h = vi.hoisted(() => ({
  svc: { listPending: vi.fn(), listAll: vi.fn() },
  ui: { showError: vi.fn(), showSuccess: vi.fn() },
}))
vi.mock('@/services/api/fundingAdmin', () => ({ fundingAdminService: h.svc }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => h.ui }))
vi.mock('@/composables/useCurrency', async () => {
  const { ref } = await import('vue')
  return { useCurrency: () => ({ localCurrency: ref('ECU') }) }
})

import FundingRequestsPanel from './FundingRequestsPanel.vue'

const now = new Date().toISOString()
const row = (id: number, status: string) => ({
  id, status, agent_did: `did:theprotocol:${id}`, requested_amount: 10, approved_amount: null, reason: 'r',
  created_at: now, reviewed_at: status === 'pending' ? null : now, funded_at: null, rejection_reason: null,
  funding_transaction_id: null,
})
const PENDING = [row(1, 'pending'), row(2, 'pending')]
const ALL = [...PENDING, row(3, 'approved'), row(4, 'funded'), row(5, 'rejected')]
const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true } } }

function tiles(w: ReturnType<typeof mount>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const t of w.findAll('.fr-stat')) out[t.find('.fr-stat-label').text()] = t.find('.fr-stat-value').text()
  return out
}
async function choose(w: ReturnType<typeof mount>, label: string) {
  await w.findAll('button.fr-chip').find((b) => b.text().startsWith(label))!.trigger('click')
}

describe('the funding queue counts only what it read', () => {
  beforeEach(() => {
    h.svc.listPending.mockReset().mockResolvedValue(PENDING)
    h.svc.listAll.mockReset().mockImplementation(async (p?: { status?: string }) =>
      (p?.status ? ALL.filter((r) => r.status === p.status) : ALL))
  })

  it('opens on Pending: the 24h approved and rejected tiles are not counted (they read 0 before)', async () => {
    const w = mount(FundingRequestsPanel, opts)
    await flushPromises()
    expect(tiles(w)).toEqual({ Pending: '2', 'Approved (24h)': '—', 'Rejected (24h)': '—', 'Total in window': '2' })
    w.unmount()
  })

  it('All counts every tile; Rejected counts only its own', async () => {
    const w = mount(FundingRequestsPanel, opts)
    await flushPromises()
    await choose(w, 'All')
    await flushPromises()
    expect(tiles(w)).toEqual({ Pending: '2', 'Approved (24h)': '2', 'Rejected (24h)': '1', 'Total in window': '5' })
    await choose(w, 'Rejected')
    await flushPromises()
    expect(tiles(w)).toEqual({ Pending: '—', 'Approved (24h)': '—', 'Rejected (24h)': '1', 'Total in window': '1' })
    w.unmount()
  })

  it('a late answer for a filter already left does not land under the newer chip', async () => {
    const w = mount(FundingRequestsPanel, opts)
    await flushPromises()
    let release: (v: unknown) => void = () => {}
    h.svc.listAll.mockImplementationOnce(() => new Promise((res) => { release = res }))  // Approved: held
    await choose(w, 'Approved')
    await choose(w, 'All')                                                             // answers at once
    await flushPromises()
    release(ALL.filter((r) => r.status === 'approved'))                              // Approved answers late
    await flushPromises()
    expect(w.findAll('.fr-list > *').length, 'the All list is shown').toBe(ALL.length)
    expect(tiles(w)['Total in window']).toBe('5')
    w.unmount()
  })
})
