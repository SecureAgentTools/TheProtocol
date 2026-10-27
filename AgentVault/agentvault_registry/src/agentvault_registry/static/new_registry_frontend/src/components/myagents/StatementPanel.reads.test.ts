/**
 * §FESUITE (V0577): My Agents' Statement reconciles the agent's statement against its live balance. A failed balance read
 * became { balance: '0' }: the strip said "Live balance 0.00" and raised "Reconcile · Mismatch — likely older txs not in
 * this window" over a statement that may balance exactly. A failed statement read showed its error with "No
 * transactions yet… hasn't sent or received any" under it and "Sum of statement 0.00". Each now says what could not be
 * read ("—", and no verdict either way); answers still reconcile as before.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getTransactions: vi.fn(), getBalance: vi.fn() }))
vi.mock('@/services/api/teg', () => ({ tegApi: { getTransactions: h.getTransactions, getBalance: h.getBalance } }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ localCurrency: ref('ECU') }) }))

import StatementPanel from './StatementPanel.vue'

const DID = 'did:theprotocol:me'
const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
// one incoming transfer of 25: the statement sums to 25, the balance answers 25 when it answers
const TX = [{ id: 't1', transaction_type: 'transfer', amount: '25', fee_amount: '0', sender_agent_id: 'did:theprotocol:other',
  receiver_agent_id: DID, status: 'completed', created_at: '2026-10-05T10:00:00Z' }]

async function openStatement() {
  const w = mount(StatementPanel, { props: { agentDid: DID, hasAgentToken: true } })
  await w.find('.st-header').trigger('click')
  await flushPromises()
  return w
}

describe("My Agents' Statement when a read fails", () => {
  beforeEach(() => { h.getTransactions.mockReset(); h.getBalance.mockReset() })

  it('a failed balance read is "—" with no verdict, never "Live balance 0.00" and a mismatch', async () => {
    h.getTransactions.mockResolvedValue({ transactions: TX, total: 1 })
    h.getBalance.mockRejectedValue(noAnswer())
    const w = await openStatement()
    expect(w.text()).not.toContain('Mismatch')
    expect(w.find('.st-pill--err').exists(), 'raised "Reconcile" over a balance nobody read').toBe(false)
    expect(w.find('.st-pill--ok').exists()).toBe(false)
    expect(w.find('[data-testid="st-balance-unread"]').exists()).toBe(true)
    expect(w.find('[data-testid="st-recon-unread"]').text()).toContain('cannot be reconciled')
  })

  it('a failed statement read shows its error alone: no "No transactions yet", no sum of 0.00', async () => {
    h.getTransactions.mockRejectedValue(noAnswer())
    h.getBalance.mockResolvedValue({ balance: '25' })
    const w = await openStatement()
    expect(w.find('.st-error').exists()).toBe(true)
    expect(w.text()).not.toContain('No transactions yet')
    expect(w.find('[data-testid="st-sum-unread"]').exists(), 'drew "Sum of statement 0.00" over a failed read').toBe(true)
  })

  it('both answered and agreeing still reads "✓ Reconciled"', async () => {
    h.getTransactions.mockResolvedValue({ transactions: TX, total: 1 })
    h.getBalance.mockResolvedValue({ balance: '25' })
    const w = await openStatement()
    expect(w.find('.st-pill--ok').exists()).toBe(true)
    expect(w.find('[data-testid="st-balance-unread"]').exists()).toBe(false)
  })
})
