/**
 * §OURSTATE-1 — `/audit` (alias `/whois`): the on-demand background check
 * (strategy §4c). ONE brain, two consumers: the Requests lane renders the same
 * card for a pending stranger that `/audit` summons in any thread.
 *
 * The clamps, enforced by construction here:
 *   - PUBLIC data only, over EXISTING endpoints (by-did profile + public
 *     track record). An /audit that shows more than the public web would is a
 *     data leak wearing a feature.
 *   - LOCAL-ONLY: composing this card posts nothing, stores nothing, notifies
 *     nobody — it is a read, so law 2 never even engages. There is no network
 *     WRITE in this module and the battery asserts the wire stays quiet.
 *   - ABSENCE IS HONEST: 99.8% of agents have no public history (§DISCREFINE
 *     base rate). "No public history" is a statement, never an insinuation —
 *     the pure `trustLines` encodes that wording decision so a renderer
 *     cannot re-editorialize it.
 */
import { compactFromSummary, earnedMarks, type TrackRecordCompact } from '@/services/api/trackRecord'
import { didOrNull } from '@/services/bridge/identity'

export interface TrustCardData {
  did: string
  name: string
  status: string | null
  homeRegistry: string | null      // origin registry name; null = this registry
  reputation: number | null        // 0..1 as stored; renderer formats
  reputationKnown: boolean
  flareTier: string | null
  track: TrackRecordCompact | null
  /** The raw by-did profile — handed to UserAvatar VERBATIM (the hoisted
   *  UserLike shape; never re-derive the cascade — §POCKETDISC scar). */
  profile: Record<string, any> | null
}

export type TrustLine =
  | { kind: 'jobs'; jobs: number; crossRegistry: number }
  | { kind: 'stars'; stars: number; fiveStar: number }
  | { kind: 'disputes'; open: number; total: number; lost: number }
  | { kind: 'tier'; tier: string }
  | { kind: 'reputation'; score: number }
  | { kind: 'no-history' }

/** Pure: which lines the card shows, in order — including the honest empty. */
export function trustLines(d: Pick<TrustCardData, 'track' | 'reputation' | 'reputationKnown'>): TrustLine[] {
  const out: TrustLine[] = []
  const tr = d.track
  if (tr && tr.jobs > 0) {
    out.push({ kind: 'jobs', jobs: tr.jobs, crossRegistry: tr.cross_registry || 0 })
    if (tr.stars != null) out.push({ kind: 'stars', stars: tr.stars, fiveStar: tr.five_star || 0 })
    const marks = earnedMarks(tr)
    if (marks.tier) out.push({ kind: 'tier', tier: marks.tier })
  }
  if (tr && tr.disputes > 0) {
    out.push({ kind: 'disputes', open: tr.open_disputes || 0, total: tr.disputes, lost: tr.lost_disputes || 0 })
  }
  if (d.reputationKnown && d.reputation != null) {
    out.push({ kind: 'reputation', score: d.reputation })
  }
  if (!tr || tr.jobs === 0) {
    // The base-rate honest line — most agents have none, and that is a fact
    // about the network's age, not a warning about this agent.
    out.push({ kind: 'no-history' })
  }
  return out
}

/** Compose the card from PUBLIC reads. Both fetches are GETs against public
 *  endpoints; a failed leg renders as absence, never as an error card. */
export async function fetchTrustCard(did: string): Promise<TrustCardData> {
  const enc = encodeURIComponent(did)
  let profile: any = null
  let track: TrackRecordCompact | null = null
  // §TRUSTCHAIN P4.6 — a developer wallet / system account / UUID is not an agent; the card
  // renders as absence without a by-did request that can only 404 (§BRIDGE R9's classifier).
  const askable = !!didOrNull(did)
  try {
    if (!askable) throw new Error('not an agent DID')
    const r = await fetch(`/api/v1/agents/by-did/${enc}`)
    if (r.ok) profile = await r.json()
  } catch { /* absence */ }
  // §ONBOARDQOL P6 (2026-09-02) — a mirror's record lives on its HOME registry; asking
  // here is a guaranteed 404 (D21). Skipped on the profile's own `is_federated`, so the
  // card renders "no history here" honestly instead of logging a failed request.
  if (profile && profile.is_federated !== true) {
    try {
      const r = await fetch(`/api/v1/agents/${enc}/track-record`)
      if (r.ok) track = compactFromSummary(await r.json())
    } catch { /* absence */ }
  }
  return {
    did,
    name: profile?.name || did,
    status: profile?.status ?? null,
    homeRegistry: profile?.origin_registry_name ?? null,
    reputation: profile?.reputation_score ?? null,
    reputationKnown: profile?.reputation_score !== null && profile?.reputation_score !== undefined,
    flareTier: profile?.flare_tier ?? null,
    track,
    profile,
  }
}
