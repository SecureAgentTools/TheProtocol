import { appLocale } from '@/services/appLocale'
/**
 * §LITEBRIDGE — the board that replaces the stage.
 *
 * The stage encodes three things SPATIALLY: which registries exist, which of
 * them your agents live on, and where traffic is moving. All three are facts,
 * and none of them actually needs a GPU — the 3D view is the beautiful way to
 * read them, not the only one.
 *
 * So the board states them. And where the stage is deliberately BOUNDED — it
 * draws at most 240 stars out of a fleet of thousands, because geometry is not
 * free — the board is EXACT. That is not a consolation prize: on a fleet of
 * 5,884 agents the board is the more accurate of the two, and it says so.
 *
 * Pure, so the numbers can be tested rather than eyeballed on a canvas that
 * cannot be asserted about.
 */

export interface BoardIndex {
  /** registry key -> events seen this session that touched YOUR agents there. */
  total: Map<string, number>
  /** registry key -> last time we saw one, ms epoch. */
  lastAt: Map<string, number>
  /** When this index started watching. A session has no past; say so. */
  since: number
}

export interface BoardRegistry {
  key: string
  name: string
  frame?: string | null
  currency?: string | null
  local?: boolean
  /** null = we never asked. Absence of an answer is not a "down". */
  reachable?: boolean | null
}

export interface BoardRow extends BoardRegistry {
  /** Agents you own there. EXACT — not the drawn sample. */
  mine: number
  /** Events this session touching your agents there. */
  seen: number
  /** ms since the last one, or null if never. */
  quietMs: number | null
  live: boolean
}

export const LIVE_WINDOW_MS = 60_000

export function createBoardIndex(now = Date.now()): BoardIndex {
  return { total: new Map(), lastAt: new Map(), since: now }
}

/** One event touched these registries. Keys, not DIDs — the caller owns the map. */
export function noteBoardActivity(ix: BoardIndex, keys: Iterable<string>, now = Date.now()): void {
  const seen = new Set<string>()
  for (const raw of keys) {
    const k = raw && String(raw)
    if (!k || seen.has(k)) continue      // one event counts once per registry
    seen.add(k)
    ix.total.set(k, (ix.total.get(k) || 0) + 1)
    ix.lastAt.set(k, now)
  }
}

/**
 * Merge what exists, what you own, and what has moved — into one ordered list.
 *
 * Order is deliberate: the registries you actually own agents on come first,
 * biggest first, then the rest alphabetically. A board sorted by raw event
 * count would reshuffle itself under the reader's eyes every few seconds.
 */
export function boardRows(
  registries: BoardRegistry[],
  mineByKey: Map<string, number> | Record<string, number>,
  ix: BoardIndex,
  now = Date.now(),
): BoardRow[] {
  const mine = mineByKey instanceof Map ? mineByKey : new Map(Object.entries(mineByKey || {}))
  const rows: BoardRow[] = registries.map(r => {
    const last = ix.lastAt.get(r.key) ?? null
    const quietMs = last === null ? null : Math.max(0, now - last)
    return {
      ...r,
      mine: Number(mine.get(r.key) || 0),
      seen: ix.total.get(r.key) || 0,
      quietMs,
      live: quietMs !== null && quietMs <= LIVE_WINDOW_MS,
    }
  })
  rows.sort((a, b) => {
    if (a.local !== b.local) return a.local ? -1 : 1
    if (b.mine !== a.mine) return b.mine - a.mine
    return String(a.name || a.key).localeCompare(String(b.name || b.key))
  })
  return rows
}

/**
 * The ACTIVE window, applied to the board.
 *
 * On the stage that control decides which STARS are drawn. With no stage it
 * would have been a dead control sitting next to a live one — so here it does
 * the same job one level up: which REGISTRIES are showing signs of life.
 *
 * Registries where you own agents are never hidden: "no traffic in the last
 * five minutes" is a fact about traffic, not about ownership, and dropping your
 * home registry off its own board because it was quiet would be the stage's
 * old sampling mistake in a new costume.
 */
export function filterByWindow(
  rows: BoardRow[], windowMs: number | null, keepKey?: string | null,
): BoardRow[] {
  if (!windowMs) return rows
  // `keepKey` is the FOCUSED registry. Hiding the row whose selection is
  // currently narrowing the fleet log and the ledger leaves the reader looking
  // at a filtered rail with the thing that filtered it nowhere on screen.
  return rows.filter(r => r.local || r.key === keepKey ||
    (r.quietMs !== null && r.quietMs <= windowMs))
}

/** What the board is allowed to claim about itself. */
export function boardSummary(rows: BoardRow[], now = Date.now(), since?: number, hiddenByWindow = 0): string {
  const withMine = rows.filter(r => r.mine > 0).length
  const agents = rows.reduce((n, r) => n + r.mine, 0)
  const watched = typeof since === 'number' ? Math.max(0, now - since) : 0
  const mins = Math.floor(watched / 60000)
  const watchNote = watched < 60000
    ? 'watching for under a minute'
    : `watching ${mins} minute${mins === 1 ? '' : 's'}`
  const hidden = hiddenByWindow > 0 ? ` · ${hiddenByWindow} quiet and hidden` : ''
  if (!rows.length) {
    return hiddenByWindow > 0
      ? `Nothing has moved in this window · ${hiddenByWindow} registries hidden`
      : 'No registries known yet.'
  }
  if (!agents) return `${rows.length} registries · you own no agents on any of them · ${watchNote}${hidden}`
  return `${agents.toLocaleString(appLocale())} agents across ${withMine} of ${rows.length} registries · exact, not sampled · ${watchNote}${hidden}`
}

/** Human "how long since", short enough for a table cell. */
export function quietLabel(quietMs: number | null): string {
  if (quietMs === null) return '—'
  if (quietMs < 2000) return 'now'
  if (quietMs < 60_000) return `${Math.floor(quietMs / 1000)}s`
  if (quietMs < 3_600_000) return `${Math.floor(quietMs / 60_000)}m`
  return `${Math.floor(quietMs / 3_600_000)}h`
}
