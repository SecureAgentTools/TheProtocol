/**
 * services/api/evals.ts — Public Agent Evals wrapper.
 *
 * Consumes the public (no-auth) endpoints added with the Agent Evals feature:
 *   GET /api/v1/evals/suites
 *   GET /api/v1/evals/agents/{did}/results
 *   GET /api/v1/evals/leaderboard
 *
 * When EVALS_ENABLED is false on the registry the tables are empty, so these
 * resolve to empty arrays rather than erroring — the FE simply shows a hint.
 * A read that FAILS rejects (only a 404 answers []), so a page never says "no eval
 * results yet" for a read that never answered (§FESUITE, 2026-10-04).
 */
import axios from 'axios'

const publicClient = axios.create({ baseURL: '/api/v1', timeout: 15_000 })

export interface EvalResult {
  run_id: string
  suite: string
  score: number
  passed: boolean
  latency_ms: number | null
  error: string | null
  at: string | null
}

export interface EvalLeaderboardEntry {
  agent_did: string
  mean_score: number
  runs: number
  last_at: string | null
}

export const evalsApi = {
  async getAgentResults(did: string, limit = 20): Promise<EvalResult[]> {
    try {
      const { data } = await publicClient.get(
        `/evals/agents/${encodeURIComponent(did)}/results`,
        { params: { limit } },
      )
      return data?.results ?? []
    } catch (e: any) {
      // §FESUITE (2026-10-04): a failed read is not "no eval results yet". A 404 (evals not served here) is the
      // server's own "none"; any other failure reaches the page, which says the read failed.
      if (e?.response?.status === 404) return []
      throw e
    }
  },

  async getLeaderboard(suite?: string, limit = 25): Promise<EvalLeaderboardEntry[]> {
    try {
      const { data } = await publicClient.get('/evals/leaderboard', {
        params: { ...(suite ? { suite } : {}), limit },
      })
      return data?.entries ?? []
    } catch (e: any) {
      // §FESUITE (2026-10-04): as getAgentResults: only a 404 is "none"
      if (e?.response?.status === 404) return []
      throw e
    }
  },

  async getSuites(): Promise<Array<{ key: string; name: string; description?: string }>> {
    try {
      const { data } = await publicClient.get('/evals/suites')
      return data?.suites ?? []
    } catch {
      return []
    }
  },
}
