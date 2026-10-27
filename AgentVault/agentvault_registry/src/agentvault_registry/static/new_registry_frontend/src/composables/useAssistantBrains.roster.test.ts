/**
 * §FESUITE (V0576): the assistant matches a spoken name against the person's roster. A question asked while the roster
 * read was still in flight (its first answer can wait on the client's 2 s retry) was matched against the empty roster
 * and answered "No agent in your roster matched …": V0576's proof run caught it. The question now waits for the read
 * in flight; a read that failed is asked again once, and while it still fails the answer says the agents could not
 * be read.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('vue-router', () => ({ useRouter: () => ({ push: vi.fn() }) }))
vi.mock('@/services/api/client', () => ({ default: { get: h.get } }))
vi.mock('@/services/api/developers', () => ({
  developerApi: { getTegSummary: vi.fn().mockResolvedValue({ total_balance: 1, total_liquid_balance: 1, total_staked_balance: 0, agent_count: 1 }) },
}))
vi.mock('@/services/api/exchangeService', () => ({ exchangeService: { listings: vi.fn().mockResolvedValue({ listings: [] }) } }))

import { useAssistantBrains } from './useAssistantBrains'

function deferred<T>() {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

/** the roster read answers through `roster`; every other read answers empty */
function rosterThrough(roster: Promise<unknown>) {
  h.get.mockImplementation((url: string) => (url === '/developers/me/agents' ? roster : Promise.resolve({ data: {} })))
}

const lastAnswer = (b: ReturnType<typeof useAssistantBrains>) => b.msgs.value[b.msgs.value.length - 1]

describe('the assistant and a roster read still in flight', () => {
  beforeEach(() => { h.get.mockReset() })

  it('waits for the read, and a read that failed is said to have failed, never "no agent matched"', async () => {
    const roster = deferred<unknown>()
    roster.promise.catch(() => { /* the composable reads it */ })
    rosterThrough(roster.promise)
    const b = useAssistantBrains({ autoOpenDoors: false })
    void b.loadCtx()                                   // the page's mount read, not settled yet
    const asked = b.handle('balance of zzqprobe')      // asked meanwhile
    roster.reject(new Error('Request failed with status code 502'))
    await asked
    expect(lastAnswer(b).unresolved).toMatch(/could not be read/)
    expect(lastAnswer(b).unresolved).not.toMatch(/No agent in your roster matched/)
  })

  it('waits for the read, and a roster that answered is matched', async () => {
    const roster = deferred<unknown>()
    rosterThrough(roster.promise)
    const b = useAssistantBrains({ autoOpenDoors: false })
    void b.loadCtx()
    const asked = b.handle('balance of zzqprobe')
    roster.resolve({ data: [{ did: 'did:theprotocol:zzq', name: 'zzqprobe' }] })
    await asked
    expect(lastAnswer(b).unresolved, 'the agent the roster holds is matched').toBeUndefined()
  })
})
