import { apiClient } from './client'

// ── Types ─────────────────────────────────────────────────────────────────

export type EnforcementMode = 'off' | 'dry_run' | 'enforcing'

export interface EnforcementModeState {
  mode: EnforcementMode
  enforcement_env_flag: boolean
  is_central_registry_env_flag: boolean
  effective_enforcement: boolean
  last_changed_at: string | null
  last_changed_by: string | null
}

export interface PeerComplianceRow {
  // Docker-discovered target identifiers (always present)
  operator_id: string
  display_name: string
  frame: string
  role: string // 'mainframe' | 'operator'
  cloud_url: string | null
  // PeerRegistry mapping — null if target isn't admitted yet
  peer_registry_id: number | null
  peer_name: string | null
  peer_url: string | null
  peer_status: string | null
  has_compliance_record: boolean
  federation_status: string | null
  compliance_score: number | null
  drift_events_count: number | null
  consecutive_poll_failures: number | null
  last_poll_at: string | null
  last_hash_mismatch_at: string | null
  quarantine_reason: string | null
  quarantine_since: string | null
  grace_expires: string | null
  admitted_at: string | null
  // ── Identity (§MCPTEST30 V0561: consul_admin._with_identity) ─────────────────
  // The trust domain a cross-frame operation resolves for the peer (spiffe_canonical.resolve_target_trust_domain's
  // order: the peer row's column, its signed card, the topology cache), the frame of this federation sharing it, and
  // that frame's currency. Optional: a registry before V0561 sends none of them, and the roster then says so.
  trust_domain?: string | null
  resolution_state?: 'resolved' | 'unidentified' | null
  resolution_source?: 'column' | 'card' | 'bfs' | 'unresolved' | null
  home_frame?: string | null
  currency_zone?: string | null
  baseline_hash?: string | null
  baseline_source?: string | null
}

/** Federation corridor reachability (2026-07-24).
 *  Compliance tracked licence adherence and had no notion of whether a corridor actually
 *  carries traffic — which is how frame-c ran with 6 of 16 peers for seven weeks while
 *  every surface read healthy. NEVER_SYNCED is the state that hid it.
 */
export type ReachabilityState = 'OK' | 'STALE' | 'NEVER_SYNCED' | 'UNREACHABLE' | 'PENDING'

export interface ReachabilityPeer {
  peer: string
  peer_id?: string | number | null
  base_url: string
  peer_type: string | null
  trust_domain: string | null
  spiffe_id: string | null
  status: string
  state: ReachabilityState
  severity: 'ok' | 'info' | 'warning' | 'critical'
  last_synced_at: string | null
  last_sync_attempt_at: string | null
  last_sync_age_seconds: number | null
  registered_at: string | null
  age_days_since_registration: number | null
  consecutive_sync_failures: number
  last_sync_error: string | null
  diagnosis: string | null
  remedy: string | null
}

export interface ReachabilityReport {
  generated_at: string
  window: { stale_hours: number; never_synced_grace_hours: number; unreachable_after_failures: number }
  peers_total: number
  peers_active: number
  reachable: number
  reachable_ratio: number | null
  counts: Record<string, number>
  findings: ReachabilityPeer[]
  peers: ReachabilityPeer[] | null
  definition: string
}

export interface ComplianceOverview {
  reachability?: ReachabilityReport | null
  mode: EnforcementMode
  enforcement_env_flag: boolean
  is_central_registry_env_flag: boolean
  effective_enforcement: boolean
  poller_enabled: boolean
  poll_interval_seconds: number
  peers_total: number
  peers_with_compliance: number
  peers_federated: number
  peers_quarantined: number
  peers_blacklisted: number
  peers_unidentified?: number // WS-G; FE computes from peers[] if backend omits it
  peers_never_polled: number
  peers_unreachable_streak: number
  peers: PeerComplianceRow[]
}

export interface PolicyDiffEntry {
  path: string
  stored_value: unknown
  live_value: unknown
  match: boolean
  severity: string | null
}

export interface PeerDetail {
  // Present on the slug-based endpoint (/peers/by-operator/{id})
  operator_id?: string
  display_name?: string
  frame?: string
  role?: string
  has_compliance_record?: boolean
  // Always present
  peer_registry_id: number
  peer_name: string
  peer_url: string
  peer_status: string
  federation_status: string | null
  compliance_score: number | null
  drift_events_count: number | null
  consecutive_poll_failures: number | null
  last_poll_at: string | null
  last_hash_mismatch_at: string | null
  quarantine_reason: string | null
  quarantine_since: string | null
  quarantine_events: Array<Record<string, unknown>> | null
  admitted_policy_hash: string | null
  live_policy_hash: string | null
  hash_match: boolean | null
  live_policy_fetched: boolean
  live_fetch_error: string | null
  admitted_policy_json: Record<string, unknown> | null
  live_policy_json: Record<string, unknown> | null
  diff: PolicyDiffEntry[] | null
  baseline_source?: string | null
  baseline_hash?: string | null
  // §MCPTEST30 (V0561): the peer's own counters for both documents (reported, never trusted to excuse a drift)
  admitted_policy_version?: number | null
  admitted_policy_source?: string | null
  live_policy_version?: number | null
  live_policy_source?: string | null
}

export interface PreviewQuarantineRow {
  operator_id: string
  display_name: string
  frame: string
  role: string
  peer_registry_id: number | null
  peer_name: string | null
  peer_url: string | null
  has_compliance_record: boolean
  reachable: boolean | null
  hash_match: boolean | null
  would_action: string
  severity: string | null
  grace_hours: number | null
  detail: string | null
  trust_domain?: string | null
}

export interface PreviewQuarantineResponse {
  generated_at: string
  mode_at_check: EnforcementMode
  total_peers: number
  would_quarantine_count: number
  would_noop_count: number
  skipped_count: number
  peers: PreviewQuarantineRow[]
}

export interface ComplianceEvent {
  event_type: string
  aggregate_id: string
  aggregate_type: string
  timestamp: string
  data: Record<string, unknown>
}

export interface EventsResponse {
  total: number
  events: ComplianceEvent[]
  // §MCPTEST30 (V0561): the types the store did not answer, and one sentence when it answered none
  unreadable?: Array<{ event_type: string; reason: string }>
  error?: string
}

export interface DriftEvent {
  event_type: string
  aggregate_id: string
  aggregate_type: string
  timestamp: string
  data: Record<string, unknown>
  // §MCPTEST30 (V0561): the peer a drift names, as this registry knows it now (DELETED: no row any more)
  peer?: { id: number; name: string | null; status: string } | null
}

export interface DriftListResponse {
  total: number
  by_type: Record<string, number>
  drifts: DriftEvent[]
  error?: string
}

export interface DriftScanResult {
  status: string
  total_drifts: number
  by_drift_type: Record<string, number>
  scanned_at: string
  note?: string
}

export interface PollNowResult {
  status: string
  peer_id?: number
  peer_name?: string
  mode_used?: EnforcementMode
  drift_detected?: boolean
  quarantine_triggered?: boolean
  poll_failure?: boolean
  detail?: string
}

// ── Cross-frame trust-bundle drift (federation_trust_drift_scan.sh port) ─────
// §MCPTEST30 (V0561): keyed by trust domain, the federation's actual frames (the retired A/B/C columns are gone)
export interface TrustBundleFrame {
  trust_domain: string
  name: string | null
  ca_count: number // CA certificates of this frame in THIS registry's own trust bundle
}

export interface TrustBundleOpRow {
  op: string
  frame: string | null
  trusts: Record<string, boolean | null> // trust domain -> the gateway trusts that frame's CA (null: not measured)
  complete: boolean | null
  missing: string[] // trust domains
  error: string | null
}

export interface TrustBundleMatrix {
  scanned_at: string
  source: string
  frames: TrustBundleFrame[]
  total: number
  complete: number
  drift: number
  errors: number
  frame_ca_error: string | null
  gateways_readable: boolean
  gateways_unreadable_reason: string | null
  ops: TrustBundleOpRow[]
}

// ── API client ────────────────────────────────────────────────────────────

const BASE = '/admin/federation/compliance'
const ENFORCEMENT_BASE = '/admin/enforcement'

// §TRUSTPOLICY (2026-09-11) — what this frame thinks of its peers, and what it does about it.
// It lives on CONSUL because CONSUL is already the page that answers that question for policy
// drift, reachability and quarantine; peer trust is the same question with different evidence.
export interface PeerTrustRow {
  id: number
  name: string
  peer_type: string
  status: string
  total_interactions: number
  disputes_lost_with: number
  bayesian_discount: number | null
  last_interaction_at: string | null
  /** unmeasured | ok | warn | restricted | suspended */
  state: string
  /** the sentence a human reads — never the bare number */
  label: string
  reason: string
  threshold_key: string | null
  threshold: number | null
  mode: string
  /** true only when this frame is actually withholding something */
  enforced: boolean
}

export interface PeerTrustPosture {
  mode: string
  min_interactions: number
  warn_below: number
  restrict_below: number
  suspend_below: number
  recover_margin: number
  policy_version: number
  policy_source: string
}

export interface PeerTrustOverview {
  posture: PeerTrustPosture
  by_state: Record<string, number>
  peers: PeerTrustRow[]
  note: string
}

export const consulApi = {
  async getPeerTrust(): Promise<PeerTrustOverview> {
    const { data } = await apiClient.get<PeerTrustOverview>('/admin/federation/peer-trust')
    return data
  },

  async getMode(): Promise<EnforcementModeState> {
    const { data } = await apiClient.get<EnforcementModeState>(
      `${BASE}/enforcement-mode`,
    )
    return data
  },

  async setMode(mode: EnforcementMode, reason: string): Promise<EnforcementModeState> {
    const { data } = await apiClient.post<EnforcementModeState>(
      `${BASE}/enforcement-mode`,
      { mode, reason },
    )
    return data
  },

  async getOverview(): Promise<ComplianceOverview> {
    const { data } = await apiClient.get<ComplianceOverview>(`${BASE}/overview`)
    return data
  },

  async getTrustBundleMatrix(): Promise<TrustBundleMatrix> {
    const { data } = await apiClient.get<TrustBundleMatrix>(
      `${BASE}/trust-bundle-matrix`,
    )
    return data
  },

  async getPeerDetail(peerId: number): Promise<PeerDetail> {
    const { data } = await apiClient.get<PeerDetail>(`${BASE}/peers/${peerId}`)
    return data
  },

  async getPeerDetailByOperator(operatorId: string): Promise<PeerDetail> {
    const { data } = await apiClient.get<PeerDetail>(
      `${BASE}/peers/by-operator/${encodeURIComponent(operatorId)}`,
    )
    return data
  },

  async getEvents(limit = 50, eventTypes?: string): Promise<EventsResponse> {
    const params: Record<string, string | number> = { limit }
    if (eventTypes) params.event_types = eventTypes
    const { data } = await apiClient.get<EventsResponse>(`${BASE}/events`, { params })
    return data
  },

  async pollPeerNow(peerId: number, dryRunOnly = true): Promise<PollNowResult> {
    const { data } = await apiClient.post<PollNowResult>(
      `${BASE}/peers/${peerId}/poll-now`,
      { dry_run_only: dryRunOnly },
    )
    return data
  },

  async previewQuarantine(): Promise<PreviewQuarantineResponse> {
    const { data } = await apiClient.get<PreviewQuarantineResponse>(
      `${BASE}/preview-quarantine`,
    )
    return data
  },

  async getDrifts(limit = 25, driftType?: string): Promise<DriftListResponse> {
    const params: Record<string, string | number> = { limit }
    if (driftType) params.drift_type = driftType
    const { data } = await apiClient.get<DriftListResponse>(`${BASE}/drifts`, { params })
    return data
  },

  async runDriftScan(): Promise<DriftScanResult> {
    const { data } = await apiClient.post<DriftScanResult>(
      `/admin/federation/drift-scan`,
      {},
    )
    return data
  },

  // 2026-04-28: federation_sync manual trigger.
  // Triggers an immediate sync cycle against all ACTIVE peers (instead of
  // waiting for the 300s background interval). Returns per-peer outcome.
  async triggerFederationSync(): Promise<{
    status: string
    synced_peers: number
    total_peers: number
    cascade_sent: number
    cascade_requested: boolean
    timestamp: string
  }> {
    const { data } = await apiClient.post(
      `/federation/sync/trigger`,
      {},
    )
    return data
  },

  // ── Mutations via the existing enforcement_admin router ─────────────────

  async manualQuarantine(
    peerId: number,
    payload: { reason: string; grace_hours: number },
  ): Promise<{
    peer_registry_id: number
    federation_status: string
    grace_hours: number
    quarantined_by: string
  }> {
    const { data } = await apiClient.post(
      `${ENFORCEMENT_BASE}/registries/${peerId}/quarantine`,
      payload,
    )
    return data
  },

  async liftQuarantine(
    peerId: number,
    payload: { new_policy_hash: string },
  ): Promise<{
    peer_registry_id: number
    federation_status: string
    new_policy_hash: string
    lifted_by: string
  }> {
    const { data } = await apiClient.post(
      `${ENFORCEMENT_BASE}/registries/${peerId}/lift-quarantine`,
      payload,
    )
    return data
  },

  /** §MCPTEST30 (V0561): make a federated peer's CURRENT policy its baseline. Refused (409) unless expectedHash is the
   *  hash the peer publishes now; the reason is kept on the ledger. */
  async acceptBaseline(
    peerId: number,
    payload: { expected_hash: string; reason: string },
  ): Promise<{
    status: 'accepted' | 'unchanged'
    peer_registry_id: number
    previous_hash?: string
    new_hash?: string
    baseline_hash?: string
    ledger_recorded?: boolean
  }> {
    const { data } = await apiClient.post(`${BASE}/peers/${peerId}/accept-baseline`, payload)
    return data
  },

  async blacklist(
    peerId: number,
    payload: { reason: string },
  ): Promise<{
    peer_registry_id: number
    federation_status: string
    reason: string
    blacklisted_by: string
    warning: string
  }> {
    const { data } = await apiClient.post(
      `${ENFORCEMENT_BASE}/registries/${peerId}/blacklist`,
      payload,
    )
    return data
  },
}
