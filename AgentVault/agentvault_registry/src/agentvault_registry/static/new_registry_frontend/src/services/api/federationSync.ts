/**
 * services/api/federationSync.ts — Federation sync observability (§pass29 Phase 6).
 *
 *   GET /admin/federation-sync/status   — fleet snapshot
 *   GET /admin/federation-sync/peers    — per-peer detail with filters
 *
 * Auth: admin_platform.
 */
import { apiClient } from './client'

export interface FedRegistryRow {
  registry_id: string
  cycles_24h: number
  errors_24h: number
  last_success_iso: string | null
  seconds_since_success: number | null
  last_duration_ms: number
}

export type PeerFreshness = 'fresh' | 'stale' | 'very_stale' | 'never'

export interface FedPeerRow {
  id: number
  name: string
  base_url: string
  status: string
  peer_type: string
  parent_registry_id: number | null
  parent_name: string | null
  is_chain_child: boolean
  /** Last direct-sync timestamp. Frozen for chain children since 2026-05-05 topology demotion. */
  last_synced_iso: string | null
  seconds_since_sync: number | null
  /** §pass30: max agent_cards.updated_at where source_registry matches this peer — the canonical freshness signal. */
  last_card_received_iso: string | null
  seconds_since_card: number | null
  card_count: number
  /** Composite: derived from the BETTER of last_synced or last_card_received. */
  freshness: PeerFreshness
  health_check_failure_count: number
  last_health_check_attempt_iso: string | null
  attempts_24h: {
    success: number
    error: number
    skipped?: number
  }
}

export interface FedLocalCycle {
  last_cycle_iso: string | null
  last_duration_ms: number
  active_peers: number
  license_gated_skipped: number
  success_count: number
  error_count: number
  cycle_error: string | null
}

export interface FedSyncStatusResponse {
  summary: {
    cycles_24h: number
    errors_24h: number
    registries_reporting: number
    active_peers: number
    total_peers: number
    stale_active_peers: number
    interval_sec: number
  }
  errors_by_reason: Record<string, number>
  per_registry: FedRegistryRow[]
  per_peer: FedPeerRow[]
  local_last_cycle: FedLocalCycle
  snapshot_iso: string
}

export interface FedPeersResponse {
  peers: FedPeerRow[]
  total_returned: number
  filters_applied: { status: string | null; stale_only: boolean }
}

export async function getFederationSyncStatus(): Promise<FedSyncStatusResponse> {
  const r = await apiClient.get<FedSyncStatusResponse>('/admin/federation-sync/status')
  return r.data
}

export async function getFederationSyncPeers(opts: {
  status?: string
  stale_only?: boolean
} = {}): Promise<FedPeersResponse> {
  const params = new URLSearchParams()
  if (opts.status) params.set('status', opts.status)
  if (opts.stale_only) params.set('stale_only', 'true')
  const q = params.toString()
  const url = '/admin/federation-sync/peers' + (q ? `?${q}` : '')
  const r = await apiClient.get<FedPeersResponse>(url)
  return r.data
}
