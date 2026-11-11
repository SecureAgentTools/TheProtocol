import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, enableAutoUnmount } from '@vue/test-utils'
import fx from '@/components/quantum/__fixtures__/quantumWorkload.json'

/**
 * V0660 (e): the agent page shows the quantum card for an agent whose card carries the quantum workload extension,
 * where the frame serves it. Under off (no quantum_workloads block in the registry-config) the page is what it was:
 * no quantum section, and no request to /api/v1/quantum.
 */
const h = vi.hoisted(() => ({ lookupByDID: vi.fn() }))
vi.mock('@/services/api/fx', () => ({ fxService: { publicRate: vi.fn().mockResolvedValue({ available: true }) } }))
vi.mock('@/services/api/discovery', () => ({ discoveryService: { lookupByDID: h.lookupByDID } }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn() } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/composables/useFrames', async () => {
  const { computed } = await import('vue')
  return { useFrames: () => ({ localFx: computed(() => null), localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/composables/useCurrency', () => ({
  useCurrency: () => ({ currencyForItem: () => 'ECU', isForeignItem: () => false, localCurrency: { value: 'ECU' } }),
}))
vi.mock('@/composables/useEngageDoors', async () => {
  const { ref } = await import('vue')
  return { useEngageDoors: () => ({ doors: ref(null), draft: ref(null), homeRegistry: ref(null), loading: ref(false), reload: vi.fn() }) }
})
vi.mock('@/composables/useRegistryConfig', async (importOriginal) => {
  const { ref, computed } = await import('vue')
  const cfg = ref<Record<string, any>>({})
  return { ...(await importOriginal<object>()), useRegistryConfig: () => ({ config: computed(() => cfg.value) }), __cfg: cfg }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: false, token: null, user: null }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined) }), useRoute: () => ({ query: {}, path: '/' }) }))

import * as rc from '@/composables/useRegistryConfig'
import { _resetQuantumReads } from '@/services/api/quantum'
import AgentDetailModal from './AgentDetailModal.vue'

const cfg = (rc as any).__cfg
const fetchMock = vi.fn()
const BaseModal = { name: 'BaseModal', template: '<div><slot /><slot name="footer" /></div>' }
const opts = {
  props: { show: true, agentDid: fx.did },
  global: { stubs: { BaseModal, Icon: true, UserAvatar: true, SovereignRegistryCard: true, TrackRecordPanel: true, BuyServicePanel: true,
    EarnedMarkRing: { template: '<div><slot /></div>' }, Teleport: true, teleport: true, RouterLink: true } },
}
const agentWith = (rawCardData: Record<string, any>) => ({ id: 'a1', did: fx.did, name: 'Lattice Works', description: 'd',
  humanReadableId: 'eu/lattice', url: 'https://provider.example/a2a', type: 'service', status: 'active', tags: [], capabilities: {},
  authSchemes: [], provider: { name: 'Example Lab' }, version: '1.0.0', schemaVersion: '1.0', developerId: 2, developerVerified: false,
  createdAt: '2026-11-01T00:00:00Z', updatedAt: '2026-11-07T00:00:00Z', rawCardData, reputation_score: 50,
  liquid_balance: 0, staked_balance: 0, originRegistry: null, isFederated: false, settlement_currency: 'ECU', pricing: null, is_paid: false })

enableAutoUnmount(afterEach)

beforeEach(() => {
  _resetQuantumReads()
  fetchMock.mockReset().mockImplementation(() => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(fx.read) }))
  ;(globalThis as any).fetch = fetchMock
  h.lookupByDID.mockReset().mockResolvedValue(agentWith(fx.cardData))
  cfg.value = {}
})
const quantumCalls = () => fetchMock.mock.calls.filter((c) => String(c[0]).includes('/api/v1/quantum/'))

describe('the agent page and the quantum card', () => {
  it('under off: no quantum section and no quantum request, for an agent whose card carries the extension', async () => {
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(w.text()).toContain('Lattice Works')
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
    w.unmount()
  })

  it('served: the full quantum card, read through the route', async () => {
    cfg.value = { quantum_workloads: fx.registryBlock }
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    const card = w.find('[data-testid="qc-card"]')
    expect(card.exists()).toBe(true)
    expect(card.attributes('data-variant')).toBe('full')
    expect(quantumCalls()).toHaveLength(1)
    expect(w.findAll('[data-testid="qc-rung"]')).toHaveLength(3)
    w.unmount()
  })

  it('served, for an agent whose card carries no extension: no quantum section and no request', async () => {
    cfg.value = { quantum_workloads: fx.registryBlock }
    h.lookupByDID.mockResolvedValue(agentWith({ name: 'Plain', extensions: [] }))
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(w.find('[data-testid="qc-card"]').exists()).toBe(false)
    expect(quantumCalls()).toHaveLength(0)
    w.unmount()
  })
})
