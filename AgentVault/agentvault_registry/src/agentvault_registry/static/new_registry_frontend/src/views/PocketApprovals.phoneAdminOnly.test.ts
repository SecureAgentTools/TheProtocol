import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §FESUITE V0578 (2026-10-06, agentvault2-09): Pocket's approvals read the phone sessions through the admin rail first
 * for EVERY developer (a 403 on each visit for a member, found by the member-views lifecycle 72), and an admin whose
 * admin read got no answer fell to the owner rail as if refused, so "could not be read" never showed. The admin rail is
 * asked for an admin only now; an admin whose read failed is told so; an admin whose read answered sees the sessions.
 */
const DID = 'did:theprotocol:pa-agent'
const h = vi.hoisted(() => ({
  isAdmin: false, sessions: vi.fn(), mySessions: vi.fn(), getMyAgents: vi.fn(), ensureAgentFor: vi.fn(),
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
// D6-841: the owner rail is asked only where the registry config says the fabric is on; this file's registry says nothing
// (asked as before), and the read is a double, never a real fetch that outlives a test
vi.mock('@/composables/useRegistryConfig', () => ({ loadRegistryConfig: vi.fn(async () => ({})) }))

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

describe("Pocket's approvals ask the admin phone read of an admin only", () => {
  beforeEach(() => {
    h.sessions.mockReset(); h.mySessions.mockReset(); h.ensureAgentFor.mockReset().mockResolvedValue(true)
    h.getMyAgents.mockReset().mockResolvedValue([{ did: DID, name: 'Pocket Agent' }])
    h.mySessions.mockResolvedValue({ sessions: [] })
  })

  it('a member never asks the admin rail; the owner rail reads the sessions', async () => {
    h.isAdmin = false
    h.sessions.mockRejectedValue(Object.assign(new Error('403'), { isAxiosError: true, response: { status: 403 } }))
    const w = await pickTheAgent()
    expect(h.sessions, 'the admin rail is not asked for a member').not.toHaveBeenCalled()
    expect(h.mySessions).toHaveBeenCalled()
    w.unmount()
  })

  it("an admin whose admin read got no answer is told it could not be read (not the owner rail's view)", async () => {
    h.isAdmin = true
    h.sessions.mockRejectedValue(failure())
    const w = await pickTheAgent()
    expect(h.sessions).toHaveBeenCalled()
    expect(h.mySessions, 'a failed admin read is not a refusal').not.toHaveBeenCalled()
    expect(w.text()).toContain('Phone sessions could not be read just now')
    w.unmount()
  })

  it('control: an admin whose admin read answered sees the sessions; a refused admin read still falls to the owner rail', async () => {
    h.isAdmin = true
    h.sessions.mockResolvedValue({ enabled: true, sessions: [{ id: 'ps-1', agent_did: DID, status: 'active' }] })
    const w = await pickTheAgent()
    expect(h.mySessions).not.toHaveBeenCalled()
    expect(w.text()).not.toContain('could not be read')
    w.unmount()
    h.sessions.mockReset().mockRejectedValue(Object.assign(new Error('403'), { isAxiosError: true, response: { status: 403 } }))
    const w2 = await pickTheAgent()
    expect(h.mySessions, 'a refusal (an admin without the flag) reads the owner rail').toHaveBeenCalled()
    w2.unmount()
  })
})
