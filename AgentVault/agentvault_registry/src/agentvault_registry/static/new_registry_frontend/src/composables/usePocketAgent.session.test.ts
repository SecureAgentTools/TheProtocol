/**
 * V0641 (agentvault2-5b, 2026-10-25, with agentvault2-66): Pocket and the buy door act as an agent you own on this
 * registry with no secret saved in this browser, through your session, as the header and the picker do (the store's
 * canActAs, §FEFRAME W3).
 *
 * Found by the console suite's first purchase (fes-20261025T100011Z-490f, sbx-alpha): the buy door said "No agent with
 * stored credentials yet" while the header acted as the member's own agent. usePocketAgent listed saved secrets only,
 * so every Pocket screen said the same on a second device, or for agents made over the API. The store and the vault are
 * doubles here; the rules under test are the composable's: what it lists, which road it signs in by, and that it never
 * chooses among several agents of yours for you.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'

const h = vi.hoisted(() => ({ auth: null as any, stored: {} as Record<string, any> }))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => h.auth }))
vi.mock('@/services/agentCredentialsStore', () => ({
  agentCredentialsStore: { getAllCredentials: () => h.stored, isSealedLocked: () => false },
}))
vi.mock('@/services/credentialVault', () => ({ credentialVault: { onChange: () => {} } }))

import { usePocketAgent } from './usePocketAgent'

const did = (n: number) => `did:theprotocol:eu.example:0b6d5e6c-0000-4000-8000-00000000002${n}`
const mine = (n: number, extra: any = {}) => ({ did: did(n), name: `mine ${n}`, owned: true, status: 'active', ...extra })

function store(rows: any[], extra: any = {}) {
  h.auth = reactive({
    availableAgents: rows, activeAgent: null, agentToken: null,
    // the store's rule (stores/auth.ts canActAs): yours here needs no secret; anything else needs one; never revoked
    canActAs: (a: any) => !!a && a.status !== 'revoked' && (!!a.owned || !!(a.client_id && a.client_secret)),
    authenticateAsAgent: vi.fn(async () => true),
    ...extra,
  })
  return h.auth
}

describe('usePocketAgent and an agent you own with no secret saved here', () => {
  beforeEach(() => { h.stored = {}; localStorage.clear() })

  it('lists it as one this browser can act as, through your session, and says no "no agent"', () => {
    store([mine(1)])
    const p = usePocketAgent()
    expect(p.credAgents.value).toEqual([expect.objectContaining({ did: did(1), viaSession: true, client_secret: '' })])
    expect(p.noAgentReason.value).toBeNull()
  })

  it('signs in as it through the store\'s own row (the owner rail), never as a secret it does not have', async () => {
    const auth = store([mine(1)])
    const p = usePocketAgent()
    expect(await p.ensureAgentFor(did(1))).toBe(true)
    expect(auth.authenticateAsAgent).toHaveBeenCalledTimes(1)
    expect(auth.authenticateAsAgent.mock.calls[0][0]).toMatchObject({ did: did(1), owned: true })
  })

  it('restores it on its own when it is the only agent that can act', async () => {
    const auth = store([mine(1)])
    expect(await usePocketAgent().restoreActing()).toBe(true)
    expect(auth.authenticateAsAgent.mock.calls[0][0]).toMatchObject({ did: did(1), owned: true })
  })

  it('never chooses among several of yours for you; the saved choice is taken', async () => {
    const auth = store([mine(1), mine(2)])
    expect(await usePocketAgent().restoreActing(), 'two of yours, no saved choice: none chosen').toBe(false)
    expect(auth.authenticateAsAgent).not.toHaveBeenCalled()
    localStorage.setItem('activeAgentId', did(2))
    expect(await usePocketAgent().restoreActing()).toBe(true)
    expect(auth.authenticateAsAgent.mock.calls[0][0]).toMatchObject({ did: did(2) })
  })

  it('a saved secret wins for its agent, and is listed once', async () => {
    h.stored = { [did(1)]: { did: did(1), name: 'saved', client_id: 'cid', client_secret: 'sec' } }
    const auth = store([mine(1)])
    const p = usePocketAgent()
    expect(p.credAgents.value).toHaveLength(1)
    expect(p.credAgents.value[0]).toMatchObject({ did: did(1), client_id: 'cid' })
    expect(p.credAgents.value[0].viaSession).toBeFalsy()
    await p.ensureAgentFor(did(1))
    expect(auth.authenticateAsAgent.mock.calls[0][0]).toMatchObject({ client_id: 'cid', client_secret: 'sec' })
  })

  it('control: a row the store cannot act as (revoked, or not yours with no secret) is not listed, and the reason stays', () => {
    store([mine(1, { status: 'revoked' }), { did: did(2), name: 'not mine', status: 'active' }])
    const p = usePocketAgent()
    expect(p.credAgents.value).toEqual([])
    expect(p.noAgentReason.value).toMatch(/No agent with stored credentials yet/)
  })

  it('an agent the store already acts as leaves no "no agent" reason', () => {
    store([], { activeAgent: { did: did(3) }, agentToken: 'agent.jwt' })
    expect(usePocketAgent().noAgentReason.value).toBeNull()
  })

  // agentvault2-66's review of be05537f: a door that acts as THE acting agent asks for a choice when none can be made
  it('several of yours, none chosen, no secret saved: the choose reason asks for one', () => {
    store([mine(1), mine(2)])
    const p = usePocketAgent()
    expect(p.noAgentReason.value, 'agents can act: not a "no agent" state').toBeNull()
    expect(p.chooseReason.value).toMatch(/choose one in the agent switcher/)
  })

  it('no choose reason with one of yours, a saved choice, a saved secret, or an acting agent', () => {
    store([mine(1)])
    expect(usePocketAgent().chooseReason.value, 'one: restoreActing takes it').toBeNull()
    store([mine(1), mine(2)])
    localStorage.setItem('activeAgentId', did(2))
    expect(usePocketAgent().chooseReason.value, 'the saved choice is taken').toBeNull()
    localStorage.clear()
    h.stored = { [did(3)]: { did: did(3), client_id: 'cid', client_secret: 'sec' } }
    store([mine(1), mine(2)])
    expect(usePocketAgent().chooseReason.value, 'a saved secret: restoreActing takes it').toBeNull()
    h.stored = {}
    store([mine(1), mine(2)], { activeAgent: { did: did(1) }, agentToken: 'agent.jwt' })
    expect(usePocketAgent().chooseReason.value, 'one is acting already').toBeNull()
  })
})
