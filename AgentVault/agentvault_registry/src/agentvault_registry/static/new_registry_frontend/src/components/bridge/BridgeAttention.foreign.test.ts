/**
 * §FESUITE (V0577): "NEEDS YOU" (the attention panel Pocket's shell and the bridge mount) also asks every other registry
 * you hold an agent credential for what waits on you there (contracts/v2/mine and guild/mine, with that agent's own
 * token). A read there that answered 5xx or not at all was null, so that registry counted 0 needs and was never named
 * under "Could not reach:" (only a failed sign-in was), the conflation its own comment rules out. It is now named; a
 * refusal (a 4xx: the rail is not served there) is still an answer of none. And "Nothing is waiting on you." is no longer
 * absolute while the panel lists reads it could not make: it says "in what could be read".
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
    getAllCredentials: () => ({ 'did:theprotocol:far:1': {
      did: 'did:theprotocol:far:1', client_id: 'far-cid', client_secret: 'far-secret-0123456789', registry_url: 'https://far.example',
    } }),
  },
}))
vi.mock('@/composables/useFrameManifest', () => ({ currentFrameManifest: () => null }))
vi.mock('@/services/frameManifest', () => ({ entryByOrigin: () => null }))
vi.mock('@/composables/useFocusTrap', () => ({ useFocusTrap: () => {} }))
vi.mock('@/services/appLocale', () => ({ appLocale: () => 'en' }))

import BridgeAttention from './BridgeAttention.vue'

/** what the far registry answers on both of its reads */
function farAnswers(status: number) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: status < 300, status, json: async () => [] })))
}

async function openPanel() {
  const w = mount(BridgeAttention, { props: { show: false }, global: { stubs: { Icon: true } } })
  await w.setProps({ show: true })
  for (let i = 0; i < 4; i++) await flushPromises()
  return w
}
const clearLine = (w: any) => w.find('[data-testid="bat-clear"]').text()

beforeEach(() => {
  for (const f of Object.values(h)) { f.mockReset(); f.mockResolvedValue([]) }
  h.getMyStakingStats.mockResolvedValue({})
})
afterEach(() => { vi.unstubAllGlobals() })

describe('NEEDS YOU when a read fails', () => {
  it('a registry whose reads answered 502 is named under "Could not reach", and the all-clear is not absolute', async () => {
    farAnswers(502)
    const w = await openPanel()
    expect(w.find('[data-testid="bat-blind-foreign"]').exists(), 'counted a failed registry as nothing waiting there').toBe(true)
    expect(w.find('[data-testid="bat-blind-foreign"]').text()).toContain('far.example')
    expect(clearLine(w)).toBe('Nothing is waiting on you in what could be read.')
  })

  it('a registry that refuses the rail (404) is an answer of none: nothing named, the all-clear stands', async () => {
    farAnswers(404)
    const w = await openPanel()
    expect(w.find('[data-testid="bat-blind-foreign"]').exists()).toBe(false)
    expect(clearLine(w)).toBe('Nothing is waiting on you.')
  })

  it('a local read that failed qualifies the all-clear too', async () => {
    farAnswers(404)
    h.getMyStakingStats.mockRejectedValue(new Error('Network Error'))
    const w = await openPanel()
    expect(w.find('[data-testid="bat-blind-failed"]').text()).toContain('locks')
    expect(clearLine(w)).toBe('Nothing is waiting on you in what could be read.')
  })
})
