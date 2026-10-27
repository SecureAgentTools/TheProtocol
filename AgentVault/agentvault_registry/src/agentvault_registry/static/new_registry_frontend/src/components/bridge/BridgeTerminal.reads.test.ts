/**
 * §FESUITE (V0577): the bridge terminal's DISCOVERY lane searches the federation and promises its zero: "Nothing matched.
 * The network is searched whole, so this is a real zero." A search that got no answer drew exactly that sentence under
 * its own error. The GUILD lane's open board drew "No open work on this registry right now." over a failed read. Both
 * now say the read failed and offer it again; answers of none still say none.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { AxiosError } from 'axios'

const h = vi.hoisted(() => ({ searchAgents: vi.fn(), board: vi.fn() }))
vi.mock('@/services/api/discovery', () => ({ discoveryService: { searchAgents: h.searchAgents } }))
vi.mock('@/services/api/guild', () => ({ guildApi: { board: h.board, bid: vi.fn(), post: vi.fn() } }))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: {} }))
vi.mock('@/services/api/chat', () => ({ chatApi: {} }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => null }))
// acting as an agent: the guild lane is read and bid on as one
vi.mock('@/stores/auth', () => ({
  useAuthStore: () => ({ agentToken: 'agent.jwt', activeAgent: { did: 'did:theprotocol:a1', name: 'Agent One' }, token: null }),
}))
vi.mock('@/stores/staking', () => ({
  useStakingStore: () => ({ positions: [], pendingRewards: '0', fetchMyStakingStats: vi.fn(), fetchPendingRewards: vi.fn() }),
}))
vi.mock('@/composables/useSenateLane', () => ({
  useSenateLane: () => ({ myVoted: ref({}), openProposals: ref([]), loaded: ref(false), load: vi.fn(async () => ({ ok: true })),
    vote: vi.fn(), voteMember: vi.fn() }),
}))
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useRegistryConfig: () => ({ config: ref(null) }),
}))
vi.mock('@/composables/useMemberVoteFlow', () => ({
  useMemberVoteFlow: () => ({ approved: ref(false), busy: ref(false), cancel: vi.fn(), code: ref(''), start: vi.fn(),
    stepUp: ref(null), stepUpError: ref('') }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn(async () => {}) }) }))

import BridgeTerminal from './BridgeTerminal.vue'

const noAnswer = () => new AxiosError('Network Error', 'ERR_NETWORK')
const stubs = { AgentDetailModal: true, AssistantDock: true, StepUpConfirm: true }

describe('the bridge terminal when a lane read fails', () => {
  beforeEach(() => { h.searchAgents.mockReset(); h.board.mockReset() })

  it('a failed federation search is not "a real zero", and searches again', async () => {
    h.searchAgents.mockRejectedValue(noAnswer())
    const w = mount(BridgeTerminal, { props: { lane: 'discovery' }, global: { stubs } })
    await w.find('form.bterm-row').trigger('submit')
    await flushPromises()
    expect(w.text(), 'promised a real zero over a search that never answered').not.toContain('this is a real zero')
    const notice = w.find('[data-testid="term-search-failed"]')
    expect(notice.exists()).toBe(true)

    h.searchAgents.mockResolvedValue({ results: [] })
    await notice.find('[data-testid="read-failed-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="term-search-failed"]').exists()).toBe(false)
    expect(w.text()).toContain('this is a real zero')
  })

  it('a failed open-board read is not "No open work on this registry right now."', async () => {
    h.board.mockRejectedValue(noAnswer())
    const w = mount(BridgeTerminal, { props: { lane: 'guild' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).not.toContain('No open work on this registry right now.')
    expect(w.find('[data-testid="term-board-failed"]').exists()).toBe(true)
  })

  it('an answered empty board still says there is no open work', async () => {
    h.board.mockResolvedValue({ orders: [] })
    const w = mount(BridgeTerminal, { props: { lane: 'guild' }, global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('No open work on this registry right now.')
  })
})
