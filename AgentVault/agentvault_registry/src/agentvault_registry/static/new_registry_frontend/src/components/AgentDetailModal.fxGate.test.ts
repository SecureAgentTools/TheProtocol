import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-05, agentvault2-09): the agent card's hire gate for an agent that settles in another currency.
 * fxService.publicRate answers null for a FAILED read and { available: false } on a frame without FX; with no card read
 * either, the gate said "enable FX on your registry to pay" and disabled Hire: an "FX off" nobody read (it also flashed
 * while the read was out). An unread FX says so now (Try again) and Hire waits; an answered "off" still locks Hire and an
 * answered "on" still offers it (the controls).
 */
const h = vi.hoisted(() => ({ publicRate: vi.fn(), lookupByDID: vi.fn(), localFx: null as unknown }))
vi.mock('@/services/api/fx', () => ({ fxService: { publicRate: h.publicRate } }))
vi.mock('@/services/api/discovery', () => ({ discoveryService: { lookupByDID: h.lookupByDID } }))
vi.mock('@/services/api/client', () => ({ apiClient: { get: vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })), post: vi.fn() } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: {} }))
vi.mock('@/composables/useFrames', async () => {
  const { computed } = await import('vue')
  return { useFrames: () => ({ localFx: computed(() => h.localFx), localCurrency: computed(() => 'ECU') }) }
})
vi.mock('@/composables/useCurrency', () => ({
  useCurrency: () => ({ currencyForItem: () => 'ACU', isForeignItem: () => true, localCurrency: { value: 'ECU' } }),
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
  props: { show: true, agentDid: 'did:theprotocol:asia-agent' },
  global: { stubs: { BaseModal, Icon: true, UserAvatar: true, SovereignRegistryCard: true, TrackRecordPanel: true, BuyServicePanel: true,
    EarnedMarkRing: { template: '<div><slot /></div>' }, Teleport: true, teleport: true, RouterLink: true } },
}
const AGENT = { id: 'a1', did: 'did:theprotocol:asia-agent', name: 'Atlas', description: 'd', humanReadableId: 'asia/atlas',
  url: 'https://asia.example/a2a', type: 'service', status: 'active', tags: [], capabilities: {}, authSchemes: [],
  provider: { name: 'ASIA' }, version: '1.0.0', schemaVersion: '1.0', developerId: 2, developerVerified: false,
  createdAt: '2026-10-01T00:00:00Z', updatedAt: '2026-10-05T00:00:00Z', rawCardData: {}, reputation_score: 50,
  liquid_balance: 0, staked_balance: 0, originRegistry: 'ASIA', isFederated: true, settlement_currency: 'ACU',
  trust_domain: 'asia.example', pricing: { model: 'per_request', currency: 'ACU', base_rate: '2', payment_required: true },
  is_paid: true }
const engage = (w: ReturnType<typeof mount>) => w.find('[data-testid="adm-engage-go"]')

describe('the hire gate tells "FX off" from "FX not read"', () => {
  beforeEach(() => {
    h.publicRate.mockReset()
    h.lookupByDID.mockReset().mockResolvedValue(AGENT)
    h.localFx = null
  })

  it('a failed FX read with no card answer: no "enable FX", Hire waits, the note says FX could not be checked; Try again reads it', async () => {
    h.publicRate.mockResolvedValueOnce(null)
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(w.text()).not.toContain('enable FX on your registry to pay')
    expect(w.text()).not.toContain('enable FX to pay')
    expect(w.find('[data-testid="adm-fx-unread"]').exists(), 'the note says FX was not read').toBe(true)
    expect(engage(w).attributes('disabled'), 'Hire waits for an answer').toBeDefined()
    h.publicRate.mockResolvedValueOnce({ available: true, local_currency: 'ECU', peer_currency: 'ACU' })
    await w.find('[data-testid="adm-fx-retry"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-testid="adm-fx-unread"]').exists()).toBe(false)
    expect(engage(w).attributes('disabled')).toBeUndefined()
    expect(w.text()).toContain('pays via FX')
    w.unmount()
  })

  it('while the read is out: no "enable FX" flash', async () => {
    h.publicRate.mockReturnValueOnce(new Promise(() => {}))
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(w.text()).not.toContain('enable FX')
    expect(engage(w).attributes('disabled')).toBeDefined()
    w.unmount()
  })

  it('control: an answered "off" locks Hire and says enable FX; an answered "on" offers it', async () => {
    h.publicRate.mockResolvedValueOnce({ available: false })
    const w = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(w.text()).toContain('enable FX on your registry to pay')
    expect(engage(w).attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="adm-fx-unread"]').exists()).toBe(false)
    w.unmount()
    h.publicRate.mockResolvedValueOnce({ available: true })
    const w2 = mount(AgentDetailModal, opts)
    await flushPromises()
    expect(engage(w2).attributes('disabled')).toBeUndefined()
    expect(w2.text()).toContain('pays via FX')
    w2.unmount()
  })
})
