import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (the swallow census, 2026-10-04) — the evals reads answered [] for EVERY failure, so /leaderboard's Evals tab
 * and an agent profile's Evals tab said "No eval results yet." with their read failed. A registry with evals switched
 * off answers empty tables (200) or no route (404): both are "none". Anything else must reach the page as a failure.
 * Mocked at the HTTP layer (evals.ts makes its own axios instance).
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('axios', () => ({ default: { create: () => ({ get: http.get }) } }))

import { evalsApi } from './evals'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })
const DID = 'did:theprotocol:00000000-0000-4000-8000-000000000045'

describe('the evals reads tell a failed read from "none"', () => {
  beforeEach(() => http.get.mockReset())

  it('the leaderboard: a 5xx or no answer rejects; a 404 or empty tables are "none"', async () => {
    http.get.mockRejectedValueOnce(answered(502))
    await expect(evalsApi.getLeaderboard()).rejects.toThrow('502')
    http.get.mockRejectedValueOnce(new Error('timeout of 15000ms exceeded'))
    await expect(evalsApi.getLeaderboard('s1', 25)).rejects.toThrow('timeout')
    http.get.mockRejectedValueOnce(answered(404))
    await expect(evalsApi.getLeaderboard()).resolves.toEqual([])
    http.get.mockResolvedValueOnce({ data: { entries: [] } })
    await expect(evalsApi.getLeaderboard()).resolves.toEqual([])
  })

  it('the leaderboard answers its entries, asked with the suite when one is named', async () => {
    const entries = [{ agent_did: DID, mean_score: 0.9, runs: 3, last_at: null }]
    http.get.mockResolvedValueOnce({ data: { entries } })
    await expect(evalsApi.getLeaderboard('s1', 25)).resolves.toEqual(entries)
    expect(http.get).toHaveBeenCalledWith('/evals/leaderboard', { params: { suite: 's1', limit: 25 } })
  })

  it("an agent's results: a 5xx rejects; a 404 is \"none\"; an answer is its results", async () => {
    http.get.mockRejectedValueOnce(answered(503))
    await expect(evalsApi.getAgentResults(DID)).rejects.toThrow('503')
    http.get.mockRejectedValueOnce(answered(404))
    await expect(evalsApi.getAgentResults(DID)).resolves.toEqual([])
    const results = [{ run_id: 'r', suite: 's1', score: 1, passed: true, latency_ms: 10, error: null, at: null }]
    http.get.mockResolvedValueOnce({ data: { results } })
    await expect(evalsApi.getAgentResults(DID, 20)).resolves.toEqual(results)
    expect(http.get).toHaveBeenCalledWith(`/evals/agents/${encodeURIComponent(DID)}/results`, { params: { limit: 20 } })
  })
})
