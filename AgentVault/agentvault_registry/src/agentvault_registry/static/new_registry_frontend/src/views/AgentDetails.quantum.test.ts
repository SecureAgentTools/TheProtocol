import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'

/**
 * V0660 (e): the full agent view (route agent-details, agent/:agentId, the page the modal's door opens) shows the
 * quantum card on the same conditions as the modal: the agent's card carries the quantum workload extension and the
 * frame serves it (the registry-config's quantum_workloads block). Under off the page is what it was: no quantum
 * section and no request to /api/v1/quantum.
 */
const h = vi.hoisted(() => ({ agent: null as any }))
vi.mock('@/services/api/client', () => ({
  apiClient: {
    get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })),
    post: vi.fn().mockRejectedValue(new Error('no')), patch: vi.fn().mockRejectedValue(new Error('no')),
  },
}))
vi.mock('@/services/api/agentAuthz', () => ({ agentAuthzApi: { get: vi.fn().mockRejectedValue(new Error('no')) } }))
vi.mock('@/services/api/reputationBond', () => ({
  reputationBondApi: { getAgentReputation: vi.fn().mockRejectedValue(new Error('no')) },
  hiddenUntilBonded: () => false,
}))
vi.mock('@/stores/agents', () => ({
  useAgentStore: () => ({ currentAgent: h.agent, agents: [], fetchAgentById: vi.fn(), fetchMyAgents: vi.fn() }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: true, token: 't', user: { id: 2, is_admin: false } }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('@/composables/useCurrency', async () => {
  const { computed } = await import('vue')
  return { useCurrency: () => ({ localCurrency: computed(() => 'ECU') }) }
})
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined), replace: vi.fn() }),
  useRoute: () => ({ params: { agentId: fx.did }, query: {}, path: '/agent/' + fx.did }),
}))
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => {
  const { ref, computed } = await import('vue')
  const cfg = ref<Record<string, any>>({})
  return { ...(await importOriginal<object>()), useRegistryConfig: () => ({ config: computed(() => cfg.value) }), __cfg: cfg }
})

import * as rc from '@/composables/useRegistryConfig'
import { _resetQuantumReads } from '@/services/api/quantum'
import AgentDetails from './AgentDetails.vue'

const cfg = (rc as any).__cfg
const fetchMock = vi.fn()
const stubs = { Icon: true, ZKPVerifiedBadge: true, AgentLineageTree: true, AgentAccessPanel: true, BondMaturityBar: true,
  TrackRecordPanel: true, ReadFailedNotice: true, UserAvatar: true, RouterLink: true }
const agentWith = (cardData: Record<string, any>) => ({ id: 'a1', did: fx.did, name: 'Lattice Works', description: 'd',
  status: 'active', created_at: '2026-11-01T00:00:00Z', last_active_at: null, liquid_balance: 0, staked_balance: 0,
  reputation_score: 50, card_data: cardData })
const quantumCalls = () => fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/v1/quantum/'))

enableAutoUnmount(afterEach)

beforeEach(() => {
  _resetQuantumReads()
  fetchMock.mockReset().mockImplementation(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fx.read) }))
  ;(globalThis as any).fetch = fetchMock
  h.agent = agentWith(fx.cardData)
  cfg.value = {}
})

describe('the full agent view and the quantum card', () => {
  it('under off: no quantum section and no quantum request, for an agent whose card carries the extension', async () => {
    const w = mount(AgentDetails, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('Lattice Works')
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
  })

  it('served: the full quantum card on the agent view, read through the route once', async () => {
    cfg.value = { quantum_workloads: fx.registryBlock }
    const w = mount(AgentDetails, { global: { stubs } })
    await flushPromises()
    const card = w.find('[data-testid="qc-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-variant')).toBe('full')
    expect(quantumCalls()).toHaveLength(1)
    expect(w.findAll('[data-testid="qc-rung"]')).toHaveLength(3)
  })

  it('served, for an agent whose card carries no extension: no quantum section and no request', async () => {
    cfg.value = { quantum_workloads: fx.registryBlock }
    h.agent = agentWith({ name: 'Plain', extensions: [] })
    const w = mount(AgentDetails, { global: { stubs } })
    await flushPromises()
    expect(w.text()).toContain('Lattice Works')
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
  })
})
