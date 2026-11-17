// V0666 the Flare view reworked (order gwo_558042610799088faf1a5e4c): who wears what, as one pure model the view and its tests share.
// The developer and each agent are BEARERS. A bought ring or corner is worn by the one agent that bears the slot (and by the developer's own avatar); an earned ring
// or badge is ONE copy, worn by one bearer at a time, the developer or one agent (the registry moves it); a title is the developer's. The registry decides, this
// only reads what it says: every field here comes from the flare status and the agents list the page already holds.
import { BADGE_KEYS, RING_KEYS } from '@/services/contributorTrack'

export const ME = 'me'
export const MAX_BEARERS = 200

export interface DeveloperFlare {
  name: string
  flare_encirclement_variant?: string | null
  flare_corner_variant?: string | null
  selected_corner_flare?: string | null
  selected_encirclement_flare?: string | null
  title?: string | null
}
export interface AgentFlareRow {
  did: string
  name?: string
  bears_corner_flare?: boolean
  bears_encirclement_flare?: boolean
  flare_encirclement_variant?: string | null
  flare_corner_variant?: string | null
}
export interface Bearer { key: string; kind: 'developer' | 'agent'; did: string | null; name: string }
export interface WornItem { key: string; source: 'earned' | 'bought' }
export interface Worn { ring: WornItem | null; badge: WornItem | null; title: string | null }

const isRing = (v: unknown): v is string => typeof v === 'string' && RING_KEYS.includes(v)
const isBadge = (v: unknown): v is string => typeof v === 'string' && BADGE_KEYS.includes(v)

/** An agent with no name is shown by the tail of its did, never blank. */
export function agentName(a: AgentFlareRow): string {
  const n = (a.name || '').trim()
  return n || `…${String(a.did).slice(-8)}`
}

export function wornBy(b: Bearer, dev: DeveloperFlare, agents: AgentFlareRow[]): Worn {
  if (b.kind === 'developer') {
    return {
      ring: isRing(dev.flare_encirclement_variant) ? { key: dev.flare_encirclement_variant, source: 'earned' } : dev.selected_encirclement_flare ? { key: dev.selected_encirclement_flare, source: 'bought' } : null,
      badge: isBadge(dev.flare_corner_variant) ? { key: dev.flare_corner_variant, source: 'earned' } : dev.selected_corner_flare ? { key: dev.selected_corner_flare, source: 'bought' } : null,
      title: dev.title || null,
    }
  }
  const a = agents.find((x) => x.did === b.did)
  if (!a) return { ring: null, badge: null, title: null }
  return {
    ring: a.bears_encirclement_flare && dev.selected_encirclement_flare ? { key: dev.selected_encirclement_flare, source: 'bought' } : isRing(a.flare_encirclement_variant) ? { key: a.flare_encirclement_variant, source: 'earned' } : null,
    badge: a.bears_corner_flare && dev.selected_corner_flare ? { key: dev.selected_corner_flare, source: 'bought' } : isBadge(a.flare_corner_variant) ? { key: a.flare_corner_variant, source: 'earned' } : null,
    title: null,                                                              // a title says what the person did: it stays the developer's
  }
}
export const wornCount = (w: Worn): number => (w.ring ? 1 : 0) + (w.badge ? 1 : 0) + (w.title ? 1 : 0)

/** The developer first, then the agents that wear something, then the rest by name; at most MAX_BEARERS agents. */
export function bearersOf(dev: DeveloperFlare, agents: AgentFlareRow[]): Bearer[] {
  const me: Bearer = { key: ME, kind: 'developer', did: null, name: dev.name }
  const rows = agents.map((a) => ({ b: { key: a.did, kind: 'agent', did: a.did, name: agentName(a) } as Bearer, n: wornCount(wornBy({ key: a.did, kind: 'agent', did: a.did, name: '' }, dev, agents)) }))
  rows.sort((x, y) => (y.n > 0 ? 1 : 0) - (x.n > 0 ? 1 : 0) || x.b.name.localeCompare(y.b.name, undefined, { sensitivity: 'base' }))
  return [me, ...rows.slice(0, MAX_BEARERS).map((r) => r.b)]
}

/** A search by name or did; the developer stays in every answer. */
export function filterBearers(list: Bearer[], q: string): Bearer[] {
  const needle = q.trim().toLowerCase()
  if (!needle) return list
  return list.filter((b) => b.kind === 'developer' || b.name.toLowerCase().includes(needle) || (b.did || '').toLowerCase().includes(needle))
}

/** The one bearer that wears an earned copy (ME or an agent's did), or null when it is free. */
export function holderOfEarned(kind: 'encirclement' | 'corner', key: string, dev: DeveloperFlare, agents: AgentFlareRow[]): string | null {
  const devKey = kind === 'encirclement' ? dev.flare_encirclement_variant : dev.flare_corner_variant
  if (devKey === key) return ME
  const hit = agents.find((a) => (kind === 'encirclement' ? a.flare_encirclement_variant : a.flare_corner_variant) === key)
  return hit ? hit.did : null
}
