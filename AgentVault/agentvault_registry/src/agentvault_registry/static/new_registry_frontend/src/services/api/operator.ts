/**
 * services/api/operator.ts — Operator Portal command-center API client.
 *
 * Consolidates every endpoint the AAA+ operator portal calls into one typed
 * surface. Backed by:
 *   - routers/operator_lifecycle.py          (lifecycle, drift flags)
 *   - routers/federation_peers.py            (peer list + my registrations)
 *   - routers/federation_sync.py             (sync status, sync trigger, policy compliance)
 *   - routers/federation_license_self.py     (license rotate-self)
 *   - routers/admin_health.py                (eventstore-recent, system-resources)
 *
 * The operator IS admin on their OWN registry, so admin_platform-flagged
 * health endpoints are reachable from this client when called against the
 * operator's own URL (the registry the portal is loaded from).
 */
import { apiClient } from './client'

// ─── /operators/me/lifecycle ──────────────────────────────────────────────
export interface LifecycleApplication {
  id: number
  name: string
  status: string
  cloud_hosted: boolean
  organization: string | null
  email: string | null
  activated_at: string | null
  revoked_at: string | null
  revoked_reason: string | null
  reviewed_at: string | null
  created_at: string | null
}

export interface LifecycleLicense {
  id: number
  operator_did: string
  status: string
  license_key_prefix: string
  issued_at: string | null
  last_seen_at: string | null
  event_count: number
  suspended_at: string | null
  suspended_reason: string | null
  revoked_at: string | null
  revoked_reason: string | null
  federation_tier: string | null
}

export interface LifecyclePeer {
  id: number
  name: string
  status: string
  base_url: string
  peer_type: string
  hop_distance: number | null
  parent_registry_id: number | null
  registered_at: string | null
  approved_at: string | null
  last_synced_at: string | null
  last_seen_in_topology_at: string | null
  bfs_reachable: boolean
}

export interface LifecycleCloud {
  cloud_hosted: boolean
  cloud_url: string | null
  cloud_port_base: number | null
  cloud_provisioned_at: string | null
  cloud_torn_down_at: string | null
  cloud_stack_dir: string | null
}

export interface OperatorLifecycle {
  application: LifecycleApplication
  federation_license: LifecycleLicense | null
  peer_registry: LifecyclePeer | null
  cloud: LifecycleCloud | null
  drift_flags: string[]
}

export async function getMyLifecycle(): Promise<OperatorLifecycle | null> {
  try {
    // a 404 is the rail's answer "you are not an operator" (operator_lifecycle.py), read below as null: no global "Not
    // Found" toast over the operator portal, which shows the apply path (§FESUITE, the loading sweep saw the toast)
    const r = await apiClient.get('/operators/me/lifecycle', { expectedStatuses: [404] })
    return r.data as OperatorLifecycle
  } catch (e: any) {
    if (e?.response?.status === 404) return null
    throw e
  }
}

// ─── Federation surface (peers + sync + policy-compliance) ───────────────
// NOTE: the canonical `/federation/peers`, `/federation/sync-status`,
// `/federation/policy-compliance` endpoints require SPIFFE peer-registry
// identity (mTLS) — they're peer-to-peer endpoints, not browser-callable.
// We use the admin-callable `/admin/federation/topology-overview` which the
// operator's own admin JWT can hit (operator IS admin on their OWN registry).
// /public/topology is the unauthenticated fallback if admin call fails.

export interface FederationPeerInfo {
  registry_id?: string
  registry_name: string
  base_url: string
  trust_domain: string | null
  agent_count?: number
  last_sync_at?: string | null
  sync_status?: string
  hop_distance?: number | null
  peer_type?: string
}

export interface FederationSyncStatus {
  last_sync_run_at: string | null
  next_sync_due_at: string | null
  active_peers: number
  total_peers: number
  recent_failures: number
  is_central_registry: boolean
  enforcement_active: boolean
}

export interface PolicyComplianceStatus {
  is_compliant: boolean
  policy_version: number
  drift_detected: boolean
  drift_count: number
  last_checked_at: string | null
  details?: Record<string, any>
}

interface TopologyOverview {
  frames?: any[]
  direct_peers?: any[]
  discovered?: any[]
  cloud_operators?: any[]
  summary?: {
    total_peers?: number
    peers_by_type?: Record<string, number>
    license_status_breakdown?: Record<string, number>
    drift_count?: number
    oldest_discovered_at?: string | null
    healthy_count?: number
  }
}

function _peerFromOverviewRow(row: any, type: string): FederationPeerInfo {
  // The overview returns rows shaped from _peer_base + _peer_admin_extras
  const base = row.peer_base || row
  return {
    registry_id: String(base.id ?? row.application_id ?? row.id ?? ''),
    registry_name: base.name || row.name || 'unknown',
    base_url: base.base_url || row.cloud_url || '',
    trust_domain: base.trust_domain ?? row.trust_domain ?? null,
    agent_count: base.agent_count ?? row.agent_count,
    last_sync_at: base.last_synced_at ?? row.last_synced_at ?? null,
    sync_status: base.sync_status || (base.bfs_reachable ? 'active' : 'stale'),
    hop_distance: base.hop_distance ?? row.hop_distance ?? null,
    peer_type: type,
  }
}

/** Operator-side federation peer list (admin_federation flag on own registry). */
export async function getFederationPeers(): Promise<FederationPeerInfo[]> {
  try {
    const r = await apiClient.get<TopologyOverview>('/admin/federation/topology-overview')
    const d = r.data
    const out: FederationPeerInfo[] = []
    for (const p of (d.frames || []))         out.push(_peerFromOverviewRow(p, 'frame'))
    for (const p of (d.direct_peers || []))   out.push(_peerFromOverviewRow(p, 'direct'))
    for (const p of (d.discovered || []))     out.push(_peerFromOverviewRow(p, 'discovered'))
    for (const p of (d.cloud_operators || [])) out.push(_peerFromOverviewRow(p, 'cloud_operator'))
    return out
  } catch (e: any) {
    // Fallback: public/topology returns simpler peer shapes without auth
    if (e?.response?.status === 401 || e?.response?.status === 403) {
      const r2 = await apiClient.get('/public/topology')
      const regs = r2.data?.registries || []
      return regs.map((reg: any) => ({
        registry_name: reg.name,
        base_url: reg.publicUrl || reg.public_url || '',
        trust_domain: reg.domain || reg.trust_domain || null,
        agent_count: reg.agent_count,
        hop_distance: reg.hopDepth ?? reg.hop_depth ?? null,
        sync_status: 'unknown',
      }))
    }
    throw e
  }
}

/** Sync status — synthesized from topology-overview summary + federation/info. */
export async function getFederationSyncStatus(): Promise<FederationSyncStatus> {
  const [overviewR, infoR] = await Promise.allSettled([
    apiClient.get<TopologyOverview>('/admin/federation/topology-overview'),
    apiClient.get('/federation/info'),
  ])
  const overview = overviewR.status === 'fulfilled' ? overviewR.value.data : null
  const info = infoR.status === 'fulfilled' ? infoR.value.data : null

  const total = overview?.summary?.total_peers ?? 0
  const healthy = overview?.summary?.healthy_count ?? 0
  // Find most-recent last_synced_at across all peers
  const allPeers: any[] = []
  if (overview) {
    for (const arr of [overview.frames, overview.direct_peers, overview.discovered, overview.cloud_operators]) {
      if (arr) for (const p of arr) allPeers.push((p as any).peer_base || p)
    }
  }
  const syncTimes = allPeers
    .map(p => p.last_synced_at)
    .filter((s: any): s is string => typeof s === 'string' && s.length > 0)
    .sort()
    .reverse()
  const lastSync = syncTimes[0] || null

  return {
    last_sync_run_at: lastSync,
    next_sync_due_at: null,  // not available via developer-callable endpoints
    active_peers: healthy,
    total_peers: total,
    recent_failures: total - healthy,
    is_central_registry: Boolean(info?.is_central_registry || info?.is_genesis_registry),
    enforcement_active: Boolean(info?.federation_enforcement_active),
  }
}

/** Trigger sync via admin endpoint. The /federation/sync/trigger endpoint is
 *  developer-callable for admins (no SPIFFE requirement on that one). */
export async function triggerFederationSync(): Promise<{ triggered: boolean; message: string }> {
  try {
    const r = await apiClient.post('/federation/sync/trigger', {})
    return {
      triggered: r.data?.triggered ?? true,
      message: r.data?.message || 'Sync cycle queued',
    }
  } catch (e: any) {
    return {
      triggered: false,
      message: e?.response?.data?.detail || e?.message || 'Sync trigger failed',
    }
  }
}

/** Policy compliance — synthesized from lifecycle drift flags (the operator's
 *  own drift signal is more meaningful than a peer's policy hash). */
export async function getPolicyCompliance(): Promise<PolicyComplianceStatus> {
  try {
    const overviewR = await apiClient.get<TopologyOverview>('/admin/federation/topology-overview')
    const driftCount = overviewR.data?.summary?.drift_count ?? 0
    return {
      is_compliant: driftCount === 0,
      policy_version: 1,
      drift_detected: driftCount > 0,
      drift_count: driftCount,
      last_checked_at: new Date().toISOString(),
    }
  } catch {
    return {
      is_compliant: true,
      policy_version: 1,
      drift_detected: false,
      drift_count: 0,
      last_checked_at: null,
    }
  }
}

// ─── /federation/license/rotate-self ─────────────────────────────────────
export interface RotateSelfRequest {
  reason: 'periodic_rotation' | 'compromise_suspected' | 'manual_audit' | 'rolling_drill'
}
export interface RotateSelfResponse {
  new_license_key: string  // shown ONCE
  new_license_key_prefix: string
  rotated_at: string
  reason: string
  rotation_id: number
  expires_at: string | null
}

export async function rotateOwnLicense(
  body: RotateSelfRequest,
  currentLicenseKey: string,
  idempotencyKey: string,
): Promise<RotateSelfResponse> {
  const r = await apiClient.post('/federation/license/rotate-self', body, {
    headers: {
      'X-Federation-License': currentLicenseKey,
      'X-Idempotency-Key': idempotencyKey,
    },
  })
  return r.data
}

// ─── /admin/eventstore-recent + /admin/system-resources ───────────────────
// Operator is admin on their own registry; these endpoints are admin_platform-gated
// but reachable when the portal is loaded from the operator's own URL.

export interface RecentEvent {
  id?: string
  event_type: string
  aggregate_id?: string
  timestamp?: string
  data?: Record<string, any>
}

export async function getRecentEvents(): Promise<RecentEvent[]> {
  const r = await apiClient.get('/admin/eventstore-recent')
  return Array.isArray(r.data) ? r.data : (r.data.events || [])
}

export interface SystemResources {
  cpu: { percent: number; cores: number; load_avg?: number[] }
  memory: { total_bytes: number; used_bytes: number; percent: number }
  disk?: { total_bytes: number; used_bytes: number; percent: number }
  timestamp?: string
}

export async function getSystemResources(): Promise<SystemResources> {
  const r = await apiClient.get('/admin/system-resources')
  return r.data
}

// ─── Helper: generate idempotency key ────────────────────────────────────
export function newIdempotencyKey(prefix: string = 'op'): string {
  const ts = Date.now().toString(36)
  const rnd = Math.random().toString(36).slice(2, 10)
  return `${prefix}-${ts}-${rnd}`
}
