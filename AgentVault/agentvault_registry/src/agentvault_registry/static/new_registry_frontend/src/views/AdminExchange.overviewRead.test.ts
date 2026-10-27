import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-05): before the market overview answered, and over a failed read, the header said MARKET DARK and
 * PASSPORT OFF: states the page never read. It says a dash until the overview answers, and a failed read says so.
 */
const adm = vi.hoisted(() => ({ overview: vi.fn(), participants: vi.fn(), invariant: vi.fn() }))
const ex = vi.hoisted(() => ({ listings: vi.fn() }))
vi.mock('@/services/api/exchangeAdminService', () => ({ exchangeAdminService: adm }))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: ex }))
vi.mock('@/services/api/jurisdictionAdmin', () => ({ parseBlockers: () => [] }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import AdminExchange from './AdminExchange.vue'

const opts = { global: { stubs: { Icon: true, ConfirmActionModal: true } } }

describe('the AGORA admin header says what it read', () => {
  beforeEach(() => {
    for (const f of [adm.overview, adm.participants, adm.invariant, ex.listings]) f.mockReset()
    ex.listings.mockResolvedValue({ listings: [] })
    adm.participants.mockResolvedValue({ participants: [] })
    adm.invariant.mockRejectedValue(new Error('not now'))
  })

  it('a failed overview read is no MARKET DARK and no PASSPORT OFF', async () => {
    adm.overview.mockRejectedValue(Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } }))
    const w = mount(AdminExchange, opts)
    await flushPromises()
    expect(w.text()).not.toContain('MARKET DARK')
    expect(w.text()).not.toContain('PASSPORT OFF')
    expect(w.find('[data-testid="adx-market-chip"]').text()).toContain('MARKET —')
    expect(w.find('[data-testid="adx-overview-failed"]').exists()).toBe(true)
    w.unmount()
  })

  it('an overview that answers dark says MARKET DARK', async () => {
    adm.overview.mockResolvedValue({ venue_enabled: false, passport_enabled: false, currency: 'SBXB', global_halt: false,
      escrow_balance: '0', trades_24h: 0, notional_24h: '0', trades_total: 0, settlement: { pending: 0, oldest_lag_seconds: 0 },
      orders_by_status: {}, participants_by_source: {} })
    const w = mount(AdminExchange, opts)
    await flushPromises()
    expect(w.find('[data-testid="adx-market-chip"]').text()).toContain('MARKET DARK')
    expect(w.find('[data-testid="adx-overview-failed"]').exists()).toBe(false)
    w.unmount()
  })
})
