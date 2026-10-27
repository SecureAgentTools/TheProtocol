/**
 * §FESUITE (2026-10-10, lifecycle 90): NEEDS YOU asks the funding queue only of a viewer who may read it. The queue is
 * the treasury admin's (require_admin_flag("admin_treasury")) and the panel asked it for ANY admin flag, so a support,
 * enforcement, federation or platform admin was refused it on every panel (a 403 in the console) and the panel said the
 * funding queue could not be read. The controls: a treasury admin and a super admin still read it.
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
const who = vi.hoisted(() => ({ user: null as Record<string, unknown> | null }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:test:agent-1', name: 'Agent One' },
  isAdmin: !!who.user, user: who.user }) }))
vi.mock('@/composables/useMainframe', () => ({ useMainframe: () => ({ isMainframe: { value: false } }) }))
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

async function open() {
  const w = mount(BridgeAttention, { props: { show: false }, global: { stubs: { Icon: true } } })
  await w.setProps({ show: true })
  for (let i = 0; i < 6; i++) await flushPromises()
  return w
}

beforeEach(() => {
  for (const f of Object.values(h)) { f.mockReset(); f.mockResolvedValue([]) }
  h.getMyStakingStats.mockResolvedValue({})
})

describe('the funding queue in NEEDS YOU', () => {
  it('a support admin is not asked for it, and the panel names no failed funding read', async () => {
    who.user = { is_admin: false, admin_support: true }
    const w = await open()
    expect(h.listPending, 'asked a queue only the treasury admin may read').not.toHaveBeenCalled()
    expect(w.text()).not.toMatch(/funding/i)
  })

  it('control: a treasury admin and a super admin read it', async () => {
    who.user = { is_admin: false, admin_treasury: true }
    await open()
    expect(h.listPending).toHaveBeenCalled()
    h.listPending.mockClear()
    who.user = { is_admin: true }
    await open()
    expect(h.listPending).toHaveBeenCalled()
  })
})
