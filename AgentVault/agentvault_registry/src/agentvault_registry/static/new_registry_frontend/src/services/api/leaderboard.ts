/**
 * services/api/leaderboard.ts — Public reputation leaderboard wrapper.
 *
 * Build #11 (2026-05-07) — pulls from existing public endpoints:
 *   GET /api/v1/teg/reputation/rankings   (no auth)
 *   GET /api/v1/agents/by-did/{did}        (no auth, profile enrichment)
 *
 * No new backend code — all consumed endpoints already public.
 */
import axios from 'axios'
import type { TrackRecordCompact } from '@/services/api/trackRecord'

// Use a separate axios instance WITHOUT auth interceptors — leaderboard is
// public (no login required), and we don't want apiClient's 401-cascade
// behavior triggering when an unauthenticated visitor hits it.
const publicClient = axios.create({
  baseURL: '/api/v1',
  timeout: 15_000,
})

export interface ReputationRankingEntry {
  rank: number
  agent_id: string  // DID
  reputation_score: number
  reputation_tier: string  // "standard" | "gold" | "platinum" | etc.
  total_transactions: number
  /** §MARKSURFACES (2026-09-10) — the registry-attested earned mark, shipped with the
   *  ranking row so the page can render it without a per-row lookup. Null = no verified
   *  guild work. NOT the same fact as `reputation_score`: that is EigenTrust over
   *  transaction flow, this is settled work with receipts, and they can disagree. */
  track_record?: TrackRecordCompact | null
}

export interface ReputationRankingsResponse {
  rankings: ReputationRankingEntry[]
  total_agents: number
  timestamp: string
}

export interface AgentProfilePublic {
  id?: string
  did: string
  name?: string | null
  description?: string | null
  status?: string | null
  reputation_score?: number | null
  liquid_balance?: string | number | null
  staked_balance?: string | number | null
  card_data?: Record<string, any> | null
  last_active_at?: string | null
  /** §MARKSURFACES — shipped by GET /agents/by-did since 2026-09-10. */
  track_record?: TrackRecordCompact | null
}

class LeaderboardService {
  async getRankings(limit: number = 50, offset: number = 0): Promise<ReputationRankingsResponse> {
    try {
      const resp = await publicClient.get('/teg/reputation/rankings', {
        params: { limit, offset },
      })
      return resp.data
    } catch (err) {
      console.error('Failed to load reputation rankings:', err)
      throw err
    }
  }

  async getProfile(did: string): Promise<AgentProfilePublic | null> {
    try {
      const resp = await publicClient.get(`/agents/by-did/${encodeURIComponent(did)}`)
      return resp.data
    } catch (err) {
      // Some DIDs may not have a discoverable agent card — return null gracefully
      return null
    }
  }
}

export const leaderboardService = new LeaderboardService()
