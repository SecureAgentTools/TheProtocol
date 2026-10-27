/**
 * §FESUITE (V0577): an agent's profile page starts its reputation at 0 · Unranked. A failed reputation read
 * (/teg/agents/{did}/reputation) fell back to the score on the agent row, which an agent that is not yours does not
 * have, so the page kept its starting values: "0 rep · Unranked" in the header, "0 / 100" in the tabs, also while the
 * read was in flight. They now read "—" until a read (or the agent's own row) answered for this agent.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const DID = 'did:theprotocol:stranger-1'
const h = vi.hoisted(() => ({ reputation: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { did: 'did:theprotocol:stranger-1' }, query: {} }),
  useRouter: () => ({ push: vi.fn(async () => {}), replace: vi.fn(async () => {}) }),
}))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, isAuthenticated: true, activeAgent: null }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('@/services/api/agentCards', () => ({
  agentCardsApi: { searchCards: async () => [{ agent_did: 'did:theprotocol:stranger-1', name: 'Stranger', status: 'active' }] },
}))
vi.mock('@/services/api/evals', () => ({ evalsApi: { getAgentResults: async () => [] } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: vi.fn(async (url: string) => {
      if (url.endsWith('/reputation')) return h.reputation()
      if (url === '/developers/me/agents') return { data: [] }   // not yours: the row carries no score
      return { data: {} }
    }),
    post: vi.fn(),
  },
}))

import AgentProfile from './AgentProfile.vue'

async function profile() {
  const w = shallowMount(AgentProfile, { global: { stubs: { Icon: true } } })
  for (let i = 0; i < 3; i++) await flushPromises()
  return w
}
const headerRep = (w: any) => w.find('.ap-meta-strong').text()
const headerTier = (w: any) => w.find('.ap-meta-tier').text()

describe("an agent profile's reputation when its read fails", () => {
  beforeEach(() => { h.reputation.mockReset(); vi.spyOn(console, 'error').mockImplementation(() => {}) })

  it('reads "—", never "0 rep · Unranked", for an agent whose reputation could not be read', async () => {
    h.reputation.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    const w = await profile()
    expect(w.find('.ap-meta').exists(), 'the profile header did not render').toBe(true)
    expect([headerRep(w), headerTier(w)], 'drew 0 · Unranked over a failed read').toEqual(['—', '—'])
  })

  it('shows the figures the registry answered', async () => {
    h.reputation.mockResolvedValue({ data: { reputation_score: 72, reputation_tier: 'Silver', last_updated: null } })
    const w = await profile()
    expect([headerRep(w), headerTier(w)]).toEqual(['72', 'Silver'])
  })
})
