/**
 * V0641 (agentvault2-66's review of be05537f, agentvault2-5b, 2026-10-25): the buy door acts as the store's acting agent.
 * Once usePocketAgent lists the agents you own here (viaSession), a member with several of them, none chosen and no
 * secret saved, passed the "no agent" gate while restoreActing (rightly) chose none: the quote went out with no agent's
 * token and its 401 was shown as the reason. The door now asks for a choice and calls nothing, and prices the service
 * once the member chose one. The store, the vault and the API are doubles; the composable is the real one.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, stored: {} as Record<string, any>, api: { get: vi.fn(), post: vi.fn() } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/agentCredentialsStore', () => ({
  agentCredentialsStore: { getAllCredentials: () => h.stored, isSealedLocked: () => false },
}))
vi.mock('@/services/credentialVault', () => ({ credentialVault: { onChange: () => {} } }))
vi.mock('@/services/api/client', () => ({ default: h.api, apiClient: h.api }))

import BuyServicePanel from './BuyServicePanel.vue'

const did = (n: number) => `did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-00000000004${n}`
const mine = (n: number) => ({ did: did(n), name: `mine ${n}`, owned: true, status: 'active' })
const target = 'did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-000000000050'

function store(rows: any[]) {
  h.auth = reactive({
    availableAgents: rows, activeAgent: null as any, agentToken: null as any,
    // the store's rule (stores/auth.ts canActAs): yours here needs no secret
    canActAs: (a: any) => !!a && (!!a.owned || !!(a.client_id && a.client_secret)),
    authenticateAsAgent: vi.fn(async (row: any) => { h.auth.activeAgent = row; h.auth.agentToken = 'agent.jwt'; return true }),
  })
  return h.auth
}

const mountPanel = () => mount(BuyServicePanel, { props: { did: target }, global: { stubs: { ActingContextNotice: true } } })

describe('the buy door and which agent it acts as', () => {
  beforeEach(() => {
    h.stored = {}
    localStorage.clear()
    h.api.get.mockReset()
    h.api.post.mockReset()
    h.api.get.mockResolvedValue({ data: {
      payment_required: true, can_buy: true, recommended_amount: '0.5', your_currency: 'SBXA', same_currency: true,
    } })
  })

  it('with several of yours and none chosen, it asks for a choice and calls nothing; a choice prices it', async () => {
    const auth = store([mine(1), mine(2)])
    const w = mountPanel()
    await flushPromises()
    expect(h.api.get, 'no quote sent without an acting agent').not.toHaveBeenCalled()
    expect(auth.authenticateAsAgent, 'the door does not choose for the member').not.toHaveBeenCalled()
    expect(w.find('[data-testid="bsp-quote-error"]').text()).toContain('choose one in the agent switcher')
    // the member picks one in the header switcher (the store's own switch)
    auth.activeAgent = mine(2)
    auth.agentToken = 'agent.jwt'
    await flushPromises()
    expect(h.api.get).toHaveBeenCalledWith('/a2a-payment/quote', expect.objectContaining({ params: { target_agent_did: target } }))
    expect(w.find('[data-testid="bsp-price-yours"]').text()).toContain('0.5 SBXA')
    w.unmount()
  })

  it('control: your only agent here is signed in through your session and the service is priced', async () => {
    const auth = store([mine(1)])
    const w = mountPanel()
    await flushPromises()
    expect(auth.authenticateAsAgent).toHaveBeenCalledTimes(1)
    expect(auth.authenticateAsAgent.mock.calls[0][0]).toMatchObject({ did: did(1), owned: true })
    expect(h.api.get).toHaveBeenCalledTimes(1)
    expect(w.find('[data-testid="bsp-price-yours"]').exists()).toBe(true)
    w.unmount()
  })
})
