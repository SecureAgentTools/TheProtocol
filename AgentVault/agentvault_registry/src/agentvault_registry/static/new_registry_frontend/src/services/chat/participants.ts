/**
 * §OURSTATE-1 — the per-principal identity resolver (session-cached).
 *
 * THE COMMANDER'S MANDATE (2026-08-24, binding): wherever OurState shows a
 * name it shows the WHOLE identity — avatar + flare encirclement + earned-mark
 * collar — at pixel-parity with Pocket Discover / My Agents. The only way that
 * parity survives is by construction: this module fetches the by-did profile
 * (which the backend returns with the flare fields HOISTED into the exact
 * UserLike shape `UserAvatar` consumes, bearer-truth computed server-side for
 * local agents) and hands it onward VERBATIM. It never re-derives the slot
 * cascade and never reads a flattened `it.flare` — both §POCKETDISC scars.
 *
 * Humans: the developer flare endpoint is PUBLIC (`/fiat/flare/developer/{id}`,
 * verified at build time), so humans get the same flare treatment in CORE via
 * the tier-default cascade (their selected_* variants are not public; the
 * two-mode rule in UserAvatar handles the absent fields honestly). Humans
 * carry no collar — an earned mark is agent work history.
 *
 * Discipline: resolve-what-you-see (§BRIDGE R13) — one small public call per
 * principal actually rendered, cached for the session; errors resolve to a
 * plain named identity, NEVER cached as poison (a transient 502 must not
 * strip someone's flare for the whole session).
 */
import { compactFromSummary, type TrackRecordCompact } from '@/services/api/trackRecord'
import { classifyIdentity, didOrNull } from '@/services/bridge/identity'

export interface ParticipantIdentity {
  key: string
  ptype: 'developer' | 'agent'
  name: string
  avatarUrl: string | null
  /** VERBATIM hoisted UserLike for UserAvatar — or null (plain initials). */
  user: Record<string, any> | null
  trackRecord: TrackRecordCompact | null
  resolved: boolean
}

const cache = new Map<string, ParticipantIdentity>()
const inflight = new Map<string, Promise<ParticipantIdentity>>()

export function principalKey(ptype: 'developer' | 'agent', id: string | number): string {
  return ptype === 'developer' ? `dev:${id}` : `agt:${String(id).toLowerCase()}`
}

function fallbackIdentity(key: string, ptype: 'developer' | 'agent', name: string): ParticipantIdentity {
  return { key, ptype, name, avatarUrl: null, user: null, trackRecord: null, resolved: false }
}

async function resolveAgent(did: string, fallbackName: string): Promise<ParticipantIdentity> {
  const key = principalKey('agent', did)
  // §TRUSTCHAIN P4.6 — ONE classifier decides what may reach /agents/by-did (§BRIDGE R9). A
  // developer wallet DID, a system account or a bare UUID is a party, not an agent: resolved
  // to its label without a request that can only 404.
  const ident = classifyIdentity(did)
  if (!didOrNull(did)) {
    return fallbackIdentity(key, 'agent', fallbackName || ident.label || did)
  }
  let profile: any = null
  let track: TrackRecordCompact | null = null
  try {
    const r = await fetch(`/api/v1/agents/by-did/${encodeURIComponent(did)}`)
    if (r.ok) profile = await r.json()
  } catch { /* fall through */ }
  // §ONBOARDQOL P6 (2026-09-02) — a federated MIRROR has no track record HERE: the
  // rail answers 404 for every mirror, and a first-time user's thread with a mirrored
  // agent logged one failed request per participant (D21). Locality is the profile's
  // own word (`is_federated`, the §BUYSERVICE rule), never "did the fetch fail".
  if (profile && profile.is_federated !== true) {
    try {
      const r = await fetch(`/api/v1/agents/${encodeURIComponent(did)}/track-record`)
      if (r.ok) track = compactFromSummary(await r.json())
    } catch { /* fall through */ }
  }
  if (!profile) return fallbackIdentity(key, 'agent', fallbackName || did)
  return {
    key, ptype: 'agent',
    name: profile.name || fallbackName || did,
    avatarUrl: profile.card_data?.iconUrl || profile.icon_url || null,
    user: profile,               // hoisted UserLike — verbatim, never re-mapped
    trackRecord: track,
    resolved: true,
  }
}

async function resolveDeveloper(devId: string | number, fallbackName: string): Promise<ParticipantIdentity> {
  const key = principalKey('developer', devId)
  let flare: any = null
  try {
    const r = await fetch(`/api/v1/fiat/flare/developer/${encodeURIComponent(String(devId))}`)
    if (r.ok) flare = await r.json()
  } catch { /* fall through */ }
  if (!flare || !flare.flare_tier) {
    return { ...fallbackIdentity(key, 'developer', fallbackName || `dev ${devId}`), resolved: true }
  }
  // §OURSTATE-6 (his call): the SELECTED slots are public now, so a human
  // wears in chat exactly what they equipped — the whole point of buying a
  // cosmetic is that other people see it. Before this, only `flare_tier` was
  // forwarded, so an agent rendered its encirclement and overlay while its
  // OWNER, with the same choices, rendered a plain tier ring.
  //
  // ⚠ Handed to UserAvatar VERBATIM: the sovereign-always-wins cascade lives
  // there (§pass39b), and re-deriving it here is the §POCKETDISC scar.
  return {
    key, ptype: 'developer',
    name: fallbackName || flare.display_name || `dev ${devId}`,
    avatarUrl: flare.logo_url || null,
    user: {
      flare_tier: flare.flare_tier,
      flare_granted_at: flare.flare_granted_at ?? null,
      flare_display_name: flare.display_name ?? null,
      flare_tagline: flare.tagline ?? null,
      flare_accent_color: flare.accent_color ?? null,
      selected_encirclement_flare: flare.selected_encirclement_flare ?? null,
      flare_encirclement_variant: flare.flare_encirclement_variant ?? null,
      flare_encirclement_overlay: flare.flare_encirclement_overlay ?? null,
      selected_corner_flare: flare.selected_corner_flare ?? null,
      flare_corner_variant: flare.flare_corner_variant ?? null,
    },
    trackRecord: null,           // earned marks are agent work history
    resolved: true,
  }
}

/** Resolve (cached). `fallbackName` comes from the conversation row so a slow
 *  or failed resolve still shows the right NAME immediately. */
export function resolveIdentity(ptype: 'developer' | 'agent', id: string | number,
                                fallbackName = ''): Promise<ParticipantIdentity> {
  const key = principalKey(ptype, id)
  const hit = cache.get(key)
  if (hit && hit.resolved) return Promise.resolve(hit)
  const running = inflight.get(key)
  if (running) return running
  const p = (ptype === 'agent' ? resolveAgent(String(id), fallbackName)
                               : resolveDeveloper(id, fallbackName))
    .then(idn => {
      // Only a RESOLVED identity is cached — a transient failure must not
      // strip someone's flare for the whole session.
      if (idn.resolved) cache.set(key, idn)
      inflight.delete(key)
      return idn
    })
    .catch(() => {
      inflight.delete(key)
      return fallbackIdentity(key, ptype, fallbackName || String(id))
    })
  inflight.set(key, p)
  return p
}

/** Synchronous cache read for templates that render before resolution lands. */
export function peekIdentity(ptype: 'developer' | 'agent', id: string | number): ParticipantIdentity | null {
  return cache.get(principalKey(ptype, id)) || null
}
