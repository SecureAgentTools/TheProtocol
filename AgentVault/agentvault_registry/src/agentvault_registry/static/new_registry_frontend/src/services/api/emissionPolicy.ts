// W3 (agentvault2-d6, 2026-10-25; his word: "the event emission policy which needs hardening and a fe page to check the
// exact configuration from the fe. i really need it visualized"): the effective emission-policy configuration in one
// read, GET /admin/event-emission-policies/effective (routers/admin_health.py, admin flag admin_treasury like its
// siblings; services/emission_policy_view.py builds it). The page: views/AdminEmissionPolicy.vue (agentvault2-69).
import { apiClient } from './client'

/** What the registry's gate does with a type: emit it (a row allows it), refuse it (a row forbids it), or, with no row,
 *  what its mode says (off: allowed; shadow: allowed and counted as a refusal enforce would make; enforce: refused). */
export type RegistryGate = 'allow' | 'refuse' | 'no-row-allowed' | 'no-row-shadow' | 'no-row-refused'
/** The TEG's gate fails closed: no row is a refusal; LedgerBalanceChanged (its balance outbox) is always allowed. */
export type TegGate = 'allow' | 'refuse' | 'no-row-refused' | 'always-allowed'
/** balance: the event store's balance projection counts it; skipped: its row says skip; audit: recorded, not counted. */
export type ProjectionUse = 'balance' | 'skipped' | 'audit'
export type FindingCode =
  | 'emitted-without-row' | 'registry-emits-refused' | 'teg-emits-refused' | 'both-may-emit'
  | 'balance-type-skipped' | 'row-without-emitter' | 'in-store-without-row' | 'shadow-would-refuse'

export interface PolicyFlags { emit_from_registry: boolean; emit_from_teg: boolean; skip_in_projection: boolean }
export interface PolicyRow extends PolicyFlags { description: string | null; updated_at: string | null }

export interface MatrixRow {
  event_type: string
  /** the table's row, or null where the table has none */
  row: PolicyRow | null
  /** which code in this release emits the type (from the source, not from the table) */
  emitted_by: ('registry' | 'teg')[]
  registry: RegistryGate
  teg: TegGate
  projection: ProjectionUse
  balance_moving: boolean
  /** this frame's event store's count of the type; null means the store was not read (never draw it as 0) */
  store_count: number | null
  /** emits the registry's shadow mode counted as refusals enforce would make; null means not read */
  shadow_would_refuse: number | null
  findings: FindingCode[]
}

export interface DriftEntry {
  peer: string
  peer_type?: string | null
  /** "ok", or why the peer's rows could not be read */
  read: string
  only_here?: string[]
  only_there?: string[]
  differing?: { event_type: string; here: PolicyFlags; there: PolicyFlags }[]
}

export interface EffectivePolicy {
  generated_at?: string | null
  modes: {
    registry: {
      mode: 'off' | 'shadow' | 'enforce' | string
      no_row: string
      policy_table?: { rows: number; this_worker_cached?: number | null; this_worker_loaded_at?: string | null; this_worker_load_error?: string | null }
      set_by?: string | null
    }
    teg: { mode: string; no_row: string; always_allowed?: string[]; derived?: string | null }
    projection: { balance_types: string[]; skipped: string[] }
  }
  catalog: { registry: number; teg: number }
  /** "ok", or why this frame's event store could not be read */
  store_read: string
  /** "ok", or why the shadow counts could not be read */
  shadow_read: string
  matrix: MatrixRow[]
  summary: {
    types: number
    rows: number
    findings: Partial<Record<FindingCode, number>>
    by_finding?: Partial<Record<FindingCode, string[]>>
    finding_text?: Partial<Record<FindingCode, string>>
  }
  drift?: DriftEntry[]
}

export const emissionPolicyApi = {
  async effective(includeDrift = true): Promise<EffectivePolicy> {
    const r = await apiClient.get('/admin/event-emission-policies/effective', { params: { include_drift: includeDrift } })
    return r.data as EffectivePolicy
  },
}
