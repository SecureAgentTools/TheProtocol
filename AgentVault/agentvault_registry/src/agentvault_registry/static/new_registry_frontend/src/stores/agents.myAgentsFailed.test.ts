import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (2026-10-05): My Agents drew "Fleet is empty: No agents deployed" over a failed fleet read, because the store
 * swallowed the failure into an unchanged (empty) list. The store says the last fleet read failed now; a failed refresh
 * leaves the list it had.
 */
const api = vi.hoisted(() => ({ getMyAgents: vi.fn() }))
vi.mock('@/services/api/agents', () => ({ agentApi: { getMyAgents: api.getMyAgents } }))
vi.mock('@/services/api/client', () => ({ apiClient: { post: vi.fn() } }))
vi.mock('@/services/api/batchedPost', () => ({ batchedPost: vi.fn(async () => ({ results: [] })) }))

import { useAgentStore } from './agents'

describe('the fleet read says when it failed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    api.getMyAgents.mockReset()
  })

  it('a failed first read is a failure, never an empty fleet', async () => {
    const s = useAgentStore()
    expect(s.myAgentsFailed).toBe(false)
    api.getMyAgents.mockRejectedValueOnce(new Error('Request failed with status code 502'))
    await s.fetchMyAgents(undefined, { limit: 500 })
    expect(s.myAgentsFailed).toBe(true)
    expect(s.agents).toEqual([])
  })

  it('an answer clears it, and a failed refresh keeps the list that was shown', async () => {
    const s = useAgentStore()
    api.getMyAgents.mockResolvedValueOnce([{ did: 'did:theprotocol:a', name: 'A' }])
    await s.fetchMyAgents(undefined, { limit: 500 })
    expect(s.myAgentsFailed).toBe(false)
    expect(s.agents.map((a: any) => a.did)).toEqual(['did:theprotocol:a'])
    api.getMyAgents.mockRejectedValueOnce(new Error('Network Error'))
    await s.fetchMyAgents(undefined, { limit: 500 })
    expect(s.myAgentsFailed).toBe(true)
    expect(s.agents.map((a: any) => a.did)).toEqual(['did:theprotocol:a'])
  })

  it('a sign-out forgets it', async () => {
    const s = useAgentStore()
    api.getMyAgents.mockRejectedValueOnce(new Error('Network Error'))
    await s.fetchMyAgents()
    s.$reset()
    expect(s.myAgentsFailed).toBe(false)
  })
})
