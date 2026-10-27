/**
 * §FESUITE (V0577): an agent's profile page found an agent that is not yours with /agent-cards?search=<did>, and that
 * search matches names and descriptions, never a DID. Every such agent (the Forge's lineage nodes and the command
 * palette's DID lookup open them) read "Agent Not Found" and the page left for /discover. It now reads the agent by its DID
 * (GET /agents/by-did); "Agent Not Found" only after the registry answered that there is none, and a lookup that got no
 * answer says "Load Failed" instead.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, shallowMount } from '@vue/test-utils'
import { AxiosError } from 'axios'

const DID = 'did:theprotocol:someone-elses-1'
const h = vi.hoisted(() => ({ byDid: vi.fn(), push: vi.fn(async () => {}), showError: vi.fn() }))
vi.mock('vue-router', () => ({
  useRoute: () => ({ params: { did: 'did:theprotocol:someone-elses-1' }, query: {} }),
  useRouter: () => ({ push: h.push, replace: vi.fn(async () => {}) }),
}))
vi.mock('@/stores/agents', () => ({ useAgentStore: () => ({ agents: [], fetchMyAgents: async () => {} }) }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: { id: 7 }, isAuthenticated: true, activeAgent: null }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: h.showError, showSuccess: vi.fn(), showWarning: vi.fn() }) }))
// the card search never matches a DID (it searches names and descriptions)
vi.mock('@/services/api/agentCards', () => ({ agentCardsApi: { searchCards: async () => [] } }))
vi.mock('@/services/api/evals', () => ({ evalsApi: { getAgentResults: async () => [] } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: vi.fn(async (url: string) => {
      if (url === '/developers/me/agents') return { data: [] }   // not yours
      if (url.startsWith('/agents/by-did/')) return h.byDid()
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
const errors = () => h.showError.mock.calls.map((c: any[]) => c[0])
const status = (s: number) => new AxiosError(`Request failed with status code ${s}`, s >= 500 ? 'ERR_BAD_RESPONSE' : 'ERR_BAD_REQUEST',
  undefined, undefined, { status: s, statusText: '', data: {}, headers: {}, config: {} } as any)

describe("an agent's profile when the agent is not yours", () => {
  beforeEach(() => { h.byDid.mockReset(); h.push.mockClear(); h.showError.mockClear(); vi.spyOn(console, 'error').mockImplementation(() => {}) })

  it('opens it, read by its DID, never "Agent Not Found"', async () => {
    h.byDid.mockResolvedValue({ data: { did: DID, name: 'Someone Else', description: 'not mine', status: 'active', reputation_score: 42 } })
    const w = await profile()
    expect(errors(), 'said "Agent Not Found" about an agent the registry serves').not.toContain('Agent Not Found')
    expect(h.push).not.toHaveBeenCalledWith('/discover')
    expect(w.find('.ap-meta').exists()).toBe(true)
    expect(w.text()).toContain('Someone Else')
  })

  it('"Agent Not Found" only once the registry answered there is none', async () => {
    h.byDid.mockRejectedValue(status(404))
    await profile()
    expect(errors()).toContain('Agent Not Found')
    expect(h.push).toHaveBeenCalledWith('/discover')
  })

  it('a lookup that got no answer says "Load Failed", never "Agent Not Found"', async () => {
    h.byDid.mockRejectedValue(new AxiosError('Network Error', 'ERR_NETWORK'))
    await profile()
    expect(errors()).not.toContain('Agent Not Found')
    expect(errors()).toContain('Load Failed')
    expect(h.push).not.toHaveBeenCalledWith('/discover')
  })
})
