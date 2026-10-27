/**
 * services/api/attestationsAdmin.ts — ZKP attestation analytics admin wrapper.
 *
 * Build #14 (2026-05-08) — admin oversight for the ZKP attestation system.
 * Surfaces circuit distribution, status breakdown, expiry timeline, recent
 * submissions, and ZKP phase env state for empty-state context.
 *
 * Backend: routers/admin_health.py:get_attestations_analytics
 * Auth: admin_platform flag.
 */
import { apiClient } from './client'
import type { CircuitInfo } from './attestations'

export type AttestationPeriod = '24h' | '7d' | '30d' | 'all'

export interface AttestationStats {
  total: number
  verified: number
  failed: number
  revoked: number
  expired: number
  active: number
  expiring_24h: number
  circuits_available: number
}

export interface CircuitDistribution {
  circuit_id: string
  circuit_version: string
  count: number
}

export interface AgentDistribution {
  agent_did: string
  count: number
}

export interface AttestationRow {
  id: string
  agent_did: string
  circuit_id: string
  circuit_version: string
  verified: boolean
  submitted_at: string | null
  verified_at: string | null
  expires_at: string | null
  revoked_at: string | null
  revoked_by: string | null
  revoked_reason: string | null
  failure_reason: string | null
  is_active: boolean
  policy_parameters_hash: string | null
}

export interface CadencePoint {
  t: string
  submitted: number
}

export interface ZkpPhaseState {
  phase_1: boolean
  phase_2: boolean
  phase_3: boolean
  phase_4: boolean
  phase_5: boolean
  /** Reported only by a registry older than V0613; no switch stands behind it. */
  phase_6?: boolean
}

export interface AttestationAnalytics {
  as_of: string
  period: AttestationPeriod
  stats: AttestationStats
  by_circuit: CircuitDistribution[]
  top_agents: AgentDistribution[]
  recent: AttestationRow[]
  cadence: CadencePoint[]
  zkp_phases: ZkpPhaseState
}

/** One entry of GET /circuits/: v2.0.0 active (with its key, metadata and policy), v1.0.0 retired. */
export type CircuitListEntry = CircuitInfo

class AttestationsAdminService {
  async analytics(period: AttestationPeriod = '30d'): Promise<AttestationAnalytics> {
    try {
      const resp = await apiClient.get('/admin/attestations/analytics', { params: { period } })
      return resp.data
    } catch (err) {
      console.error('Failed to load attestation analytics:', err)
      throw err
    }
  }

  /** Public endpoint — list available circuits (read-only). A failed read throws (§FESUITE, V0578): it answered [], and
   *  the analytics page drew "Available circuits (0)" for a list it never read. */
  async listCircuits(): Promise<CircuitListEntry[]> {
    try {
      const resp = await apiClient.get('/circuits/')
      return resp.data?.circuits || []
    } catch (err) {
      console.error('Failed to list circuits:', err)
      throw err
    }
  }
}

export const attestationsAdminService = new AttestationsAdminService()
