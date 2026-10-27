import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §REPATLANE (V0603): the AGORA gateway's payout lane holds a payout whose answer did not prove that nothing moved
 * ('unresolved'): it is never sent again on its own, so a second send cannot pay a trader twice. The Stuck-Funds board
 * is where an operator learns of one: the keeper strip counts them ("held") and a high finding says what to read.
 * RED control: before V0603 the board named only "abandoned" and "dust", so a held payout was on no screen.
 */
const h = vi.hoisted(() => ({
  api: {
    exchangeInvariant: vi.fn(), exchangeOverview: vi.fn(), auditorLatest: vi.fn(), feeCollector: vi.fn(),
    gatewayKeeper: vi.fn(), inventory: vi.fn(),
  },
}))
vi.mock('@/services/api/forensics', async (orig) => ({ ...(await orig<object>()), forensicsApi: h.api }))

import StuckFundsTab from './StuckFundsTab.vue'

const keeper = (held: number) => ({
  enabled: true, buffer: 50, currency: 'SBXA', gateway_did: 'did:theprotocol:agora-gateway-sbxalphaop-sbxa',
  gateway_balance: 1000, outstanding_obligation: 12, repat_dust: 0.5,
  credits: {
    by_status: {}, dust: { count: 0, sum: 0 }, abandoned: { count: 0, sum: 0 },
    deliverable_pending: { count: 1, sum: 12 }, unresolved: { count: held, sum: held * 2.5 },
    in_flight: { count: 0, sum: 0 },
  },
})

async function board(held: number) {
  h.api.exchangeInvariant.mockResolvedValue({ ok: true })
  h.api.exchangeOverview.mockResolvedValue({ currency: 'SBXA', orders_by_status: {} })
  h.api.auditorLatest.mockResolvedValue({})
  h.api.feeCollector.mockResolvedValue(null)
  h.api.gatewayKeeper.mockResolvedValue(keeper(held))
  h.api.inventory.mockResolvedValue({ rails: [] })
  const w = mount(StuckFundsTab, { props: { frame: 'local' as any }, global: { stubs: { Icon: true } } })
  await flushPromises()
  return w
}

describe('the Stuck-Funds board shows held payouts', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    Object.values(h.api).forEach((f) => f.mockReset())
  })

  it('counts them on the keeper strip and raises a finding that says what to read', async () => {
    const w = await board(3)
    expect(w.find('[data-testid="gk-unresolved"]').text()).toContain('3')
    expect(w.text()).toContain('3 gateway payout(s) HELD: money may have moved')
    expect(w.text()).toContain('7.5 SBXA')
    w.unmount()
  })

  it('control: none held, no finding', async () => {
    const w = await board(0)
    expect(w.find('[data-testid="gk-unresolved"]').text()).toContain('0')
    expect(w.text()).not.toContain('HELD: money may have moved')
    w.unmount()
  })
})
