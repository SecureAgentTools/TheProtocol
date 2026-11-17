// V0663 (his suggestion 3): the bell groups the account's feed by kind (the notification catalog's category), marks a kind
// read, and mutes a kind. Pure rules, no network, no DOM.
//
// What muting is: a kind of this DEVICE's bell is folded into one quiet line ("12 muted") and its entries are not listed.
// It changes nothing the server sends (push, mail and the in-app feed follow Settings > Notifications), and nothing vanishes
// unseen: the quiet line counts what it holds and one press shows it again. Two things can never be muted: the Mentions
// group (it is not part of the feed; the bell draws it apart) and the kinds in NEVER_MUTED (sign-in and security notices).
import type { FeedItem } from '@/stores/notifications'

export const MUTED_KEY = 'bell.mutedKinds'
export const NEVER_MUTED: readonly string[] = ['security']

const LABELS: Record<string, string> = {
  chat: 'Chat', marketplace: 'Marketplace', ops: 'Operations', security: 'Security', agents: 'Agents', contracts: 'Contracts',
  money: 'Money', governance: 'Governance', organizations: 'Organizations', broadcast: 'Announcements', legal: 'Legal',
}

export function kindOf(e: Pick<FeedItem, 'category' | 'type_key'>): string {
  const c = String(e?.category || '').trim().toLowerCase()
  if (c) return c
  const t = String(e?.type_key || '')
  return t.includes('.') ? t.split('.')[0] : (t || 'other')
}

export function kindLabel(kind: string): string {
  return LABELS[kind] || (kind ? kind.charAt(0).toUpperCase() + kind.slice(1) : 'Other')
}

export function canMute(kind: string): boolean {
  return !NEVER_MUTED.includes(kind)
}

export interface BellGroup { kind: string; label: string; entries: FeedItem[]; canMute: boolean }
export interface QuietKind { kind: string; label: string; count: number }
export interface Grouped { groups: BellGroup[]; quiet: { count: number; kinds: QuietKind[] } }

function stamp(e: FeedItem): number {
  const t = e.created_at ? Date.parse(e.created_at) : NaN
  return Number.isFinite(t) ? t : 0
}

/** The unread feed, one group per kind (the kind with the newest entry first, each group newest first). A muted kind that can
 *  be muted leaves the groups and is counted in `quiet`; a kind that cannot be muted stays whatever the set says. */
export function groupFeed(feed: FeedItem[], muted: ReadonlySet<string>): Grouped {
  const byKind = new Map<string, FeedItem[]>()
  for (const e of feed || []) {
    if (!e || e.read) continue
    const k = kindOf(e)
    byKind.set(k, [...(byKind.get(k) || []), e])
  }
  const groups: BellGroup[] = []
  const quietKinds: QuietKind[] = []
  for (const [kind, entries] of byKind) {
    const sorted = [...entries].sort((a, b) => stamp(b) - stamp(a) || b.id - a.id)
    if (muted.has(kind) && canMute(kind)) quietKinds.push({ kind, label: kindLabel(kind), count: sorted.length })
    else groups.push({ kind, label: kindLabel(kind), entries: sorted, canMute: canMute(kind) })
  }
  groups.sort((a, b) => stamp(b.entries[0]) - stamp(a.entries[0]) || a.kind.localeCompare(b.kind))
  quietKinds.sort((a, b) => b.count - a.count || a.kind.localeCompare(b.kind))
  return { groups, quiet: { count: quietKinds.reduce((s, q) => s + q.count, 0), kinds: quietKinds } }
}

/** "12 muted" */
export function quietLine(count: number): string { return `${count} muted` }

/** The muted kinds read back from storage: only strings that name a kind that can be muted, never a throw. */
export function parseMuted(raw: string | null | undefined): Set<string> {
  if (!raw) return new Set()
  try {
    const v = JSON.parse(raw)
    if (!Array.isArray(v)) return new Set()
    return new Set(v.filter((k) => typeof k === 'string' && k.length > 0 && k.length <= 40 && canMute(k)))
  } catch { return new Set() }
}

export function toggleMuted(muted: ReadonlySet<string>, kind: string, on: boolean): Set<string> {
  const next = new Set(muted)
  if (on && canMute(kind)) next.add(kind)
  else next.delete(kind)
  return next
}

export function loadMuted(storage: Pick<Storage, 'getItem'> | undefined = typeof localStorage !== 'undefined' ? localStorage : undefined): Set<string> {
  try { return parseMuted(storage?.getItem(MUTED_KEY)) } catch { return new Set() }
}

export function saveMuted(muted: ReadonlySet<string>, storage: Pick<Storage, 'setItem'> | undefined = typeof localStorage !== 'undefined' ? localStorage : undefined): void {
  try { storage?.setItem(MUTED_KEY, JSON.stringify([...muted].sort())) } catch { /* a full or blocked store keeps the choice for this session only */ }
}
