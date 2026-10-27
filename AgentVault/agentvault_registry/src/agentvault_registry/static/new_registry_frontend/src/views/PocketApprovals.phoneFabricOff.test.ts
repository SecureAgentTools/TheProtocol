import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * D6-841 (agentvault2-5b, 2026-10-25): found by the console suite's lifecycle 72 in the V0641 proof on sbx-beta. The owner
 * rail (GET /phone/sessions/mine) answers 503 where the Phone Fabric is off; it used to go out only when the member's
 * agent held saved credentials, and once owned agents act through the session (V0641) it went out on every visit to a
 * registry without the fabric. Pocket's approvals now ask it only where the registry config says the fabric is on; a
 * registry that says nothing (older) is asked as before. The stores and APIs are doubles; the config is a double too.
 */
const DID = 'did:theprotocol:pa-agent'
const h = vi.hoisted(() => ({
  isAdmin: false, sessions: vi.fn(), mySessions: vi.fn(), getMyAgents: vi.fn(), ensureAgentFor: vi.fn(), cfg: {} as Record<string, unknown>,
  // a lane this frame runs dark: every call answers 404
  dark: () => new Proxy({}, { get: () => vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })) }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ get isAdmin() { return h.isAdmin }, user: { developer_id: 1 }, token: 'tok' }) }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: h.getMyAgents } }))
vi.mock('@/services/api/agentDelegation', () => ({
  agentDelegationApi: { listGrants: vi.fn().mockResolvedValue({ grants: [] }), listCapabilities: vi.fn().mockResolvedValue({ tokens: [], mode: 'off' }) },
}))
vi.mock('@/services/api/phoneFabric', () => ({ phoneFabricApi: { sessions: h.sessions, mySessions: h.mySessions } }))
vi.mock('@/composables/usePocketAgent', () => ({ usePocketAgent: () => ({ ensureAgentFor: h.ensureAgentFor }) }))
vi.mock('@/composables/usePocketLock', async () => {
  const { ref } = await import('vue')
  return { usePocketLock: () => ({ enabled: ref(false), enroll: vi.fn(), disable: vi.fn(), verify: vi.fn() }), pocketCredentialId: () => null }
})
vi.mock('@/services/api/liability', () => ({ liabilityApi: h.dark() }))
vi.mock('@/services/api/devicePush', () => ({ devicePushApi: h.dark() }))
vi.mock('@/composables/useDeviceSigner', async () => {
  const { ref } = await import('vue')
  return { useDeviceSigner: () => ({ supported: ref(false), platformAvailable: ref(false), sign: vi.fn() }) }
})
vi.mock('vue-router', () => ({ useRoute: () => ({ query: {}, path: '/pocket/approvals' }), useRouter: () => ({ push: vi.fn(), replace: vi.fn() }) }))

vi.mock('@/composables/useRegistryConfig', () => ({ loadRegistryConfig: vi.fn(async () => h.cfg) }))

import PocketApprovals from './PocketApprovals.vue'

const opts = { global: { stubs: { Icon: true, DecisionQueue: true, ConfirmActionModal: true, Teleport: true, teleport: true, RouterLink: true } } }
const failure = () => Object.assign(new Error('Request failed with status code 502'), { isAxiosError: true, response: { status: 502 } })

async function pickTheAgent() {
  const w = mount(PocketApprovals, opts)
  await flushPromises()
  await w.find('[data-testid="pa-picker-search"]').trigger('focus')
  await flushPromises()
  await w.find('.pa-pick-row').trigger('click')
  await flushPromises()
  return w
}

describe("Pocket's approvals ask the owner phone read only where the fabric is on", () => {
  beforeEach(() => {
    h.isAdmin = false
    h.sessions.mockReset(); h.mySessions.mockReset(); h.ensureAgentFor.mockReset().mockResolvedValue(true)
    h.getMyAgents.mockReset().mockResolvedValue([{ did: DID, name: 'Pocket Agent' }])
    h.mySessions.mockResolvedValue({ sessions: [] })
  })

  it('where the registry says the fabric is off, the owner rail is never asked (nor the agent signed in for it)', async () => {
    h.cfg = { phone_fabric_enabled: false }
    const w = await pickTheAgent()
    expect(h.mySessions, 'no read of a fabric this registry does not run').not.toHaveBeenCalled()
    expect(h.ensureAgentFor, 'nor a sign-in to ask it').not.toHaveBeenCalled()
    expect(w.text()).not.toContain('could not be read')
    w.unmount()
  })

  it('where it says the fabric is on, the owner rail reads the sessions', async () => {
    h.cfg = { phone_fabric_enabled: true }
    const w = await pickTheAgent()
    expect(h.mySessions).toHaveBeenCalled()
    w.unmount()
  })

  it('control: a registry that says nothing (older) is asked as before', async () => {
    h.cfg = {}
    const w = await pickTheAgent()
    expect(h.mySessions).toHaveBeenCalled()
    w.unmount()
  })
})
