/**
 * V0655 (ay) (order gwo_57362aa3484807226198b8de): what the ring around a member's logo in a room's side panel says, which
 * picture it may draw, and how a mention names the member. One place for the side panel and its tests.
 *
 * The ring has four states: off (nothing in this room wakes it, whatever its line says), live (a status line that has
 * not lapsed), on call (no live line, and it wakes only when named) and quiet (no live line, or a lapsed one). A line
 * lapses at its expires_at even between two reads of the presence (the panel reads it every two minutes).
 */

export type Ring = 'off' | 'live' | 'on-call' | 'quiet'

export interface RingMember {
  status?: { text?: string | null; expires_at?: string | null } | null
}

export function liveLine(a: RingMember, now: number = Date.now()): boolean {
  const s = a?.status
  if (!s || !String(s.text || '').trim()) return false
  const until = Date.parse(String(s.expires_at || ''))
  return Number.isNaN(until) || until > now
}

/** wakeMode: the member's mode in this room ('listen', 'on-call', 'off'), or '' for an agent outside the room */
export function ringOf(a: RingMember, wakeMode: string, now: number = Date.now()): Ring {
  if (wakeMode === 'off') return 'off'
  if (liveLine(a, now)) return 'live'
  return wakeMode === 'on-call' ? 'on-call' : 'quiet'
}

/** A picture the panel may draw: an https address, a path on this host, or an inline raster or SVG image; anything
 *  else draws the initial */
export function safeIcon(url: unknown): string | null {
  const u = typeof url === 'string' ? url.trim() : ''
  if (!u || u.length > 2048) return null
  if (/^https:\/\/[^\s/]/i.test(u)) return u
  if (u.startsWith('/') && !u.startsWith('//')) return u
  if (/^data:image\/(png|jpeg|gif|webp|svg\+xml)[;,]/i.test(u)) return u
  return null
}

/** What a mention of the member writes after "@": its card name where no other member of the list carries the same
 *  name (the server resolves a card name only where it is unique), its DID otherwise (the DID always resolves) */
export function mentionLabel(a: { did: string; name?: string | null }, all: Array<{ did: string; name?: string | null }>): string {
  const name = String(a.name || '').trim()
  if (!name) return a.did
  const same = all.filter((o) => String(o.name || '').trim().toLowerCase() === name.toLowerCase())
  return same.length > 1 ? a.did : name
}
