import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0577 (2026-10-05, agentvault2-09): Fiat Ops swallowed two reads. The purchase explorer said "No purchases
 * match the current filters." over a failed search (and kept the previous filters' rows and total for the next one; only
 * the newest search lands now); the flare list said "No flares granted yet. Click Grant flare above to start." under a
 * 0 count. Each says its read failed (Try again); a registry without the flare route (404) still reads as an empty list.
 */
const h = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn() }))
vi.mock('@/services/api/fiatOnramp', () => ({
  fiatPricingAdminService: { getPricing: vi.fn().mockResolvedValue({ active: null, history: [], fallback_in_use: false }),
    putPricing: vi.fn(), simulate: vi.fn(), validatePricing: vi.fn() },
  fiatOpsAdminService: { getStats: vi.fn().mockResolvedValue(null), listPurchases: h.list, getPurchase: vi.fn(),
    refund: vi.fn(), replayPurchase: vi.fn(), resendMagicLink: vi.fn() },
}))
vi.mock('@/services/api/client', () => ({ apiClient: { get: h.get, post: vi.fn() } }))

import AdminFiatOps from './AdminFiatOps.vue'

const opts = { global: { stubs: { Icon: true, FlareBadge: true, Teleport: true, teleport: true } } }
const failure = (status = 502) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

const OLD_ROW = {
  id: 'p-old', stripe_session_id: 'old-session', stripe_event_id: null, stripe_payment_intent_id: null, developer_id: 1,
  agent_did: 'did:theprotocol:a', customer_email: 'a@example.com', amount_eur: '5.00', amount_avt: '10000', avt_per_eur_rate: '2000',
  tier_label: 'starter', status: 'completed', failure_reason: null, avt_transfer_tx_id: null, anonymous_flow: false,
  created_at: '2026-10-05T12:00:00Z', completed_at: '2026-10-05T12:01:00Z', refunded_at: null,
}

describe('Fiat Ops says what its explorer and flare reads answered', () => {
  beforeEach(() => { h.list.mockReset(); h.get.mockReset() })

  it('failed reads: no "No purchases match", no "No flares granted yet"; each says it failed', async () => {
    h.list.mockRejectedValue(failure())
    h.get.mockRejectedValue(failure())
    const w = mount(AdminFiatOps, opts)
    await flushPromises()
    expect(w.text()).not.toContain('No purchases match the current filters.')
    expect(w.text()).not.toContain('No flares granted yet')
    expect(w.find('[data-testid="afo-explorer-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="afo-flares-unread"]').exists()).toBe(true)
    w.unmount()
  })

  it('answered empties and a missing flare route (404) keep their words', async () => {
    h.list.mockResolvedValue({ rows: [], total: 0, offset: 0 })
    h.get.mockRejectedValue(failure(404))
    const w = mount(AdminFiatOps, opts)
    await flushPromises()
    expect(w.text()).toContain('No purchases match the current filters.')
    expect(w.text()).toContain('No flares granted yet')
    expect(w.find('[data-read-failed]').exists()).toBe(false)
    w.unmount()
  })

  it('a late answer for an earlier search does not land over the newer one', async () => {
    h.get.mockResolvedValue({ data: [] })
    h.list.mockResolvedValue({ rows: [], total: 0, offset: 0 })   // the mount's reads (the stats' recent rows, the explorer)
    const w = mount(AdminFiatOps, opts)
    await flushPromises()
    const vm = w.vm as any
    let release: (v: unknown) => void = () => {}
    h.list.mockImplementationOnce(() => new Promise((res) => { release = res }))   // search A: held
    const a = vm.loadExplorer(0)
    h.list.mockResolvedValueOnce({ rows: [], total: 0, offset: 0 })               // search B: answers none
    await vm.loadExplorer(0)
    release({ rows: [OLD_ROW], total: 1, offset: 0 })                              // search A answers late
    await a
    await flushPromises()
    expect(vm.explorer.rows.length, 'the late answer for the earlier search did not land').toBe(0)
    expect(w.text(), 'the newer search said none').toContain('No purchases match the current filters.')
    w.unmount()
  })
})
