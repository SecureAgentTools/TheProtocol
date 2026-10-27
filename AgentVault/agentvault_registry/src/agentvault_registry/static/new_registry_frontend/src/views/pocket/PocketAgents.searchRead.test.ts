/**
 * §FESUITE (V0578): Pocket's My agents searches the whole fleet on the server (/developers/me/agents?q=). A search the
 * registry did not answer kept the earlier list, filtered it on the phone, found nothing and said "No agents match "x"."
 * (the error line came second and never showed), and the header count read "0 / 100"; a failed first read showed a "0"
 * count beside "Could not load your agents". "No agents match" and the count are now what an answered read says.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { computed, reactive, ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ getMyAgents: vi.fn() }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: (...a: unknown[]) => h.getMyAgents(...a) } }))
vi.mock('@/services/api/developers', () => ({ developerApi: { getAgentBalancesBatch: async () => ({ balances: {} }) } }))
vi.mock('@/services/pocketMarks', () => ({ marksForMany: () => {} }))
vi.mock('vue-router', () => ({ useRoute: () => reactive({ query: {} }), useRouter: () => ({ replace: vi.fn(async () => {}), push: vi.fn(async () => {}) }) }))
vi.mock('@/composables/usePullToRefresh', () => ({
  usePullToRefresh: () => ({ ptrH: ref(0), ptrArmed: ref(false), onTouchStart() {}, onTouchMove() {}, onTouchEnd() {} }),
}))
vi.mock('@/composables/useCurrency', () => ({ useCurrency: () => ({ amount: (v: unknown) => String(v), localCurrency: computed(() => 'ECU') }) }))
vi.mock('@/composables/useActingContext', () => ({ useActingContext: () => ({ actingCurrencyLabel: computed(() => 'ECU') }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => reactive({ agentCreatedTick: 0, openQuickAgentModal: () => {} }) }))

import PocketAgents from './PocketAgents.vue'

const LIST = [
  { did: 'did:theprotocol:a1', name: 'Alpha', status: 'active', liquid_balance: 10 },
  { did: 'did:theprotocol:b2', name: 'Beta', status: 'active', liquid_balance: 5 },
]
const badGateway = () => new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', undefined, undefined,
  { status: 502, statusText: '', data: {}, headers: {}, config: {} } as any)

async function page() {
  const w = mount(PocketAgents, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}

describe("Pocket's My agents over a read the registry did not answer", () => {
  beforeEach(() => { h.getMyAgents.mockReset(); vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] }) })

  it('a failed fleet search never says "No agents match"', async () => {
    h.getMyAgents.mockResolvedValueOnce(LIST)
    const w = await page()
    h.getMyAgents.mockRejectedValueOnce(badGateway())
    await w.find('.pg-search input').setValue('zeta')
    vi.advanceTimersByTime(400)
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(h.getMyAgents).toHaveBeenLastCalledWith({ limit: 100, q: 'zeta' })
    expect(w.text(), 'said "no agents match" over a fleet search that failed').not.toContain('No agents match')
    expect(w.find('[data-testid="pg-err"]').exists()).toBe(true)
    vi.useRealTimers()
  })

  it('a failed first read shows no "0" count beside the error', async () => {
    h.getMyAgents.mockRejectedValueOnce(badGateway())
    const w = await page()
    expect(w.find('[data-testid="pg-err"]').exists()).toBe(true)
    expect(w.find('.pg-count').exists(), 'drew a 0 count over a read that failed').toBe(false)
    vi.useRealTimers()
  })

  it('an answered search with no match says so, with its count', async () => {
    h.getMyAgents.mockResolvedValueOnce(LIST)
    const w = await page()
    h.getMyAgents.mockResolvedValueOnce([])
    await w.find('.pg-search input').setValue('zeta')
    vi.advanceTimersByTime(400)
    for (let i = 0; i < 4; i++) await flushPromises()
    expect(w.text()).toContain('No agents match')
    expect(w.find('.pg-count').exists()).toBe(true)
    vi.useRealTimers()
  })
})
