import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'

/**
 * §FESUITE (2026-10-04, the leave sweep on V0572, fes-20261004T171222Z-9caf): the attention panel (Pocket's shell and the
 * bridge mount it) defers its first load by 1.2 s. The timer was never cleared, so leaving within 1.2 s ran six reads
 * from a panel that was already gone, and a failed one logged "Failed to fetch staking stats" on the next page. The
 * control proves the deferred load does run while the panel stays; the case proves leaving first asks nothing.
 */
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
vi.mock('@/stores/sessions', () => ({ useSessionHub: () => ({}) }))
vi.mock('@/composables/usePrivacy', () => ({ usePrivacy: () => ({ money: (x: unknown) => String(x) }) }))
vi.mock('@/composables/useI18n', () => ({
  useI18n: () => ({ t: (k: string, f?: unknown) => (typeof f === 'string' ? f : k), tp: (k: string, f?: unknown) => (typeof f === 'string' ? f : k) }),
}))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/agentCredentialsStore', () => ({ agentCredentialsStore: { isSealedLocked: () => false, getAllCredentials: () => [] } }))
vi.mock('@/composables/useFrameManifest', () => ({ currentFrameManifest: () => null }))
vi.mock('@/services/frameManifest', () => ({ entryByOrigin: () => null }))
vi.mock('@/composables/useFocusTrap', () => ({ useFocusTrap: () => {} }))
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))

import BridgeAttention from './BridgeAttention.vue'

function mountPanel() {
  return mount(BridgeAttention, { props: { show: false }, global: { stubs: { Icon: true } } })
}

beforeEach(() => {
  vi.useFakeTimers()
  for (const f of Object.values(h)) { f.mockReset(); f.mockResolvedValue([]) }
})
afterEach(() => { vi.useRealTimers() })

describe('BridgeAttention leaves nothing running', () => {
  it('runs its deferred first load while it stays mounted (the control)', async () => {
    const w = mountPanel()
    await vi.advanceTimersByTimeAsync(1300)
    expect(h.getProposals).toHaveBeenCalledTimes(1)
    expect(h.getMyStakingStats).toHaveBeenCalledTimes(1)
    expect(h.mine).toHaveBeenCalledTimes(1)
    w.unmount()
  })

  it('asks nothing when it is left before the deferred first load', async () => {
    const w = mountPanel()
    await vi.advanceTimersByTimeAsync(300)
    w.unmount()
    await vi.advanceTimersByTimeAsync(5000)
    expect(h.getProposals).not.toHaveBeenCalled()
    expect(h.getMyStakingStats).not.toHaveBeenCalled()
    expect(h.mine).not.toHaveBeenCalled()
  })
})
