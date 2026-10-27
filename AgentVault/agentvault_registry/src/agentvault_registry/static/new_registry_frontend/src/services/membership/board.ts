/**
 * services/membership/board.ts — §MEMBERSHIP phase C (2026-10-02): the registry board, as the console reads it.
 *
 * Design § 12 S5: registries compete for members the way cities compete for residents, with their rules, their record
 * and what their commons pays for; the board shows members and their 30-day flow where a market would show a price.
 * The figures come from the federated Directory (stack directory/board.py, agentvault2-33), which reads each
 * registry's public /membership/stats and /commons/seasons: counts only, never a member, a ballot or a DID.
 *
 * Every figure says what was observed and no more. A registry the Directory has not checked yet is NOT CHECKED,
 * never 0; one that does not publish the figure is ABSENT; one whose last read failed shows the last good figures with
 * the time they were read; one that answered "commons switched off" says so. There is no price here, no chart and no
 * buy button, by design.
 */

export interface BoardMembership {
  state: 'ok' | 'absent' | 'unreadable' | string
  mode: string | null
  members: number | null
  joined30d: number | null
  left30d: number | null
  presenceMode: string | null
  minBondAgeDays: number | null
  tenureFullDays: number | null
  asOf: string | null
  readAt: number | null
  checkedAt: number | null
  error: string | null
}

export interface BoardSeason {
  id: number
  title: string | null
  status: string | null
  budget: string | null
  paidTotal: string | null
  submissions: number | null
  ballots: number | null
  opensAt: string | null
  endsAt: string | null
  closedAt: string | null
  paidAt: string | null
  cancelledAt: string | null
}

export interface BoardCommons {
  state: 'ok' | 'switched_off' | 'absent' | 'unreadable' | string
  currency: string | null
  /** the newest three seasons that were NOT cancelled (board2 of the Directory; board1 read the newest three) */
  seasons: BoardSeason[]
  /** cancelled seasons among the registry's last twenty (a cancelled season paid nothing); null where not read */
  cancelledRecent: number | null
  readAt: number | null
  checkedAt: number | null
  error: string | null
}

export interface BoardRegistry {
  name: string
  tier: string | null
  location: string | null
  currency: string | null
  publicUrl: string | null
  verified: boolean
  reachable: boolean
  membership: BoardMembership | null
  commons: BoardCommons | null
}

/** What the board can say about a registry's members. */
export type MembershipView =
  | { kind: 'unchecked' }
  | { kind: 'absent' }
  /** every read so far failed: no figure exists to show, and none is invented */
  | { kind: 'failed'; error: string | null; checkedAt: number | null }
  | { kind: 'ok' | 'stale'; members: number; joined: number; left: number; net: number; mode: string | null;
      presenceMode: string | null; readAt: number | null; error: string | null }

export function membershipView(m: BoardMembership | null | undefined): MembershipView {
  if (!m) return { kind: 'unchecked' }
  if (m.state === 'absent') return { kind: 'absent' }
  // unreadable WITH an earlier good read keeps its figures, marked stale; unreadable with none has no figure at all
  const hasFigures = m.members !== null && m.members !== undefined
  if (m.state !== 'ok' && !hasFigures) return { kind: 'failed', error: m.error, checkedAt: m.checkedAt }
  const joined = Math.max(0, Number(m.joined30d) || 0)
  const left = Math.max(0, Number(m.left30d) || 0)
  return {
    kind: m.state === 'ok' ? 'ok' : 'stale',
    members: Math.max(0, Number(m.members) || 0), joined, left, net: joined - left,
    mode: m.mode, presenceMode: m.presenceMode, readAt: m.readAt, error: m.state === 'ok' ? null : m.error,
  }
}

/** What the board can say about a registry's commons: its newest season, or why there is none to show. */
export type CommonsView =
  | { kind: 'unchecked' }
  | { kind: 'absent' }
  | { kind: 'failed'; error: string | null; checkedAt: number | null }
  | { kind: 'off' }
  | { kind: 'none'; stale: boolean; readAt: number | null; cancelled: number }
  | { kind: 'season'; stale: boolean; readAt: number | null; currency: string | null; season: BoardSeason; cancelled: number }

export function commonsView(c: BoardCommons | null | undefined): CommonsView {
  if (!c) return { kind: 'unchecked' }
  if (c.state === 'absent') return { kind: 'absent' }
  if (c.state === 'switched_off') return { kind: 'off' }
  const stale = c.state !== 'ok'
  const seasons = [...(c.seasons || [])].sort((a, b) => b.id - a.id)
  if (stale && !seasons.length && c.readAt == null) return { kind: 'failed', error: c.error, checkedAt: c.checkedAt }
  // the cancelled seasons the index left out are counted, never silently gone: "no season" alone would hide them
  const cancelled = Math.max(0, Number(c.cancelledRecent) || 0)
  if (!seasons.length) return { kind: 'none', stale, readAt: c.readAt, cancelled }
  // the season the registry leads with: the open one, else the one waiting for payment, else the newest
  const lead = seasons.find((s) => s.status === 'open') || seasons.find((s) => s.status === 'closed') || seasons[0]
  return { kind: 'season', stale, readAt: c.readAt, currency: c.currency, season: lead, cancelled }
}

export type BoardSort = 'members' | 'flow' | 'name'

/**
 * The board's order. By members (or by 30-day net flow): registries with figures first, highest first; then those
 * whose figures are stale, then those not publishing or not checked, each group by name. A registry is never ranked
 * on a number the board does not have.
 */
export function sortBoard(rows: BoardRegistry[], by: BoardSort = 'members'): BoardRegistry[] {
  const rank = (r: BoardRegistry) => {
    const v = membershipView(r.membership)
    return ({ ok: 0, stale: 1, failed: 2, absent: 3, unchecked: 4 } as Record<string, number>)[v.kind] ?? 4
  }
  const value = (r: BoardRegistry) => {
    const v = membershipView(r.membership)
    if (v.kind !== 'ok' && v.kind !== 'stale') return 0
    return by === 'flow' ? v.net : v.members
  }
  return [...rows].sort((a, b) => {
    if (by !== 'name') {
      const g = rank(a) - rank(b)
      if (g) return g
      const d = value(b) - value(a)
      if (d) return d
    }
    return a.name.localeCompare(b.name)
  })
}

/** A Directory answer as the board reads it: every array an array, every count a number or null. */
export function normaliseBoard(raw: any): BoardRegistry[] {
  const list = Array.isArray(raw) ? raw : []
  const n = (x: unknown) => (typeof x === 'number' && Number.isFinite(x) ? x : null)
  return list.filter((r) => r && typeof r.name === 'string').map((r) => ({
    name: r.name,
    tier: r.tier ?? null,
    location: r.location ?? null,
    currency: r.currency ?? null,
    publicUrl: r.publicUrl ?? null,
    verified: !!r.verified,
    reachable: !!r.reachable,
    membership: r.membership && typeof r.membership === 'object' ? {
      state: String(r.membership.state || 'unreadable'), mode: r.membership.mode ?? null,
      members: n(r.membership.members), joined30d: n(r.membership.joined30d), left30d: n(r.membership.left30d),
      presenceMode: r.membership.presenceMode ?? null, minBondAgeDays: n(r.membership.minBondAgeDays),
      tenureFullDays: n(r.membership.tenureFullDays), asOf: r.membership.asOf ?? null,
      readAt: n(r.membership.readAt), checkedAt: n(r.membership.checkedAt), error: r.membership.error ?? null,
    } : null,
    commons: r.commons && typeof r.commons === 'object' ? {
      state: String(r.commons.state || 'unreadable'), currency: r.commons.currency ?? null,
      seasons: (Array.isArray(r.commons.seasons) ? r.commons.seasons : []).map((s: any) => ({
        id: Number(s?.id) || 0, title: s?.title ?? null, status: s?.status ?? null, budget: s?.budget ?? null,
        paidTotal: s?.paidTotal ?? null, submissions: n(s?.submissions), ballots: n(s?.ballots),
        opensAt: s?.opensAt ?? null, endsAt: s?.endsAt ?? null, closedAt: s?.closedAt ?? null,
        paidAt: s?.paidAt ?? null, cancelledAt: s?.cancelledAt ?? null,
      })),
      cancelledRecent: n(r.commons.cancelledRecent),
      readAt: n(r.commons.readAt), checkedAt: n(r.commons.checkedAt), error: r.commons.error ?? null,
    } : null,
  }))
}
