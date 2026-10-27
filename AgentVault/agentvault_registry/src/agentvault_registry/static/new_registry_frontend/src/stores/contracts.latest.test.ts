import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useContractStore } from './contracts'

/**
 * §COCKPITDESK (2026-10-15): the latest fetch owns the contract list. Its "mine" half is read for the acting agent and
 * the page refetches on every switch; a fetch still in flight for the earlier agent is dropped on arrival, never shown
 * as the new agent's contracts, and only the latest fetch ends the loading state.
 */
const api = vi.hoisted(() => ({ listAvailableContracts: vi.fn(), getAgentContracts: vi.fn() }))
const who = vi.hoisted(() => ({ did: 'did:theprotocol:a' }))
vi.mock('@/services/api/contracts', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listAvailableContracts: api.listAvailableContracts,
  getAgentContracts: api.getAgentContracts,
  ctrRef: (c: { id: string }) => c.id,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ get activeAgent() { return { did: who.did } } }) }))

const row = (id: string) => ({ id, created_at: '2026-10-14T00:00:00Z' })
function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((r) => { resolve = r })
  return { promise, resolve }
}

describe('the contract list follows the acting agent', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.listAvailableContracts.mockReset().mockResolvedValue([])
    api.getAgentContracts.mockReset()
    who.did = 'did:theprotocol:a'
  })

  it("agent A's contracts arriving after the switch to B are dropped; B's stay", async () => {
    const slowA = deferred<unknown[]>()
    api.getAgentContracts.mockImplementation((did: string) =>
      did === 'did:theprotocol:a' ? slowA.promise : Promise.resolve([row('contract-of-b')]))
    const store = useContractStore()
    const first = store.fetchContracts()          // as A: its "mine" is slow
    // the fetch reads the acting agent after an await (the auth store's import): switch once A's read is in flight
    await vi.waitFor(() => expect(api.getAgentContracts).toHaveBeenCalledWith('did:theprotocol:a'))
    who.did = 'did:theprotocol:b'
    await store.fetchContracts()                  // as B, before A's answer
    expect(store.contracts.map((c) => String(c.id))).toEqual(['contract-of-b'])
    slowA.resolve([row('contract-of-a')])
    await first
    expect(store.contracts.map((c) => String(c.id)), "A's contracts never replace B's").toEqual(['contract-of-b'])
    expect(store.loading).toBe(false)
  })

  it('a single fetch is unchanged', async () => {
    api.getAgentContracts.mockResolvedValue([row('contract-of-a')])
    const store = useContractStore()
    await store.fetchContracts()
    expect(store.contracts.map((c) => String(c.id))).toEqual(['contract-of-a'])
    expect(store.loading).toBe(false)
  })
})
