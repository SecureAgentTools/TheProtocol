/**
 * §FESUITE (V0577): My Agents' A2A payment tokens panel lists the agent's tokens and counts them by state above the list.
 * A failed list read showed its error with "No payment tokens yet" under it and 0 AUTHORIZED / 0 SETTLED / 0 RELEASED /
 * 0 FAILED above it: an agent holding authorized tokens (funds held until settled or released) read as holding none. The
 * error now stands alone, the counts read "—", and an answered empty list still says none.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ listMyTokens: vi.fn() }))
vi.mock('@/services/api/a2aPayment', () => ({ a2aPaymentService: { listMyTokens: h.listMyTokens } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))

import PaymentTokensPanel from './PaymentTokensPanel.vue'

async function openPanel() {
  const w = mount(PaymentTokensPanel, { props: { agentDid: 'did:theprotocol:me', hasAgentToken: true } })
  await w.find('.pt-header').trigger('click')
  await flushPromises()
  return w
}
const counts = (w: any) => w.findAll('.pt-stat-value').map((v: any) => v.text())

describe("My Agents' payment tokens when the list read fails", () => {
  beforeEach(() => { h.listMyTokens.mockReset() })

  it('shows the error alone: no "No payment authorizations yet", and counts of "—", never 0', async () => {
    h.listMyTokens.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await openPanel()
    expect(w.find('.pt-error').exists()).toBe(true)
    expect(w.text()).not.toContain('No payment authorizations yet')
    expect(counts(w)).toEqual(['—', '—', '—', '—'])
    expect(w.find('.pt-count').exists(), 'the header counted 0 tokens over a failed read').toBe(false)
  })

  it('the closed panel, which has read nothing yet, counts nothing in its header', async () => {
    const w = mount(PaymentTokensPanel, { props: { agentDid: 'did:theprotocol:me', hasAgentToken: true } })
    await flushPromises()
    expect(h.listMyTokens).not.toHaveBeenCalled()
    expect(w.find('.pt-count').exists(), 'the header said 0 before any read').toBe(false)
  })

  it('an answered empty list still says none, with counts of 0', async () => {
    h.listMyTokens.mockResolvedValue([])
    const w = await openPanel()
    expect(w.text()).toContain('No payment authorizations yet')
    expect(counts(w)).toEqual(['0', '0', '0', '0'])
  })
})
