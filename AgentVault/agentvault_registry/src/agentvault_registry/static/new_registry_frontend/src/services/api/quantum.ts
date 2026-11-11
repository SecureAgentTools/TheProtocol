/**
 * V0660 (e): the console's one read of an agent's quantum workload extension, GET /api/v1/quantum/agents/{did}
 * (V0660 (a), routers/quantum_agent_cards.py). The route answers only where the frame serves the extension
 * (QUANTUM_WORKLOADS_MODE shadow or on); callers ask it only then (composables/useQuantumWorkloads.ts).
 *
 * One promise per DID for the page's life: a discovery grid, the agent page and a chat thread that show the same agent
 * cost one request. A 404 is an answer (the card carries no extension, or there is no card); a failed read is not, and
 * is dropped from the cache so the next mount reads again.
 */

export interface QuantumRead {
  agent_did: string
  name?: string | null
  is_local?: boolean
  origin?: string | null
  version?: string | null
  params: Record<string, any> | null
  check?: { valid?: boolean; problems?: string[]; mode?: string } | null
  index?: Record<string, any> | null
  freshness?: {
    read_at?: string
    backends?: Array<{ id?: string; age_seconds?: Record<string, number | null>; oldest_age_seconds?: number | null }>
  } | null
}

export type QuantumReadState =
  | { state: 'ok'; read: QuantumRead }
  | { state: 'none' }
  | { state: 'failed' }

const cache = new Map<string, Promise<QuantumReadState>>()

export function readQuantumAgent(did: string): Promise<QuantumReadState> {
  const key = (did || '').trim()
  if (!key.startsWith('did:')) return Promise.resolve({ state: 'none' })
  const hit = cache.get(key)
  if (hit) return hit
  const p: Promise<QuantumReadState> = Promise.resolve()
    .then(() => fetch(`${window.location.origin}/api/v1/quantum/agents/${encodeURIComponent(key)}`,
      { headers: { Accept: 'application/json' } }))
    .then(async (r): Promise<QuantumReadState> => {
      if (r.status === 404) return { state: 'none' }
      if (!r.ok) throw new Error(`quantum read answered ${r.status}`)
      const d = await r.json()
      if (!d || typeof d !== 'object' || !d.params || typeof d.params !== 'object') return { state: 'none' }
      return { state: 'ok', read: d as QuantumRead }
    })
    .catch((): QuantumReadState => {
      cache.delete(key)
      return { state: 'failed' }
    })
  cache.set(key, p)
  return p
}

/** Tests only. */
export function _resetQuantumReads(): void { cache.clear() }
