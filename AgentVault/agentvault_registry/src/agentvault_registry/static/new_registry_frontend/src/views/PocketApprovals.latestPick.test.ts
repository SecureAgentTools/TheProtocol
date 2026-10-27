import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'

/**
 * §COCKPITDESK (2026-10-15): the latest pick owns the screen. Agent A's grant and token lists still in flight when agent
 * B is picked had landed under B's name, where a revoke takes A's grant by its id. An answer for an agent no longer
 * picked is dropped, for the lists and the phone sessions alike.
 */
const A = 'did:theprotocol:pa-alpha'
const B = 'did:theprotocol:pa-bravo'
const h = vi.hoisted(() => ({
  listGrants: vi.fn(), listCapabilities: vi.fn(), mySessions: vi.fn(), ensureAgentFor: vi.fn(), getMyAgents: vi.fn(),
  dark: () => new Proxy({}, { get: () => vi.fn().mockRejectedValue(Object.assign(new Error('404'), { response: { status: 404 } })) }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ isAdmin: false, user: { developer_id: 1 }, token: 'tok' }) }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: h.getMyAgents } }))
vi.mock('@/services/api/agentDelegation', () => ({
  agentDelegationApi: { listGrants: h.listGrants, listCapabilities: h.listCapabilities },
}))
vi.mock('@/services/api/phoneFabric', () => ({ phoneFabricApi: { sessions: vi.fn(), mySessions: h.mySessions } }))
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

import PocketApprovals from './PocketApprovals.vue'

const opts = { global: { stubs: { Icon: true, DecisionQueue: true, ConfirmActionModal: true, Teleport: true, teleport: true, RouterLink: true } } }
const grant = (principal: string) => ({ id: principal, principal, permissions: ['teg.transfer'], revoked: false })
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

async function pick(w: ReturnType<typeof mount>, index: number) {
  await w.find('[data-testid="pa-picker-search"]').trigger('focus')
  await flushPromises()
  await w.findAll('.pa-pick-row')[index].trigger('click')
}

describe("Pocket's approvals show the picked agent's authority, never an earlier pick's", () => {
  beforeEach(() => {
    for (const f of [h.listGrants, h.listCapabilities, h.mySessions, h.ensureAgentFor, h.getMyAgents]) f.mockReset()
    h.getMyAgents.mockResolvedValue([{ did: A, name: 'Alpha' }, { did: B, name: 'Bravo' }])
    h.listCapabilities.mockResolvedValue({ tokens: [], mode: 'enforce' })
    h.ensureAgentFor.mockResolvedValue(true)
    h.mySessions.mockResolvedValue({ sessions: [] })
  })

  it("A's lists landing after B was picked are dropped; B's stay", async () => {
    const slowA = deferred<{ grants: unknown[] }>()
    h.listGrants.mockImplementation((did: string) => did === A ? slowA.promise : Promise.resolve({ grants: [grant('principal-of-bravo')] }))
    const w = mount(PocketApprovals, opts)
    await flushPromises()
    await pick(w, 0)                 // Alpha: its grants are slow
    await pick(w, 1)                 // Bravo, before Alpha's answer
    await flushPromises()
    expect(w.text()).toContain('principal-of-bravo')
    slowA.resolve({ grants: [grant('principal-of-alpha')] })
    await flushPromises()
    expect(w.text(), "Alpha's grant never shows under Bravo").not.toContain('principal-of-alpha')
    expect(w.text()).toContain('principal-of-bravo')
    expect(w.find('.pa-skel').exists(), 'the later pick ended the loading').toBe(false)
    w.unmount()
  })

  it("A's phone sessions landing after B was picked are dropped", async () => {
    h.listGrants.mockResolvedValue({ grants: [] })
    const slowSessions = deferred<{ sessions: unknown[] }>()
    h.mySessions.mockImplementationOnce(() => slowSessions.promise)
    const w = mount(PocketApprovals, opts)
    await flushPromises()
    await pick(w, 0)
    await flushPromises()            // Alpha's lists answered; its sessions are in flight
    await pick(w, 1)
    await flushPromises()
    slowSessions.resolve({ sessions: [{ id: 'ps-alpha', status: 'active', current_app: 'alpha-phone', actions_used: 1, budget_spent: 0 }] })
    await flushPromises()
    expect(w.text()).not.toContain('alpha-phone')
    w.unmount()
  })
})
