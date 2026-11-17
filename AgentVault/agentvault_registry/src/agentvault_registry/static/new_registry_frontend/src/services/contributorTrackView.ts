/**
 * V0665 (order gwo_5e0701efdef9d3989491bc37): the contributor track as the Track tab draws it. Pure: the registry's track read in, the view's groups out.
 *
 * The main row is the pass like a battle pass (forty tiers) (a tier can carry two items: tier 10 holds a badge and a ring); the titles come next, side quests off the main
 * row, and the items still waiting for a condition last ("comes later", with the registry's reason). A new unlock is what is unlocked and not yet seen on this device.
 */
import type { TrackItem, TrackKind } from '@/services/api/contributorTrack'

export interface Tier { tier: number; items: TrackItem[]; done: boolean; partial: boolean }
export interface Groups { tiers: Tier[]; titles: TrackItem[]; side: TrackItem[]; later: TrackItem[] }

/** The track's groups: the tiers of the pass, the design's titles, the side quests, and the art's other rings and badges (waiting for a condition). */
export function groups(items: TrackItem[]): Groups {
  const tiers: Tier[] = []
  const last = items.reduce((m, i) => (i.tier != null && i.tier > m ? i.tier : m), 0)      // the pass has as many tiers as its items name (43 today)
  for (let n = 1; n <= last; n++) {
    const its = items.filter((i) => i.tier === n)
    if (!its.length) continue
    const un = its.filter((i) => i.unlocked).length
    tiers.push({ tier: n, items: its, done: un === its.length, partial: un > 0 && un < its.length })
  }
  const rest = items.filter((i) => i.tier == null)
  const side = rest.filter((i) => i.side)
  const titles = rest.filter((i) => i.kind === 'title' && !i.side)
  const later = rest.filter((i) => i.kind !== 'title' && !i.side)
  return { tiers, titles, side, later }
}

export const keyOf = (i: { kind: TrackKind; key: string }) => `${i.kind}:${i.key}`

/** The first tier of the pass that is not done: where "jump to my next tier" goes. Null when every tier is done (or there are none). */
export function nextOpenTier(tiers: Tier[]): number | null {
  return tiers.find((t) => !t.done)?.tier ?? null
}

/** What this device has not been told about yet: unlocked items whose key is not in `seen`. */
export function newUnlocks(items: TrackItem[], seen: ReadonlySet<string>): TrackItem[] {
  return items.filter((i) => i.unlocked && !seen.has(keyOf(i)))
}

export function unlockedCount(items: TrackItem[]): { done: number; total: number } {
  const open = items.filter((i) => !i.later)
  return { done: open.filter((i) => i.unlocked).length, total: open.length }
}

/** Percent for a progress bar (0 to 100); an item with no signal has none. */
export function percent(i: TrackItem): number {
  if (i.unlocked) return 100
  const p = i.progress
  if (!p || !p.of) return 0
  return Math.max(0, Math.min(100, Math.round((p.n / p.of) * 100)))
}

/** Which of the art's components draws an item. */
export function drawn(kind: TrackKind): 'ring' | 'badge' | 'title' {
  return kind === 'encirclement' ? 'ring' : kind === 'corner' ? 'badge' : 'title'
}

/** The i18n section holding an item's name: rings, badges, titles. */
export function section(kind: TrackKind): 'rings' | 'badges' | 'titles' {
  return kind === 'encirclement' ? 'rings' : kind === 'corner' ? 'badges' : 'titles'
}

/**
 * The celebration reads the track ONCE per page load for each signed-in developer: the flag lives in memory, not in session storage (a browser-storage key
 * is a line of the cookie policy, and this is not worth one: a reload reads again, once).
 */
let checkedFor: string | null = null
export function markChecked(devId: number | string | null | undefined): boolean {
  const k = String(devId ?? '')
  if (checkedFor === k) return false
  checkedFor = k
  return true
}
export function resetChecked(): void { checkedFor = null }

export const SEEN_KEY = (devId: number | string | null | undefined) => `ct_seen_${devId ?? 'anon'}`
export function readSeen(storage: Pick<Storage, 'getItem'>, devId: number | string | null | undefined): Set<string> {
  try {
    const raw = storage.getItem(SEEN_KEY(devId))
    const arr = raw ? JSON.parse(raw) : []
    return new Set(Array.isArray(arr) ? arr.filter((x) => typeof x === 'string') : [])
  } catch { return new Set() }
}
export function writeSeen(storage: Pick<Storage, 'setItem'>, devId: number | string | null | undefined, seen: Iterable<string>): void {
  try { storage.setItem(SEEN_KEY(devId), JSON.stringify([...seen])) } catch { /* private mode: the celebration may show again, nothing worse */ }
}

/**
 * The NEXT title to unlock (V0665, his feedback on the Track tab, room seq 4404): of the titles not yet unlocked and not waiting for a signal, the one closest to unlocking
 * (n of m), a tie to the one that comes first in the track. Only a title with progress can be ranked: a visitor's read has none, so it names no next title.
 */
export function nextTitle(items: TrackItem[]): TrackItem | null {
  let best: TrackItem | null = null
  let bestPct = -1
  for (const i of items) {
    if (i.kind !== 'title' || i.unlocked || i.later || !i.progress) continue
    const p = percent(i)
    if (p > bestPct) { best = i; bestPct = p }
  }
  return best
}

/**
 * The NEXT item of the pass track (his feedback on the preview, room seq 4568: "show the pass track first item too"): the first item of the ten tiers not yet unlocked, tier by
 * tier and in the track's order inside a tier. Like the next title it needs progress to be told apart: a visitor's read has none, so it names none.
 */
export function nextTrackItem(items: TrackItem[]): TrackItem | null {
  for (const tier of groups(items).tiers) {
    const hit = tier.items.find((i) => !i.unlocked && !i.later && !!i.progress)
    if (hit) return hit
  }
  return null
}

/** Is this item drawn as an outline only? Everything not yet unlocked is, except the ones shown in full: the next title and the next item of the pass track. */
export function isBlacked(i: TrackItem, ...shown: Array<TrackItem | null>): boolean {
  return !i.unlocked && !shown.some((s) => !!s && keyOf(i) === keyOf(s))
}

/** The title a person wears: the one they chose, else the COMMANDER title for the commander flare tier (a rule of the code: nothing is stored, so taking a title off returns to it). */
export function wornTitleOf(chosen: string | null | undefined, flareTier: string | null | undefined): string {
  return (chosen ? String(chosen) : '') || (flareTier === 'commander' ? 'commander' : '')
}

/** The Eye Sees All is drawn with the almond-eye mark at the plate's left: option B, his pick (room seq 4158). */
export const titleVariant = (key: string): 'a' | 'b' => (key === 'the-eye-sees-all' ? 'b' : 'a')
