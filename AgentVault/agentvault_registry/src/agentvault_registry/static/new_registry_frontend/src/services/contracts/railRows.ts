/**
 * §TWOAGENT (V0442) — the Contracts page reads the contract RAIL, not only its couriers.
 *
 * On a frame where D8 retired the legacy contract surface (LEGACY_CONTRACTS_ENABLED=false: EU and ASIA), the page's grid
 * and tiles asked /api/v1/contracts/, got a 404 and said "No contracts match your filters", while the page showed only
 * the v2 contracts that were REPLICAS of another frame's. So a contract's client, at its own home, never saw it: the
 * Scrivener's contract offered on EU read as zero contracts on EU. These helpers split /contracts/v2/mine into what lives
 * here and what is a courier from elsewhere, and count the tiles from the rail when the legacy list is gone.
 */

export interface RailRow {
  id?: string
  cid?: string
  status?: string | null
  replica?: boolean
  client_did?: string | null
  provider_did?: string | null
  [k: string]: unknown
}

export interface RailSplit<T extends RailRow = RailRow> {
  home: T[]
  replicas: T[]
}

/** Home rows (the contract lives on this registry) and replicas (a signed courier of another frame's contract). */
export function splitRailRows<T extends RailRow>(items: unknown): RailSplit<T> {
  const out: RailSplit<T> = { home: [], replicas: [] }
  if (!Array.isArray(items)) return out
  for (const it of items as T[]) {
    if (!it || typeof it !== 'object') continue
    if (it.replica === true) out.replicas.push(it)
    else if (it.id || it.cid) out.home.push(it)
  }
  return out
}

export type RailTile = 'proposed' | 'accepted' | 'inReview' | 'completed'

/** Which of the page's four tiles a rail status belongs to. An offer is proposed; accepted work is accepted; a delivery
 *  made (in_progress) is awaiting review; completed is completed. Drafts, disputes, cancellations and expiries are not
 *  tiled, as the legacy tiles never counted their equivalents. */
export function railTileOf(status: string | null | undefined): RailTile | null {
  switch (String(status || '').toLowerCase()) {
    case 'offered': return 'proposed'
    case 'agreed': return 'accepted'
    case 'in_progress': return 'inReview'
    case 'completed': return 'completed'
    default: return null
  }
}

export function railTileCounts(items: unknown): Record<RailTile, number> {
  const counts: Record<RailTile, number> = { proposed: 0, accepted: 0, inReview: 0, completed: 0 }
  if (!Array.isArray(items)) return counts
  for (const it of items as RailRow[]) {
    const tile = railTileOf(it?.status)
    if (tile) counts[tile] += 1
  }
  return counts
}

/** The acting agent's side of a contract, or null when it is neither (or no agent is acting). */
export function railRole(c: RailRow | null | undefined, did: string | null | undefined): 'client' | 'provider' | null {
  if (!c || !did) return null
  const me = did.toLowerCase()
  if (String(c.client_did || '').toLowerCase() === me) return 'client'
  if (String(c.provider_did || '').toLowerCase() === me) return 'provider'
  return null
}

/** A legacy list request refused as a route that is not there (D8 retired it), as opposed to any other failure. */
export function isRetiredList(err: unknown): boolean {
  const e = err as { response?: { status?: number }; status?: number } | null
  return Boolean(e && (e.response?.status === 404 || e.status === 404))
}
