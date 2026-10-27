/**
 * D6-839 (agentvault2-5b, 2026-10-25, found by the console suite's a_member_buys_a_paid_service on sbx-alpha, V0641): a
 * purchase's receipt said "settling…" for good. /a2a-payment/settle answers "settling" and settles in a background task
 * (both of the suite's purchases settled within half a second), /buy hands that word on, and the panel never read it
 * again. It now reads the token's state from /a2a-payment/my-tokens until the state is final, bounded. The store and the
 * API are doubles; the composable is the real one.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, tokens: [] as any[], api: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/agentCredentialsStore', () => ({
  agentCredentialsStore: { getAllCredentials: () => ({}), isSealedLocked: () => false },
}))
vi.mock('@/services/credentialVault', () => ({ credentialVault: { onChange: () => {} } }))
vi.mock('@/services/api/client', () => ({ default: h.api, apiClient: h.api }))

import BuyServicePanel from './BuyServicePanel.vue'

const buyer = { did: 'did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-000000000041', name: 'mine', owned: true, status: 'active' }
const target = 'did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-000000000050'
const QUOTE = { payment_required: true, can_buy: true, recommended_amount: '0.5', your_currency: 'SBXA', same_currency: true }
const bought = (tokenId: string) => ({ data: {
  ok: true, stage: 'settled', token_id: tokenId, paid_amount: '0.5', paid_currency: 'SBXA',
  settlement_status: 'settling', settlement_tx_id: null, result: { result: { artifacts: [] } },
} })

function actingStore() {
  h.auth = reactive({
    availableAgents: [buyer], activeAgent: null as any, agentToken: null as any,
    canActAs: (a: any) => !!a && (!!a.owned || !!(a.client_id && a.client_secret)),
    authenticateAsAgent: vi.fn(async (row: any) => { h.auth.activeAgent = row; h.auth.agentToken = 'agent.jwt'; return true }),
  })
}

async function buyOnce(w: ReturnType<typeof mount>) {
  await w.find('[data-testid="bsp-prompt"]').setValue('weather in Berlin')
  await w.find('[data-testid="bsp-go"]').trigger('click')
  await flushPromises()
}
const settlement = (w: ReturnType<typeof mount>) => w.find('[data-testid="bsp-settlement"]').text()
const tokenReads = () => h.api.get.mock.calls.filter((c) => c[0] === '/a2a-payment/my-tokens').length

describe('a purchase answered "settling" learns how it ended', () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] })
    localStorage.clear()
    h.tokens = []
    h.api.get.mockReset()
    h.api.post.mockReset()
    h.api.get.mockImplementation(async (url: string) => {
      if (url === '/a2a-payment/quote') return { data: QUOTE }
      if (url === '/a2a-payment/my-tokens') return { data: h.tokens }
      throw new Error(`unexpected GET ${url}`)
    })
    actingStore()
  })
  afterEach(() => { vi.useRealTimers() })

  it('the receipt says settled once the token settled', async () => {
    h.api.post.mockResolvedValueOnce(bought('tok_settles_1'))
    const w = mount(BuyServicePanel, { props: { did: target }, global: { stubs: { ActingContextNotice: true } } })
    await flushPromises()
    await buyOnce(w)
    expect(settlement(w), 'what /buy said, before anything is read').toContain('settling')
    h.tokens = [{ token_id: 'tok_settles_1', status: 'settled' }]
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(settlement(w)).toContain('settled')
    expect(settlement(w)).not.toContain('settling')
    expect(w.find('[data-testid="bsp-error"]').exists(), 'a settled purchase shows no error').toBe(false)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(tokenReads(), 'reading stops once the state is final').toBe(1)
    w.unmount()
  })

  it('a failed settlement reads as not paid, with what to do', async () => {
    h.api.post.mockResolvedValueOnce(bought('tok_fails_1'))
    const w = mount(BuyServicePanel, { props: { did: target }, global: { stubs: { ActingContextNotice: true } } })
    await flushPromises()
    await buyOnce(w)
    h.tokens = [{ token_id: 'tok_fails_1', status: 'settling' }]
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(settlement(w), 'still in flight: unchanged').toContain('settling')
    h.tokens = [{ token_id: 'tok_fails_1', status: 'FAILED' }]
    await vi.advanceTimersByTimeAsync(1000)
    await flushPromises()
    expect(settlement(w)).toContain('NOT PAID')
    expect(w.find('[data-testid="bsp-error"]').text()).toContain('tok_fail')
    w.unmount()
  })

  it('control: a token that never settles leaves "settling" and the reads stop at the bound', async () => {
    h.api.post.mockResolvedValueOnce(bought('tok_stuck_1'))
    const w = mount(BuyServicePanel, { props: { did: target }, global: { stubs: { ActingContextNotice: true } } })
    await flushPromises()
    await buyOnce(w)
    h.tokens = [{ token_id: 'tok_stuck_1', status: 'settling' }]
    await vi.advanceTimersByTimeAsync(60_000)
    await flushPromises()
    expect(settlement(w)).toContain('settling')
    expect(tokenReads(), 'bounded: eight reads, about 20 s').toBe(8)
    w.unmount()
  })

  it('a failed read changes nothing, and a newer purchase takes the receipt over', async () => {
    h.api.post.mockResolvedValueOnce(bought('tok_old_1')).mockResolvedValueOnce(bought('tok_new_1'))
    const w = mount(BuyServicePanel, { props: { did: target }, global: { stubs: { ActingContextNotice: true } } })
    await flushPromises()
    await buyOnce(w)
    h.api.get.mockImplementationOnce(async () => { throw new Error('502') })
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()
    expect(settlement(w), 'a failed read changes nothing').toContain('settling')
    await w.find('[data-testid="bsp-again"]').trigger('click')
    await flushPromises()
    h.tokens = [{ token_id: 'tok_old_1', status: 'failed' }, { token_id: 'tok_new_1', status: 'settled' }]
    await vi.advanceTimersByTimeAsync(10_000)
    await flushPromises()
    expect(settlement(w), 'the receipt is the newer purchase\'s').toContain('settled')
    expect(w.find('[data-testid="bsp-error"]').exists(), 'the older purchase\'s end does not reach the newer receipt').toBe(false)
    w.unmount()
  })
})
