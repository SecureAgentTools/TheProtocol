// Galactic Command Center — same-origin service layer (GCC Phase 1).
//
// Model-A actions execute on THIS registry with the local admin JWT; the backend
// reaches remote registries server-side (SPIRE mTLS / host docker). The browser
// never goes cross-origin. Directory + node→target matching are server-owned
// (routers/admin_command.py) — the FE never slugs names or guesses URLs.
//
// Every financial call carries a client-generated Idempotency-Key (fleet-wide
// support since §pass57) and passes amounts as STRINGS (Decimal doctrine).

import { apiClient } from './client'
import { peerGet, peerPost } from './peer'
import { directoryFromPublicTopology } from '@/services/bridge/publicDirectory'

// ── Directory ────────────────────────────────────────────────────────────────
export interface DirectoryEntry {
  key: string
  name: string
  trust_domain: string | null
  /** Server-stamped home-frame key, or null when the deployment has none
   *  (hetzner-frame, future frames) — OPEN string per config/frames.ts doctrine:
   *  a closed 'A'|'B'|'C' union baked into the API layer caps the app at three
   *  frames and lies on single-frame deployments. */
  frame: string | null
  tier: string
  currency: string
  peer_type: string
  hop_distance: number | null
  is_local: boolean
  card_software_version: string | null
  card_last_pulled_at: string | null
  capabilities: string[]
  match: { names: string[]; trust_domain: string | null }
  /** §FEFRAME W2: where a person opens this registry's console, and the ledger it streams */
  console_url?: string | null
  ws_url?: string | null
  /** §FEFRAME W3: its key in the frame manifest (the session hub's key); `key` is the lowercased peer-row name */
  manifest_key?: string | null
}
export interface RegistryDirectory { local_key: string; registries: DirectoryEntry[] }

export async function getRegistryDirectory(): Promise<RegistryDirectory> {
  const r = await apiClient.get('/admin/command/registry-directory')
  return r.data as RegistryDirectory
}

/**
 * §NONADMINBOARD - the same list, for a developer who is not an admin.
 *
 * `/admin/command/registry-directory` is admin-gated, and the bridge read it
 * as its ONLY source: a 403 left `registryDir` null, which blanked the light
 * bridge board, emptied the star planner's name table and collapsed
 * `localHomeKey` to a key no entry carries. This is the `operator.ts`
 * fallback pattern (401/403 -> `/public/topology`), applied to the directory.
 *
 * It is deliberately a SEPARATE function rather than a fallback inside
 * `getRegistryDirectory`: the admin surfaces (Galactic Command's relay) need
 * the relay + capability fields, which the public topology cannot know, and
 * silently handing them a shape with `relay: null` would trade a clean 403 for
 * a confusing failure deeper in. Callers that can live without those fields
 * opt in by calling this.
 */
export async function getPublicRegistryDirectory(): Promise<RegistryDirectory> {
  const r = await apiClient.get('/public/topology')
  return directoryFromPublicTopology(r.data) as unknown as RegistryDirectory
}

/** The directory if you may have it, the public topology if you may not.
 *  Returns which source answered, because a view that shows a narrower list
 *  has to be able to say so instead of implying the network is smaller. */
export async function getRegistryDirectoryOrPublic(): Promise<{
  directory: RegistryDirectory | null; source: 'admin' | 'public' | 'none'
}> {
  try {
    return { directory: await getRegistryDirectory(), source: 'admin' }
  } catch (e: any) {
    const st = e?.response?.status
    // Only an authorization refusal earns the fallback. A 500 means the
    // directory is broken, and quietly showing a thinner list would hide that.
    if (st !== 401 && st !== 403) return { directory: null, source: 'none' }
    try {
      return { directory: await getPublicRegistryDirectory(), source: 'public' }
    } catch { return { directory: null, source: 'none' } }
  }
}

export interface FleetProbe { health: 'up' | 'degraded' | 'down'; status_code?: number; latency_ms: number; error?: string }
export async function getFleetStatus(): Promise<{ probed_at: number; status: Record<string, FleetProbe> }> {
  const r = await apiClient.get('/admin/command/fleet-status')
  return r.data
}

/** Join a clicked map node to its directory entry (normalized-name first, trust-domain fallback). */
const norm = (s: string | null | undefined) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')
export function resolveDirectoryEntry(
  dir: RegistryDirectory | null,
  node: { name?: string | null; trustDomain?: string | null; hopDepth?: number | null },
): DirectoryEntry | null {
  if (!dir) return null
  if ((node.hopDepth ?? 1) === 0) return dir.registries.find(e => e.is_local) || null
  const n = norm(node.name)
  if (n) {
    const byName = dir.registries.find(e => e.match.names.some(m => norm(m) === n))
    if (byName) return byName
  }
  const td = (node.trustDomain || '').toLowerCase()
  if (td) {
    const tdMatches = dir.registries.filter(e => (e.trust_domain || '').toLowerCase() === td)
    if (tdMatches.length === 1) return tdMatches[0]
  }
  return null
}

// ── Action plumbing ──────────────────────────────────────────────────────────
const idem = () =>
  (globalThis.crypto?.randomUUID?.() as string | undefined) ||
  `gcc-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`

// ── Treasury (Model A + local-to-home) ───────────────────────────────────────
/** Mainframe → remote registry treasury over cross-TEG mTLS (Model A). */
export async function crossTegFund(p: { target_registry: string; amount: string; reason?: string }) {
  const r = await apiClient.post(
    '/teg/treasury/cross-teg-fund',
    { target_registry: p.target_registry, amount: p.amount, reason: p.reason || 'cross_teg_fund' },
    { headers: { 'Idempotency-Key': idem() } },
  )
  return r.data
}

/** Fund an agent homed on THIS registry from THIS registry's treasury (canonical FLOW 4). */
export async function fundAgentLocal(p: { target_agent_did: string; amount: string; reason?: string }) {
  const r = await apiClient.post(
    '/teg/treasury/fund-agent',
    { target_agent_did: p.target_agent_did, amount: p.amount, reason: p.reason || 'gcc_fund' },
    { headers: { 'Idempotency-Key': idem() } },
  )
  return r.data
}

// ── Model B — speak-as-the-target via the same-origin relay (GCC Phase 2) ────
/** Fund an agent on a REMOTE registry from THAT registry's treasury, executed
 *  with the target's own admin JWT relayed via /admin/peer/{key}. */
export async function fundAgentRemote(key: string, adminToken: string, p: { target_agent_did: string; amount: string; reason?: string }) {
  return peerPost(key, 'teg/treasury/fund-agent',
    adminToken,
    { target_agent_did: p.target_agent_did, amount: p.amount, reason: p.reason || 'gcc_fund' },
    { 'Idempotency-Key': idem() })
}

/** Trigger a projection snapshot on a remote registry (its own admin JWT). */
export async function projectionSnapshotRemote(key: string, adminToken: string) {
  return peerPost(key, 'admin/projection-snapshot', adminToken, {})
}

/** Model-L: agent→agent transfer on a registry, executed with the SENDER
 *  agent's own JWT (minted from the scoped roster), relayed same-origin. */
export async function transferAgentRemote(key: string, agentToken: string, p: { receiver_agent_id: string; amount: string; message?: string }) {
  return peerPost(key, 'teg/transfer',
    agentToken,
    { receiver_agent_id: p.receiver_agent_id, amount: p.amount, message: p.message || 'gcc transfer' },
    { 'Idempotency-Key': idem() })
}

// ── Treasury balance (situational awareness — what's in this registry's treasury) ─
export interface TreasuryBalance { agent_id?: string; balance?: string }
/** Local registry's TEG treasury balance. */
export async function treasuryBalanceLocal(): Promise<TreasuryBalance> {
  return (await apiClient.get('/teg/treasury/balance')).data
}
/** A connected remote registry's treasury balance (relayed with its admin token). */
export async function treasuryBalanceRemote(key: string, token: string): Promise<TreasuryBalance> {
  return peerGet(key, 'teg/treasury/balance', token)
}

// ── Registry intel (P7 — dashboard + workers snapshot when local|connected) ──
export interface RegistryIntel {
  agent_count?: number
  active_agents?: number
  developer_count?: number
  workers_total?: number
  workers_with_leader?: number
}
function mergeIntel(dash: any, workers: any): RegistryIntel {
  const d = dash || {}
  const w = workers?.summary || {}
  return {
    agent_count: d.agent_count, active_agents: d.active_agents, developer_count: d.developer_count,
    workers_total: w.total, workers_with_leader: w.with_leader,
  }
}
export async function registryIntelLocal(): Promise<RegistryIntel> {
  const [d, w] = await Promise.allSettled([
    apiClient.get('/admin/dashboard'),
    apiClient.get('/admin/workers/status'),
  ])
  return mergeIntel(d.status === 'fulfilled' ? d.value.data : null, w.status === 'fulfilled' ? w.value.data : null)
}
export async function registryIntelRemote(key: string, token: string): Promise<RegistryIntel> {
  const [d, w] = await Promise.allSettled([
    peerGet(key, 'admin/dashboard', token),
    peerGet(key, 'admin/workers/status', token),
  ])
  return mergeIntel(d.status === 'fulfilled' ? d.value : null, w.status === 'fulfilled' ? w.value : null)
}

// ── Agent finder (P7 — search ANY agent on the target, incl. off-map ones) ───
export interface FoundAgent {
  did: string
  name?: string | null
  client_id: string
  status: string
  enforcement_status?: string
  liquid_balance?: number
  staked_balance?: number
  reputation_score?: number
  mtls_enabled?: boolean
}
export async function searchAgentsLocal(q: string): Promise<FoundAgent[]> {
  const r = await apiClient.get('/admin/agents', { params: { search: q, limit: 10 } })
  return (r.data?.agents ?? []) as FoundAgent[]
}
export async function searchAgentsRemote(key: string, token: string, q: string): Promise<FoundAgent[]> {
  const d = await peerGet<any>(key, 'admin/agents', token, { search: q, limit: 10 })
  return (d?.agents ?? []) as FoundAgent[]
}

// ── Coordinated suspend / reinstate (Phase-6 enforcement; Model A local, B remote) ─
export async function suspendAgentLocal(did: string, reason: string) {
  return (await apiClient.post('/admin/agents/bulk/suspend', { agent_dids: [did], reason })).data
}
export async function reinstateAgentLocal(did: string, reason: string) {
  return (await apiClient.post('/admin/agents/bulk/reinstate', { agent_dids: [did], reason })).data
}
export async function suspendAgentRemote(key: string, token: string, did: string, reason: string) {
  return peerPost(key, 'admin/agents/bulk/suspend', token, { agent_dids: [did], reason })
}
export async function reinstateAgentRemote(key: string, token: string, did: string, reason: string) {
  return peerPost(key, 'admin/agents/bulk/reinstate', token, { agent_dids: [did], reason })
}

// ── Supply invariant (P10 — Δ per frame via the registry's ES proxy slots) ───
export interface SupplyFrameAudit { delta: number | null; status: string; total_issued?: number; total_circulating?: number }
/** GET /admin/simulation/supply-audit — NOTE: the "A" key is the EVENT_STORE_URL
 *  slot (= the LOCAL frame's ES on every registry); B/C come from their own env
 *  slots. The caller must remap accordingly (see GalacticCommand.tickerSupply). */
export async function supplyAuditFrames(): Promise<Record<string, SupplyFrameAudit>> {
  return (await apiClient.get('/admin/simulation/supply-audit')).data
}

// ── Mint (P8 — LOCAL mainframe only; registry mint-proxy emits TokensIssued) ─
/** Mint new tokens via the local registry's mint proxy (mainframe-gated server-side;
 *  the only authorized create-from-void path — Δ-safe by construction). */
export async function mintTokens(p: { target_agent_did: string; amount: string; reason?: string }) {
  const r = await apiClient.post(
    '/teg/treasury/mint',
    { target_agent_did: p.target_agent_did, amount: p.amount, reason: p.reason || 'gcc_mint' },
    { headers: { 'Idempotency-Key': idem() } },
  )
  return r.data
}

// ── Cloud-op lifecycle (Model A — mainframe runs these against its op stacks) ─
export interface CloudOperatorRow { id: number | string; operator_name?: string; name?: string; status?: string; [k: string]: any }
export async function listCloudOperators(): Promise<CloudOperatorRow[]> {
  const r = await apiClient.get('/admin/cloud-operators')
  const d = r.data
  return Array.isArray(d) ? d : (d?.operators ?? d?.items ?? d?.applications ?? [])
}
export async function opRestart(applicationId: number | string, service?: string) {
  const r = await apiClient.post(`/admin/cloud-operators/${applicationId}/restart-service`, service ? { service } : {})
  return r.data
}
export async function opProvision(applicationId: number | string) {
  const r = await apiClient.post(`/admin/cloud-operators/${applicationId}/provision`, {})
  return r.data
}
export async function opTeardown(applicationId: number | string) {
  const r = await apiClient.post(`/admin/cloud-operators/${applicationId}/teardown`, {})
  return r.data
}

// ── Op self-restart (P11 — Model B: the op restarts ITSELF via its own license) ─
/** Restart a cloud-op's stack from ANY cockpit: relayed to the op's
 *  /operator-portal/self-restart with the op's own admin token; the op proxies
 *  to its parent mainframe carrying its FEDERATION_LICENSE_KEY. */
export async function opSelfRestartRemote(key: string, token: string, service?: string) {
  return peerPost(key, 'operator-portal/self-restart', token, service ? { service } : {})
}

// ── Canary fleet (Model A — local master dispatches federation-wide) ─────────
export async function canaryFleetStatus() { return (await apiClient.get('/admin/canary/fleet/status')).data }
export async function canaryFleetPause() { return (await apiClient.post('/admin/canary/fleet/pause', {})).data }
export async function canaryFleetResume() { return (await apiClient.post('/admin/canary/fleet/resume', {})).data }

// ── Federation / fabric (Model A) ────────────────────────────────────────────
export async function federationSyncTrigger() { return (await apiClient.post('/federation/sync/trigger', {})).data }

export interface IronhandTarget { did: string; name: string; registry: string; trust_domain?: string; currency?: string; mtls?: boolean }
export async function ironhandTargets(includeAll = false): Promise<IronhandTarget[]> {
  const r = await apiClient.get('/admin/ironhand/targets', { params: includeAll ? { include_all: true } : {} })
  const d = r.data
  return Array.isArray(d) ? d : (d?.targets ?? [])
}
/** Fire a real low-value IRONHAND probe at an agent (source's home fires if remote). */
export async function ironhandProbe(p: { target_did: string; source_did?: string; amount?: string }) {
  const r = await apiClient.post('/admin/ironhand/probe', p)
  return r.data
}

// ── Action log model (shared with the view + ActionLog component) ────────────
export interface ActionLogEntry {
  id: string
  ts: number
  target: string
  action: string
  status: 'ok' | 'err' | 'pending'
  detail?: string
  payload?: any
}

// ── GC2 (2026-06-12): cockpit awareness additions ────────────────────────────

/** GC2-1: atomic tri-frame supply Δ via the server-side auditor proxy
 *  (the auditor serves no CORS headers; the registry proxies it same-origin).
 *  data keys: frame-a / frame-b / frame-c (+ sbx-* — ignore those). */
export interface AuditorFrame { delta: number | null; status: string; frame?: string; timestamp?: string }
export async function auditorLatest(): Promise<{ ok: boolean; data: Record<string, AuditorFrame> | null }> {
  const r = await apiClient.get('/admin/command/auditor-latest')
  return { ok: !!r.data?.ok, data: r.data?.data ?? null }
}

/** GC2-2: the single Hetzner box's vitals (the box IS the fleet). Defensive
 *  mapping — the endpoint's exact shape may grow; absent fields stay null. */
export interface HostVitals { cpuPct: number | null; memPct: number | null; diskPct: number | null; memUsedGb?: number | null; memTotalGb?: number | null }
export async function systemVitals(): Promise<HostVitals | null> {
  try {
    const d = (await apiClient.get('/admin/system-resources')).data || {}
    const pct = (v: any) => (typeof v === 'number' && isFinite(v) ? v : null)
    const disk = d.disk || d.disk_usage || {}
    return {
      cpuPct: pct(d.cpu?.percent),
      memPct: pct(d.memory?.percent),
      diskPct: pct(disk.percent),
      memUsedGb: pct(d.memory?.used_gb),
      memTotalGb: pct(d.memory?.total_gb),
    }
  } catch { return null }
}

/** GC2-3: ZKP attestation stats — local direct, remote via the full-passthrough
 *  peer relay (same trust path as the P7 intel tiles). null = endpoint absent
 *  on the target (older image) or relay refused — render an honest dash. */
export interface AttestationStats { total: number; verified: number; active: number; expiring_24h?: number; circuits_available?: number }
export async function attestationStatsLocal(): Promise<AttestationStats | null> {
  try { return ((await apiClient.get('/admin/attestations/analytics')).data?.stats ?? null) as AttestationStats | null } catch { return null }
}
export async function attestationStatsRemote(key: string, token: string): Promise<AttestationStats | null> {
  try { return (((await peerGet<any>(key, 'admin/attestations/analytics', token)) as any)?.stats ?? null) as AttestationStats | null } catch { return null }
}

// ── Balance Reconcile (2026-06-18 — multi-op ES↔TEG drift) ───────────────────
// An agent holds REAL custody across MULTIPLE op TEGs of a frame (sim multi-op
// funding / AGORA passport); ES materialized_balances is the AGGREGATE. So the
// truth = Σ token_balance across all family op TEGs vs the ES liquid. These call
// the registry passthroughs (balance_reconcile.py); the panel fans out per frame.
export interface TegBalanceRow { agent_id: string; token_balance: string; locked_balance: string }
export interface TegBalances { count: number; balances: TegBalanceRow[] }
export interface EsBalanceRow { agent_did: string; liquid_balance: string; staked_balance: string }
export interface EsBalances { count: number; agents: EsBalanceRow[] }

/** THIS registry's local TEG bulk balances (one reconciler leg). */
export async function balanceReconcileLocal(): Promise<TegBalances> {
  return (await apiClient.get('/admin/balance-reconcile/local')).data as TegBalances
}
/** A family op's local TEG balances, relayed with the op's admin token. */
export async function balanceReconcileLocalRemote(key: string, token: string): Promise<TegBalances> {
  return peerGet<TegBalances>(key, 'admin/balance-reconcile/local', token)
}
/** THIS frame's ES materialized_balances aggregate (the local frame ES). */
export async function balanceReconcileEsBalances(): Promise<EsBalances> {
  return (await apiClient.get('/admin/balance-reconcile/es-balances')).data as EsBalances
}
/** A remote family registry's ES aggregate (= parent-frame ES), relayed with its token. */
export async function balanceReconcileEsBalancesRemote(key: string, token: string): Promise<EsBalances> {
  return peerGet<EsBalances>(key, 'admin/balance-reconcile/es-balances', token)
}
