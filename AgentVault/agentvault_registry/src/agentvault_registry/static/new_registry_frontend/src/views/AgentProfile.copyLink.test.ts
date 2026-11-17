/**
 * V0662 (order gwo_16d8fb21303f269406eb772f, his suggestion 4): the agent's profile copies a link to the agent (this
 * console, #/agent-profile/<did>, the DID encoded). Red on f569f6a6e: no copy link on the profile.
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'

const DID = 'did:theprotocol:linked-agent-1'
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { did: 'did:theprotocol:linked-agent-1' }, query: {} }),
  useRouter: () => ({ push: vi.fn(async () => {}), replace: vi.fn(async () => {}) }),
}))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, isAuthenticated: true, activeAgent: null }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('@/services/api/agentCards', () => ({ agentCardsApi: { searchCards: async () => [] } }))
vi.mock('@/services/api/evals', () => ({ evalsApi: { getAgentResults: async () => [] } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: vi.fn(async (url: string) => {
      if (url === '/developers/me/agents') return { data: [] }
      if (url.startsWith('/agents/by-did/')) return { data: { did: DID, name: 'Linked Agent', status: 'active' } }
      return { data: {} }
    }),
    post: vi.fn(),
  },
}))

import AgentProfile from './AgentProfile.vue'

describe('a link to the agent', () => {
  it('the profile\'s hero has a copy button holding this console\'s link to the agent', async () => {
    const w = shallowMount(AgentProfile, { global: { stubs: { Icon: true } } })
    try {
      for (let i = 0; i < 3; i++) await flushPromises()
      const copy = w.findComponent({ name: 'CopyButton' })
      expect(copy.exists(), 'a CopyButton in the profile').toBe(true)
      expect(copy.props('value')).toBe(`${window.location.origin}${window.location.pathname}#/agent-profile/${encodeURIComponent(DID)}`)
      expect(copy.attributes('data-testid')).toBe('ap-copy-link')
    } finally { w.unmount() }
  })
})
