/**
 * services/api/forge.ts — GÖDEL FORGE public reads.
 *
 *   GET /api/v1/forge/status               — arena flags + counts ({enabled: false} when the arena is dark)
 *   GET /api/v1/forge/lineages/{orgId}     — the Evolution Tree (roster ∪ spawn ∪ forks ∪ scores)
 *
 * enabled: false (a 403 from registries before V0556) means FORGE_ENABLED is off on this registry: the
 * view renders a calm "arena dark here" state rather than an error.
 */
import axios from 'axios'

const http = axios.create({ baseURL: '/api/v1' })

export interface ForgeStatus {
  enabled: boolean
  flags: {
    evals_agent_trigger: boolean
    royalty: boolean
    verifier_quorum_m: number
    royalty_default_bps: number
    royalty_max_bps: number
    royalty_max_depth: number
  }
  counts: { lineage_bundles?: number; verifiers?: number; code_patch_results?: number }
  lineages?: { org_id: string; name?: string; bundles?: number }[]
}

export interface ForgeNode {
  type: 'agent' | 'bundle'
  did?: string
  id?: string
  name: string
  reputation?: number
  eval_score?: number | null
  royalty_bps?: number
  kin?: boolean   // spawn-kinship ghost node (not an org member)
}

export interface ForgeEdge { kind: 'spawn' | 'fork'; from: string; to: string }

export interface ForgeLineage {
  org_id: string
  nodes: ForgeNode[]
  edges: ForgeEdge[]
  agent_count: number
  bundle_count: number
}

export async function getForgeStatus(): Promise<ForgeStatus | null> {
  try {
    const r = await http.get('/forge/status')
    const d = r.data as ForgeStatus | undefined
    return d && d.enabled !== false ? d : null // enabled: false = arena dark on this registry
  } catch (e: any) {
    // a refusal is the registry's answer: a 403 = arena dark on a registry before V0556, a 404 = no forge route at all.
    // §FESUITE (V0575): no answer, or a server error, is not "the arena is dark": it reaches the caller as a failure
    const st = e?.response?.status
    if (st === 403 || st === 404) return null
    throw e
  }
}

export async function getLineage(orgId: string): Promise<ForgeLineage | null> {
  try {
    const r = await http.get(`/forge/lineages/${encodeURIComponent(orgId)}`)
    return r.data as ForgeLineage
  } catch {
    return null
  }
}
