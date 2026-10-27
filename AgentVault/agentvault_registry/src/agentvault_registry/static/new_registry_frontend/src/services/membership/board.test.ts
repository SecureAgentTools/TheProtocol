import { describe, it, expect } from 'vitest'
import { commonsView, membershipView, normaliseBoard, sortBoard, type BoardRegistry } from './board'

/**
 * §MEMBERSHIP phase C (2026-10-02) — the registry board says what the Directory observed and no more: a registry not
 * checked yet is never 0 members, one whose first read failed shows no invented figure, one whose later read failed
 * keeps its last good figures marked as such, and nothing is ranked on a number the board does not have.
 */
const M = (over: Record<string, unknown> = {}) => ({ state: 'ok', mode: 'member', members: 3, joined30d: 2, left30d: 1,
  presenceMode: 'conditional', minBondAgeDays: 0, tenureFullDays: 365, asOf: null, readAt: 1700000000, checkedAt: 1700000000, error: null, ...over })
const reg = (name: string, membership: any = null, commons: any = null): BoardRegistry => ({ name, tier: 'frame', location: null,
  currency: 'SBXA', publicUrl: null, verified: true, reachable: true, membership, commons })

describe('what the board can say about members', () => {
  it('ok: the count, the flow and its net', () => {
    expect(membershipView(M())).toMatchObject({ kind: 'ok', members: 3, joined: 2, left: 1, net: 1, mode: 'member' })
  })
  it('not checked yet is never zero, and not published is its own answer', () => {
    expect(membershipView(null)).toEqual({ kind: 'unchecked' })
    expect(membershipView(M({ state: 'absent', members: null }))).toEqual({ kind: 'absent' })
  })
  it('a failed read keeps the last good figures as stale; a registry never read has none to show', () => {
    expect(membershipView(M({ state: 'unreadable', error: 'timeout' }))).toMatchObject({ kind: 'stale', members: 3, error: 'timeout' })
    expect(membershipView(M({ state: 'unreadable', members: null, joined30d: null, left30d: null, readAt: null, error: 'refused' })))
      .toEqual({ kind: 'failed', error: 'refused', checkedAt: 1700000000 })
  })
})

describe('what the board can say about a commons', () => {
  const S = (id: number, status: string) => ({ id, title: `S${id}`, status, budget: '10', paidTotal: '0', submissions: 1, ballots: 1,
    opensAt: null, endsAt: null, closedAt: null, paidAt: null, cancelledAt: null })
  const C = (over: Record<string, unknown> = {}) => ({ state: 'ok', currency: 'SBXA', seasons: [], cancelledRecent: null, readAt: 1, checkedAt: 1, error: null, ...over })
  it('leads with the open season, else the one waiting for payment, else the newest', () => {
    expect(commonsView(C({ seasons: [S(3, 'paid'), S(4, 'open'), S(2, 'closed')] }))).toMatchObject({ kind: 'season', season: { id: 4 } })
    expect(commonsView(C({ seasons: [S(3, 'paid'), S(2, 'closed')] }))).toMatchObject({ kind: 'season', season: { id: 2 } })
    expect(commonsView(C({ seasons: [S(3, 'paid'), S(5, 'cancelled')] }))).toMatchObject({ kind: 'season', season: { id: 5 } })
  })
  it('switched off, absent, not checked, no season yet, and a first read that failed are all different answers', () => {
    expect(commonsView(C({ state: 'switched_off' }))).toEqual({ kind: 'off' })
    expect(commonsView(C({ state: 'absent' }))).toEqual({ kind: 'absent' })
    expect(commonsView(null)).toEqual({ kind: 'unchecked' })
    expect(commonsView(C())).toEqual({ kind: 'none', stale: false, readAt: 1, cancelled: 0 })
    expect(commonsView(C({ state: 'unreadable', readAt: null, error: 'gateway 403' }))).toEqual({ kind: 'failed', error: 'gateway 403', checkedAt: 1 })
  })

  it('counts the cancelled seasons the index left out, beside the season shown or beside "no season"', () => {
    expect(commonsView(C({ seasons: [S(4, 'open')], cancelledRecent: 2 }))).toMatchObject({ kind: 'season', cancelled: 2 })
    expect(commonsView(C({ seasons: [], cancelledRecent: 5 }))).toMatchObject({ kind: 'none', cancelled: 5 })
  })

  it('control: an index that does not count them reads as none cancelled, never as a guess', () => {
    expect(commonsView(C({ seasons: [], cancelledRecent: null }))).toMatchObject({ kind: 'none', cancelled: 0 })
  })
})

describe('the board\'s order', () => {
  const rows = [
    reg('zeta', M({ members: 9, joined30d: 0, left30d: 4 })),
    reg('alpha', M({ members: 2, joined30d: 5, left30d: 0 })),
    reg('mid', M({ state: 'unreadable', members: 50 })),
    reg('never', null),
    reg('quiet', M({ state: 'absent', members: null })),
  ]
  it('by members: figures first (highest first), then stale, then not published, then not checked', () => {
    expect(sortBoard(rows, 'members').map((r) => r.name)).toEqual(['zeta', 'alpha', 'mid', 'quiet', 'never'])
  })
  it('by 30-day net flow, and by name', () => {
    expect(sortBoard(rows, 'flow').map((r) => r.name).slice(0, 2)).toEqual(['alpha', 'zeta'])
    expect(sortBoard(rows, 'name').map((r) => r.name)).toEqual(['alpha', 'mid', 'never', 'quiet', 'zeta'])
  })
})

describe('a Directory answer', () => {
  it('becomes complete rows; a row without a name is dropped; null blocks stay null', () => {
    const out = normaliseBoard([{ name: 'sbx-alpha', tier: 'frame', membership: { state: 'ok', members: 2 },
      commons: { state: 'ok', seasons: [{ id: '3', title: 'A' }] } }, { tier: 'frame' }, { name: 'op', membership: null }])
    expect(out).toHaveLength(2)
    expect(out[0].membership).toMatchObject({ state: 'ok', members: 2, joined30d: null })
    expect(out[0].commons?.seasons[0]).toMatchObject({ id: 3, title: 'A', submissions: null })
    expect(out[1].membership).toBeNull()
    expect(out[1].commons).toBeNull()
  })

  it('keeps how many recent seasons were cancelled, and null where the index does not read it (board1)', () => {
    const [a, b] = normaliseBoard([{ name: 'a', commons: { state: 'ok', seasons: [], cancelledRecent: 3 } },
      { name: 'b', commons: { state: 'ok', seasons: [] } }])
    expect(a.commons?.cancelledRecent).toBe(3)
    expect(b.commons?.cancelledRecent).toBeNull()
  })
})

