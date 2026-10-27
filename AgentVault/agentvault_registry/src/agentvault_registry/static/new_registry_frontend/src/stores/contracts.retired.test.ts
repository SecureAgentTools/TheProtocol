import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
// Imported statically (vi.mock is hoisted above it, so the store still gets the mocks): a dynamic import inside the
// first test put the store's cold import on that test's 5 s clock, and under load it timed out (V0445's first build,
// load 46), which then let its fetch run into the next test's reset mocks.
import { useContractStore } from './contracts'

// §TWOAGENT V0442: the Contracts page's store decides that D8 retired the legacy contract list from the LIST route
// alone. EU and ASIA answer /api/v1/contracts/ with 404 and the page then reads the contract rail; a frame that keeps the
// list (the sandbox pair) must keep the legacy behaviour, including a failing agent route failing the fetch.
const api = vi.hoisted(() => ({
  listAvailableContracts: vi.fn(),
  getAgentContracts: vi.fn(),
}))
vi.mock('@/services/api/contracts', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  listAvailableContracts: api.listAvailableContracts,
  getAgentContracts: api.getAgentContracts,
  ctrRef: (c: { id: string }) => c.id,
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ activeAgent: { did: 'did:theprotocol:asia:straits' } }) }))

const notFound = () => Object.assign(new Error('Request failed with status code 404'), { response: { status: 404 } })
const serverError = () => Object.assign(new Error('Request failed with status code 500'), { response: { status: 500 } })

async function fetched() {
  const store = useContractStore()
  await store.fetchContracts()
  return store
}

describe('the legacy contract list, retired or not (§TWOAGENT V0442)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.listAvailableContracts.mockReset()
    api.getAgentContracts.mockReset()
  })

  it('a 404 from the list means D8 retired it: no error, nothing listed, the page reads the rail', async () => {
    api.listAvailableContracts.mockRejectedValue(notFound())
    api.getAgentContracts.mockRejectedValue(notFound())
    const store = await fetched()
    expect(store.legacyRetired).toBe(true)
    expect(store.error).toBeNull()
    expect(store.contracts).toEqual([])
    expect(store.loaded).toBe(true) // §FESUITE: an answered list, retired: the page counts the rail
  })

  it('control: a frame that keeps the list keeps the legacy behaviour', async () => {
    api.listAvailableContracts.mockResolvedValue([{ id: 'a', created_at: '2026-09-24T08:00:00Z' }])
    api.getAgentContracts.mockResolvedValue([{ id: 'b', created_at: '2026-09-24T09:00:00Z' }])
    const store = await fetched()
    expect(store.legacyRetired).toBe(false)
    expect(store.error).toBeNull()
    expect(store.contracts.map((c) => String(c.id))).toEqual(['b', 'a'])
    expect(store.loaded).toBe(true)
  })

  it('a 404 from the agent route alone, on a frame that has the list, fails the fetch as before', async () => {
    api.listAvailableContracts.mockResolvedValue([])
    api.getAgentContracts.mockRejectedValue(notFound())
    const store = await fetched()
    expect(store.legacyRetired).toBe(false)
    expect(store.error).toContain('404')
    expect(store.loaded).toBe(false) // a failed fetch is not a read: the tiles keep the dash
  })

  it('any other failure of the list is an error, not a retirement', async () => {
    api.listAvailableContracts.mockRejectedValue(serverError())
    api.getAgentContracts.mockResolvedValue([])
    const store = await fetched()
    expect(store.legacyRetired).toBe(false)
    expect(store.error).toContain('500')
    expect(store.loaded).toBe(false)
  })
})
