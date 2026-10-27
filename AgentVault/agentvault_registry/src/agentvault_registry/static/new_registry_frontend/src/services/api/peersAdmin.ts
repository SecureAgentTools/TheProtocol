/**
 * services/api/peersAdmin.ts — Federation peer health admin wrapper.
 *
 * Build #13 (2026-05-07) — REWRITTEN 2026-05-08 (polish pass): switched
 * from the redundant /admin/peers/health endpoint to the canonical
 * /admin/federation/topology-overview which Federation.vue already uses.
 * The canonical endpoint adds license state, drift flags, BFS reachability,
 * SPIRE bundle status — fields my custom endpoint never surfaced.
 *
 * Backend: routers/admin_federation.py:get_topology_overview
 * Auth: admin_federation flag.
 *
 * Type definitions mirror Federation.vue's PeerBase + TopologyResponse to
 * keep the contract aligned across both views.
 */
import { apiClient } from './client'

export interface FederationPeerRow {
  id: number
  name: string
  base_url: string
  status: string
  peer_type: string
  hop_distance: number | null
  discovered_at: string | null
  registered_at: string | null
  approved_at: string | null
  last_synced_at: string | null
  operator_did: string | null
  trust_domain: string | null
  parent_registry_id: number | null
  parent_name?: string | null
  last_seen_in_topology_at?: string | null
  bfs_reachable?: boolean
  // Admin-only fields (always present in topology-overview)
  license_id?: string | null
  license_status?: string | null
  license_key_prefix?: string | null
  license_suspended_at?: string | null
  license_suspended_reason?: string | null
  license_revoked_at?: string | null
  license_revoked_reason?: string | null
  federation_tier?: string | null
  application_id?: string | null
  application_status?: string | null
  cloud_hosted?: boolean
  cloud_url?: string | null
  cloud_provisioned_at?: string | null
  cloud_torn_down_at?: string | null
  health_check_failure_count?: number
  last_health_check_attempt_at?: string | null
  healthy?: boolean
  spire_bundle_active?: boolean
  total_interactions?: number
  disputes_lost_with?: number
  bayesian_discount?: number
  last_interaction_at?: string | null
  drift_flags?: string[]
  has_drift?: boolean
}

export interface TopologySummary {
  total_peers: number
  peers_by_type: Record<string, number>
  license_status_breakdown: Record<string, number>
  drift_count: number
  oldest_discovered_at: string | null
  healthy_count: number
}

export interface TopologyOverview {
  frames: FederationPeerRow[]
  direct_peers: FederationPeerRow[]
  discovered: FederationPeerRow[]
  cloud_operators: FederationPeerRow[]
  summary?: TopologySummary
  topology_version?: number
}

class PeersAdminService {
  async topologyOverview(): Promise<TopologyOverview> {
    try {
      const resp = await apiClient.get('/admin/federation/topology-overview')
      return resp.data
    } catch (err) {
      console.error('Failed to load topology overview:', err)
      throw err
    }
  }
}

export const peersAdminService = new PeersAdminService()

// ── Drift label + remediation hints (mirrored from Federation.vue) ─────
export const DRIFT_LABELS: Record<string, string> = {
  license_revoked_operator_active: 'License revoked — operator still active',
  operator_revoked_license_active: 'Operator revoked — license still active',
  peer_inactive_license_active: 'Peer unreachable — direct peering INACTIVE and no chain connection',
  frame_bundle_stale: 'Frame trust bundle stale — SPIRE federation relationship or bundle missing',
  peer_url_misconfigured: 'Peer URL misconfigured — base_url likely missing the :8443 mTLS federation port',
  operator_network_topology: 'Operator Docker network drift — missing identity_network attachment or wrong per-frame alias',
}

export interface DriftHint {
  cause: string
  remediation: string
  cli?: string
  autoHeal?: string
}

export const DRIFT_HINTS: Record<string, DriftHint> = {
  license_revoked_operator_active: {
    cause: 'The operator\'s federation license is revoked but the OperatorApplication is still in approved/suspended state.',
    remediation: 'Reconcile via /admin/operators/{id}/revoke OR reinstate the license if revocation was accidental.',
  },
  operator_revoked_license_active: {
    cause: 'The OperatorApplication is revoked but the FederationLicense is still active. Legacy pre-D2 cascade gap.',
    remediation: 'Revoke the license via /admin/federation/licenses/{id}/revoke to bring states in sync.',
  },
  peer_inactive_license_active: {
    cause: 'peer_registries.status=INACTIVE but the operator\'s license is active AND the peer is NOT chain-reachable via BFS.',
    remediation: 'Either reactivate the peer (admin action), reinstate the license, OR confirm the operator is decommissioned and revoke the license.',
  },
  frame_bundle_stale: {
    cause: 'SPIRE-server lacks either the federation relationship OR the trust bundle for this frame. Cross-frame mTLS will fail.',
    remediation: 'Use Frame Management → "Resync EventStore" on this frame, OR re-import the bundle via FrameTrustManager.add_peer_bundle().',
  },
  peer_url_misconfigured: {
    cause: 'ACTIVE peer has no successful sync in 30+ min. Most common cause: peer.base_url missing the mTLS federation port (:8443 / :27N43).',
    remediation: 'The reactor_peer_url_self_heal worker auto-fixes this within ~5 min by probing alternate ports. Check back, or run drift-scan to retrigger.',
    autoHeal: 'reactor_peer_url_self_heal — usually auto-resolves within one drift cycle',
  },
  operator_network_topology: {
    cause: 'cloud-op-* nginx-federation container is missing one of the identity_networks (agentvault_identity_network, frame_b_identity_network) OR has the wrong per-frame Docker alias.',
    remediation: 'Run the network-topology repair script on the operator host. Sandbox operators are skipped by design.',
    cli: 'bash scripts/fix-operator-networks.sh <operator-name>',
  },
}
