/**
 * useFederationTopology — shared topology fetch + v0.3 merge for Federation
 * surfaces (Network tab + Federation Discovery + future flagship views).
 *
 * 2026-05-21 (§pass62) — extracted from Federation.vue's loadTopology +
 * mergeV03IntoBuckets so multiple views can share the same data pipeline.
 * Each consumer wires its own polling timer + hover-gate logic; this
 * composable provides only fetch + merge + reactive state.
 *
 * Memory references:
 *   - feedback_federation_v03_field_propagation  (admin endpoint dead-letters
 *     visual; public registries[] has v0.3 fields; merge by name match)
 *   - feedback_topology_local_entry_name_mismatch (match local by
 *     domain==='__local__' or hopDepth===0, NOT by name)
 */
import { ref, computed, type Ref } from 'vue'
import { apiClient } from '@/services/api/client'

export interface PeerVisualV03 {
  theme?: string | null
  icon_url?: string | null
  icon_etag?: string | null
  icon_size_bytes?: number | null
  orb_color?: string | null
  orb_glow_color?: string | null
  orb_pulse_speed_hz?: number | null
  orb_size_px?: number | null
  halo_enabled?: boolean | null
  halo_thickness?: number | null
  sovereign_variant?: string | null
  flare_corner_variant?: string | null
  flare_encirclement_variant?: string | null
  flare_encirclement_overlay?: string | null
  schema_compat?: string | null
}

export interface PeerFeesV03 {
  intra_registry?: number | null
  cross_registry?: number | null
  hosting_enabled?: boolean | null
  hosting_rate?: number | null
}

export interface PeerLifecycleV03 {
  status?: string | null
  card_etag?: string | null
  card_updated_at?: string | null
  quarantine_reason?: string | null
}

export interface PeerBundleFreshness {
  trust_domain: string
  not_before: string | null
  not_after: string | null
  age_seconds: number | null
  expires_in_seconds: number | null
  refresh_overdue: boolean
  refresh_critical: boolean
  error: string | null
}

export interface FederatedPeer {
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
  total_interactions?: number
  disputes_lost_with?: number
  bayesian_discount?: number
  last_interaction_at?: string | null
  drift_flags?: string[]
  has_drift?: boolean
  bundle_freshness?: PeerBundleFreshness | null
  // Card v0.3 (§pass60-60.2)
  visual?: PeerVisualV03 | null
  fees?: PeerFeesV03 | null
  fees_summary?: PeerFeesV03 | null
  lifecycle?: PeerLifecycleV03 | null
  card_etag?: string | null
  card_signature_verified?: boolean
  card_signature_kid?: string | null
  card_last_pulled_at?: string | null
}

export interface FederationTopologyResponse {
  frames: FederatedPeer[]
  direct_peers: FederatedPeer[]
  discovered: FederatedPeer[]
  cloud_operators: FederatedPeer[]
  summary?: {
    total_peers: number
    peers_by_type: Record<string, number>
    license_status_breakdown: Record<string, number>
    drift_count: number
    oldest_discovered_at: string | null
    healthy_count: number
    bundles_fresh?: number
    bundles_overdue?: number
    bundles_critical?: number
    bundles_unknown?: number
    oldest_bundle_age_seconds?: number | null
  }
  registries?: Array<{
    name: string
    publicUrl: string
    domain: string
    hopDepth: number
    trust_domain?: string | null
    visual?: PeerVisualV03 | null
    fees_summary?: PeerFeesV03 | null
    card_etag?: string | null
    card_signature_verified?: boolean | null
  }>
  edges?: string[]
  topology_version?: number
}

/**
 * §pass61.1 fix — admin endpoint returns visual=null for every peer in the
 * tier buckets. Public /topology returns full visual on registries[]. Merge
 * by name match (case-insensitive) so peers in admin buckets carry their
 * v0.3 visual identity for the FE to render. Without this, peers fall back
 * to tier-color orbs with no flare.
 */
function mergeV03IntoBuckets(admin: any, pub: any): FederationTopologyResponse {
  if (!admin || !pub?.registries) return admin
  const byName: Record<string, any> = {}
  for (const reg of pub.registries) {
    if (!reg?.name) continue
    byName[reg.name.toLowerCase()] = {
      visual: reg.visual ?? null,
      fees_summary: reg.fees_summary ?? null,
      card_etag: reg.card_etag ?? null,
      card_signature_verified: reg.card_signature_verified ?? null,
      trust_domain: reg.trust_domain ?? null,
    }
  }
  function enrich(peer: any) {
    if (!peer?.name) return peer
    const v = byName[peer.name.toLowerCase()]
    if (!v) return peer
    return {
      ...peer,
      visual: peer.visual ?? v.visual,
      fees_summary: peer.fees_summary ?? v.fees_summary,
      card_etag: peer.card_etag ?? v.card_etag,
      card_signature_verified: peer.card_signature_verified ?? v.card_signature_verified,
      trust_domain: peer.trust_domain ?? v.trust_domain,
    }
  }
  return {
    ...admin,
    frames: (admin.frames || []).map(enrich),
    direct_peers: (admin.direct_peers || []).map(enrich),
    discovered: (admin.discovered || []).map(enrich),
    cloud_operators: (admin.cloud_operators || []).map(enrich),
  }
}

export interface UseFederationTopologyOptions {
  /**
   * When true, calls admin topology endpoint first then merges public.
   * When false, only calls public endpoint. Defaults to true (caller should
   * gate this on auth state if needed — falls back gracefully on 403).
   */
  admin?: boolean
}

export interface UseFederationTopologyReturn {
  topology: Ref<FederationTopologyResponse | null>
  isLoading: Ref<boolean>
  error: Ref<string | null>
  lastFetchedAt: Ref<Date | null>
  /** Concatenation of frames/direct_peers/discovered/cloud_operators after merge */
  allPeers: Ref<FederatedPeer[]>
  /** The local registry entry from registries[] (matched by domain==='__local__' or hopDepth===0) */
  localRegistry: Ref<any>
  fetchTopology: () => Promise<void>
}

export function useFederationTopology(
  opts: UseFederationTopologyOptions = {}
): UseFederationTopologyReturn {
  const useAdmin = opts.admin !== false
  const topology = ref<FederationTopologyResponse | null>(null)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const lastFetchedAt = ref<Date | null>(null)

  const allPeers = computed<FederatedPeer[]>(() => {
    const t = topology.value
    if (!t) return []
    return [
      ...(t.frames || []),
      ...(t.direct_peers || []),
      ...(t.discovered || []),
      ...(t.cloud_operators || []),
    ]
  })

  // Memory: feedback_topology_local_entry_name_mismatch — match by stable id
  const localRegistry = computed(() => {
    return topology.value?.registries?.find(
      r => r.domain === '__local__' || r.hopDepth === 0
    ) || null
  })

  async function fetchTopology() {
    isLoading.value = true
    error.value = null
    try {
      if (useAdmin) {
        try {
          const res = await apiClient.get('/admin/federation/topology-overview')
          // Layer in legacy /public/topology edges + merge v0.3 fields into admin buckets
          try {
            const pub = await apiClient.get('/public/topology')
            const merged = mergeV03IntoBuckets(res.data, pub.data)
            topology.value = {
              ...merged,
              registries: pub.data?.registries,
              edges: pub.data?.edges,
            }
          } catch {
            topology.value = res.data
          }
        } catch (adminErr: any) {
          // Fall back to public on 403
          if (adminErr?.response?.status === 403) {
            const res = await apiClient.get('/public/topology')
            topology.value = res.data
          } else {
            throw adminErr
          }
        }
      } else {
        const res = await apiClient.get('/public/topology')
        topology.value = res.data
      }
      lastFetchedAt.value = new Date()
    } catch (e: any) {
      error.value = e?.response?.data?.detail || e?.message || 'Failed to load topology'
    } finally {
      isLoading.value = false
    }
  }

  return {
    topology,
    isLoading,
    error,
    lastFetchedAt,
    allPeers,
    localRegistry,
    fetchTopology,
  }
}

// ───────────────────────────────────────────────────────────────────────
// §pass62.6 (2026-05-21) — Topology derivation helpers.
//
// Mirrors the Federation Network tab's tree-walk (Federation.vue:781-859
// `childrenByParent` + `placeSubtree`). Network tab places nodes at the
// recursive tree depth — NOT at the raw `peer.hop_distance` column —
// which is why its rendering is "correct" while FederationDiscovery cards
// (which display raw `peer.hop_distance`) look wrong for chained peers.
//
// These helpers let any view derive the SAME tree-walk depth + chain path
// as the Network tab, without any DB or backend change. Pure frontend.
// ───────────────────────────────────────────────────────────────────────

/** Build a peer.id → peer lookup map for O(1) parent-chain traversal. */
export function buildPeersById(peers: FederatedPeer[]): Map<number, FederatedPeer> {
  return new Map(peers.map(p => [p.id, p]))
}

/**
 * Derive the tree-walk depth from the local registry.
 *
 * Roots (depth = 1):
 *   - peer_type === 'frame'        (cross-frame mainframe)
 *   - parent_registry_id == null   (directly registered to local — chain root)
 *
 * For everything else, walks the parent chain via `peersById` and counts
 * the depth. The depth STOPS when we hit a frame peer or a root peer.
 *
 * Examples (on Frame A, with original chained data):
 *   - Frame-B:        peer_type='frame'      → 1
 *   - op-berlin:      parent_registry_id=null → 1
 *   - op-london:      parent=op-berlin (root)  → 2
 *   - op-paris:       parent=op-london (2)      → 3
 *   - op-tokyo:       parent=Frame-B (root)    → 2
 *   - op-seoul:       parent=op-tokyo (2)       → 3
 *   - op-sydney:      parent=op-seoul (3)       → 4
 *
 * Bounded by maxDepth + cycle guard so a corrupted DB can't loop forever.
 */
export function deriveDisplayHop(
  peer: FederatedPeer,
  peersById: Map<number, FederatedPeer>,
  maxDepth = 10
): number {
  if (peer.peer_type === 'frame') return 1
  if (peer.parent_registry_id == null) return 1
  let depth = 1
  let cur: FederatedPeer | undefined = peer
  const seen = new Set<number>()
  while (cur?.parent_registry_id != null && depth < maxDepth) {
    if (seen.has(cur.id)) break
    seen.add(cur.id)
    const parent = peersById.get(cur.parent_registry_id)
    if (!parent) break
    depth += 1
    if (parent.peer_type === 'frame' || parent.parent_registry_id == null) break
    cur = parent
  }
  return depth
}

/**
 * Build the human-readable chain from the local registry to this peer.
 * Returns names in path order, e.g.
 *   ['Local', 'op-berlin', 'op-london', 'op-paris']
 *   ['Local', 'Frame-B', 'op-tokyo', 'op-seoul', 'op-sydney']
 *
 * `localName` is whatever you want to show for the local-registry root
 * (defaults to 'Local'; pass `localRegistry.value?.name` for the real name).
 */
export function deriveChainPath(
  peer: FederatedPeer,
  peersById: Map<number, FederatedPeer>,
  localName = 'Local'
): string[] {
  const path: string[] = [peer.name || `peer-${peer.id}`]
  let cur: FederatedPeer | undefined = peer
  const seen = new Set<number>()
  while (cur?.parent_registry_id != null && path.length < 10) {
    if (seen.has(cur.id)) break
    seen.add(cur.id)
    const parent = peersById.get(cur.parent_registry_id)
    if (!parent) break
    path.unshift(parent.name || `peer-${parent.id}`)
    cur = parent
  }
  path.unshift(localName)
  return path
}
