import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { cardAuthSchemes } from '@/services/cardAuth'

/**
 * §CARDAUTH (2026-10-23, agentvault2-56): an agent listed free that sells access its own way declares an API key in its
 * A2A v1.0 card (securitySchemes). The modal read only the legacy authSchemes list, so it showed the agent as an open,
 * free endpoint: no Authentication row, a curl example without the key header. Journal 52's worked example, Sundial.
 * Control: a legacy card with an open endpoint reads as before.
 */
const h = vi.hoisted(() => ({ lookupByDID: vi.fn() }))
vi.mock('@/services/api/fx', () => ({ fxService: { publicRate: vi.fn().mockResolvedValue(null) } }))
vi.mock('@/services/api/discovery', () => ({ discoveryService: { lookupByDID: h.lookupByDID } }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn() } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/composables/useFrames', async () => {
  const { computed } = await import('vue')
  return { useFrames: () => ({ localFx: computed(() => null), localCurrency: computed(() => 'SBXA') }) }
})
vi.mock('@/composables/useCurrency', () => ({
  useCurrency: () => ({ currencyForItem: () => 'SBXA', isForeignItem: () => false, localCurrency: { value: 'SBXA' } }),
}))
vi.mock('@/composables/useEngageDoors', async () => {
  const { ref } = await import('vue')
  return { useEngageDoors: () => ({ doors: ref(null), draft: ref(null), homeRegistry: ref(null), loading: ref(false), reload: vi.fn() }) }
})
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAuthenticated: true, token: 'tok', user: { developer_id: 1 } }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn(), showInfo: vi.fn(), showWarning: vi.fn() }) }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn().mockResolvedValue(undefined) }), useRoute: () => ({ query: {}, path: '/' }) }))

import AgentDetailModal from './AgentDetailModal.vue'

const BaseModal = { name: 'BaseModal', template: '<div><slot /><slot name="footer" /></div>' }
const opts = {
  props: { show: true, agentDid: 'did:theprotocol:sundial' },
  global: { stubs: { BaseModal, Icon: true, UserAvatar: true, SovereignRegistryCard: true, TrackRecordPanel: true, BuyServicePanel: true,
    EarnedMarkRing: { template: '<div><slot /></div>' }, Teleport: true, teleport: true, RouterLink: true } },
}
const CARD = {
  name: 'Sundial', supportedInterfaces: [{ protocolBinding: 'JSONRPC', protocolVersion: '1.0', url: 'https://sbx.example/agents/sundial/a2a' }],
  securitySchemes: { sundial_key: { type: 'apiKey', in: 'header', name: 'X-Sundial-Key',
    description: 'Get a key at https://sbx.example/agents/sundial/keys: 100 calls a day on the free plan.' } },
  security: [{ sundial_key: [] }],
}
const agent = (cd: Record<string, any>) => ({ id: 'c1', did: 'did:theprotocol:sundial', name: 'Sundial', description: 'time',
  humanReadableId: 'sundial', url: '', type: 'service', status: 'active', tags: [], capabilities: {},
  authSchemes: cardAuthSchemes(cd), provider: { name: 'Sundial' }, version: '1.0.0', schemaVersion: '1.0', developerId: 3,
  developerVerified: false, createdAt: '2026-10-23T00:00:00Z', updatedAt: '2026-10-23T00:00:00Z', rawCardData: cd,
  reputation_score: 0, liquid_balance: 0, staked_balance: 0, originRegistry: 'Local', isFederated: false,
  pricing: null, is_paid: false })

describe("the modal shows the credential a free agent's own card asks for", () => {
  beforeEach(() => { h.lookupByDID.mockReset() })

  it('names the header and carries the card\'s own words; the free note points at it', async () => {
    h.lookupByDID.mockResolvedValue(agent(CARD))
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    const auth = w.find('[data-testid="adm-auth"]')
    expect(auth.exists(), 'an Authentication row').toBe(true)
    expect(auth.text()).toContain('API key')
    expect(auth.text()).toContain('X-Sundial-Key')
    expect(w.find('[data-testid="adm-auth-desc"]').text()).toContain('100 calls a day')
    expect(w.find('[data-testid="adm-free-own-auth"]').exists(), 'the free note says the agent asks for its own').toBe(true)
    w.unmount()
  })

  it('an open legacy card reads as before (the control)', async () => {
    h.lookupByDID.mockResolvedValue(agent({ name: 'Sundial', authSchemes: [{ scheme: 'none' }] }))
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(w.find('[data-testid="adm-auth"]').text()).toContain('Open endpoint')
    expect(w.find('[data-testid="adm-free-own-auth"]').exists()).toBe(false)
    expect(w.text()).toContain('Nothing to authorize or settle before calling it')
    w.unmount()
  })
})
