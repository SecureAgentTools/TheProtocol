/**
 * §FESUITE (V0578): NEEDS YOU emits its count to the shells that mount it (Pocket's shell puts it on the installed app's
 * icon). With every read that would count something failed, the count was 0 ("absent until a source has answered" held
 * only while loading), so the shell cleared the icon badge: the phone said nothing needs you over reads that never
 * answered. The count is null now when nothing answered, and the panel draws no all-clear.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'

const h = vi.hoisted(() => ({
  getProposals: vi.fn(), getMyVotes: vi.fn(), mine: vi.fn(), guildMine: vi.fn(), getMyStakingStats: vi.fn(),
  getAttestationsByDid: vi.fn(), getAgentDisputes: vi.fn(), listPending: vi.fn(),
}))
vi.mock('@/services/api/governance', () => ({ governanceApi: { getProposals: h.getProposals, getMyVotes: h.getMyVotes } }))
vi.mock('@/services/api/contractsV2', () => ({ contractsV2Api: { mine: h.mine } }))
vi.mock('@/services/api/guild', () => ({ guildApi: { mine: h.guildMine } }))
vi.mock('@/services/api/staking', () => ({ stakingApi: { getMyStakingStats: h.getMyStakingStats } }))
vi.mock('@/services/api/attestations', () => ({ attestationsApi: { getAttestationsByDid: h.getAttestationsByDid } }))
vi.mock('@/services/api/disputes', () => ({ disputesApi: { getAgentDisputes: h.getAgentDisputes } }))
vi.mock('@/services/api/fundingAdmin', () => ({ fundingAdminService: { listPending: h.listPending } }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:test:agent-1', name: 'Agent One' }, isAdmin: false }) }))
vi.mock('@/stores/notifications', () => ({ useNotificationStore: () => ({ unreadCount: 0, items: [] }) }))
vi.mock('@/stores/sessions', () => ({ useSessionHub: () => ({ ensureAgentToken: async () => 'far.jwt', lastAgentError: {} }) }))
vi.mock('@/composables/usePrivacy', () => ({ usePrivacy: () => ({ money: (x: unknown) => String(x) }) }))
vi.mock('@/composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string, f?: unknown) => (typeof f === 'string' ? f : k), tp: (k: string, f?: unknown) => (typeof f === 'string' ? f : k) }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/agentCredentialsStore', () => ({
  agentCredentialsStore: {
    isSealedLocked: () => false,
    // one agent homed on another registry: the panel asks that registry what waits there
    getAllCredentials: () => ({}),   // no agent elsewhere: only this registry's reads count
  },
}))
vi.mock('@/composables/useFrameManifest', () => ({ currentFrameManifest: () => null }))
vi.mock('@/services/frameManifest', () => ({ entryByOrigin: () => null }))
vi.mock('@/composables/useFocusTrap', () => ({ useFocusTrap: () => {} }))
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))

import BridgeAttention from './BridgeAttention.vue'

const badGateway = () => Object.assign(new Error('Request failed with status code 502'), { response: { status: 502 } })

beforeEach(() => {
  for (const f of Object.values(h)) { f.mockReset(); f.mockRejectedValue(badGateway()) }
})

describe('the NEEDS YOU count when nothing answered', () => {
  it('is null (not 0) when every read failed, and the panel draws no all-clear', async () => {
    const w = mount(BridgeAttention, { props: { show: false }, global: { stubs: { Icon: true } } })
    await w.setProps({ show: true })
    for (let i = 0; i < 6; i++) await flushPromises()
    const counts = (w.emitted('count') || []).map(e => e[0])
    expect(counts.length).toBeGreaterThan(0)
    expect(counts[counts.length - 1], 'emitted 0 (nothing needs you) over reads that all failed').toBeNull()
    expect(w.find('[data-testid="bat-clear"]').exists()).toBe(false)
  })

  it('is 0 when the reads answered with nothing', async () => {
    for (const f of Object.values(h)) { f.mockReset(); f.mockResolvedValue([]) }
    h.getMyStakingStats.mockResolvedValue({})
    const w = mount(BridgeAttention, { props: { show: false }, global: { stubs: { Icon: true } } })
    await w.setProps({ show: true })
    for (let i = 0; i < 6; i++) await flushPromises()
    const counts = (w.emitted('count') || []).map(e => e[0])
    expect(counts[counts.length - 1]).toBe(0)
    expect(w.find('[data-testid="bat-clear"]').text()).toBe('Nothing is waiting on you.')
  })
})
