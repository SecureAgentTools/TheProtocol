// OPA policy console API (§29, 2026-07-28).
// apiClient baseURL is already /api/v1, so paths here are relative.
import { apiClient } from './client'

export interface OpaDecision {
  ts: string
  policy: string
  label: string | null
  input: Record<string, unknown>
  python: boolean | null
  opa: boolean | null
  match: boolean | null
  latency_ms: number | null
}

export interface OpaRingStats {
  retained: number
  capacity: number
  mismatches: number
  opa_errors: number
  agreement_pct: number | null
  latency_ms_avg: number | null
  latency_ms_max: number | null
}

export interface OpaStatus {
  opa_enabled: boolean
  opa_enforce: boolean
  mode: 'off' | 'shadow' | 'enforce'
  sidecar: { reachable: boolean; url?: string; error?: string }
  divergence: OpaRingStats
}

export interface OpaPolicy {
  id: string
  package: string
  rules: string[]
  lines: number
  bytes: number
  source: string
  kind: 'mirror' | 'invariant' | 'domain'
}

export interface OpaSimResult {
  ts: string
  policy: string
  label: string | null
  input: Record<string, unknown>
  current: boolean | null
  candidate: boolean | null
  would_break: boolean
  undecided: boolean
}

export interface OpaSimulation {
  evaluated: number
  would_break: number
  undecided: number
  safe_to_enforce: boolean
  verdict: string
  results: OpaSimResult[]
}

export const opaAdminApi = {
  status: () => apiClient.get<OpaStatus>('/admin/opa/status').then(r => r.data),

  decisions: (limit = 200, onlyMismatch = false) =>
    apiClient
      .get<{ count: number; decisions: OpaDecision[]; stats: OpaRingStats }>('/admin/opa/decisions', {
        params: { limit, only_mismatch: onlyMismatch },
      })
      .then(r => r.data),

  policies: () =>
    apiClient
      .get<{ enabled: boolean; count: number; policies: OpaPolicy[] }>('/admin/opa/policies')
      .then(r => r.data),

  simulate: (rego: string, rulePath: string, policyFilter?: string, limit = 200) =>
    apiClient
      .post<OpaSimulation>('/admin/opa/simulate', {
        rego,
        rule_path: rulePath,
        policy_filter: policyFilter || null,
        limit,
      })
      .then(r => r.data),
}

export default opaAdminApi
