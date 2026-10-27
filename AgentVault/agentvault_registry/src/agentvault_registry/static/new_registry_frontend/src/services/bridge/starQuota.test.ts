import { describe, it, expect } from 'vitest'
import { allocateStars, groupByRegistry, representedRegistries, LOCAL_KEY } from './starQuota'
import type { StarCandidate } from './starQuota'

const rows = (spec: Record<string, number>) => {
  const out: { did: string; registryUrl?: string | null }[] = []
  for (const [host, n] of Object.entries(spec))
    for (let i = 0; i < n; i++)
      out.push({ did: `${host}-${i}`, registryUrl: host === 'local' ? null : `https://${host}/` })
  return out
}

describe('star quota', () => {
  it('groups by registry host, local for a missing address', () => {
    const g = groupByRegistry(rows({ local: 2, 'a.io': 3 }))
    expect(g.get(LOCAL_KEY)!.length).toBe(2)
    expect(g.get('a.io')!.length).toBe(3)
  })

  it('THE BUG: a plain slice keeps only the first registries', () => {
    const r = rows({ 'a.io': 300, 'b.io': 40, 'c.io': 40 })
    const naive = r.slice(0, 240).map(x => x.did)
    expect(representedRegistries(r, naive)).toBe(1)          // what he saw
    const fair = allocateStars(r, 240)
    expect(representedRegistries(r, fair)).toBe(3)           // what he asked for
  })

  it('every registry gets at least the floor when budget allows', () => {
    const r = rows({ 'a.io': 500, 'b.io': 9, 'c.io': 9, 'd.io': 9 })
    const picked = new Set(allocateStars(r, 240, 8))
    for (const h of ['b.io', 'c.io', 'd.io'])
      expect([...picked].filter(d => d.startsWith(h)).length).toBeGreaterThanOrEqual(8)
  })

  it('never exceeds the cap', () => {
    expect(allocateStars(rows({ 'a.io': 50, 'b.io': 50, 'c.io': 50 }), 20).length).toBe(20)
  })

  it('shrinks the floor rather than starving late registries', () => {
    // 30 registries, cap 60 -> floor collapses to 2, everyone still represented
    const spec: Record<string, number> = {}
    for (let i = 0; i < 30; i++) spec[`r${i}.io`] = 10
    const r = rows(spec)
    const picked = allocateStars(r, 60, 8)
    expect(picked.length).toBe(60)
    expect(representedRegistries(r, picked)).toBe(30)
  })

  it('does not invent stars when there are fewer agents than cap', () => {
    const r = rows({ 'a.io': 3, 'b.io': 2 })
    expect(allocateStars(r, 240).sort()).toEqual(r.map(x => x.did).sort())
  })

  it('handles a single registry, empties and junk without throwing', () => {
    expect(allocateStars([], 10)).toEqual([])
    expect(allocateStars(rows({ 'a.io': 5 }), 3).length).toBe(3)
    expect(allocateStars([{ did: '', registryUrl: 'nonsense' } as any], 5)).toEqual([])
    expect(allocateStars([{ did: 'x', registryUrl: 'not a url' }], 5)).toEqual(['x'])
  })
})

/*
 * §OWNEDHOMES — the second half of the same bug.
 *
 * §STARQUOTA fixed the slice. It did NOT fix attribution: the candidates were
 * built from the local stores, so an agent owned on op-berlin (known only as a
 * bare DID from the developer fan-out) had no `registryUrl` at all and was
 * filed under LOCAL. The quota then dutifully spread a set that claimed to be
 * one registry. Measured on frame-c 2026-08-21: 4,440 owned DIDs, every single
 * one of the 1,689 the map could see carried trust_domain frame-c — zero
 * foreign. So `home` is what the caller actually knows, and it wins.
 */
describe('starQuota — explicit home', () => {
  it('buckets by home when there is no registryUrl', () => {
    const rows: StarCandidate[] = [
      { did: 'a1', home: '__local__' }, { did: 'a2', home: '__local__' },
      { did: 'b1', home: 'op-berlin' }, { did: 'b2', home: 'op-berlin' },
      { did: 'c1', home: 'op-doha' },
    ]
    const g = groupByRegistry(rows)
    expect([...g.keys()].sort()).toEqual(['__local__', 'op-berlin', 'op-doha'])
    expect(g.get('op-berlin')).toEqual(['b1', 'b2'])
  })

  it('THE BUG: bare foreign DIDs all collapse into local without home', () => {
    const bare: StarCandidate[] = [
      { did: 'l1' }, { did: 'b1' }, { did: 'b2' }, { did: 'd1' },
    ]
    expect(groupByRegistry(bare).size).toBe(1)          // what he saw
    const homed: StarCandidate[] = [
      { did: 'l1', home: '__local__' },
      { did: 'b1', home: 'op-berlin' }, { did: 'b2', home: 'op-berlin' },
      { did: 'd1', home: 'op-doha' },
    ]
    expect(groupByRegistry(homed).size).toBe(3)         // what he asked for
  })

  it('home beats registryUrl, so one registry is never two buckets', () => {
    // A credentialed agent carries the URL; the same registry from the fan-out
    // carries the key. Bucketing on both namespaces at once would hand that
    // registry a double share and two different homes on the stage.
    const g = groupByRegistry([
      { did: 'x', registryUrl: 'https://op-berlin.op.theprotocol.cloud', home: 'op-berlin' },
      { did: 'y', home: 'op-berlin' },
    ])
    expect(g.size).toBe(1)
    expect(g.get('op-berlin')).toEqual(['x', 'y'])
  })

  it('a DID mentioned twice takes one slot, in its first home', () => {
    const g = groupByRegistry([
      { did: 'dup', home: 'op-berlin' },
      { did: 'dup', home: '__local__' },
      { did: 'other', home: '__local__' },
    ])
    expect(g.get('op-berlin')).toEqual(['dup'])
    expect(g.get('__local__')).toEqual(['other'])
  })

  it('every signed-in registry gets stars at fleet scale', () => {
    // 16 registries, one of them enormous — the real shape on his account.
    const rows: StarCandidate[] = []
    for (let i = 0; i < 4440; i++) rows.push({ did: `local-${i}`, home: '__local__' })
    const ops = ['berlin', 'doha', 'london', 'paris', 'riyadh', 'abudhabi', 'telaviv',
      'washington', 'newyork', 'chicago', 'houston', 'losangeles', 'qatest16', 'A', 'B']
    for (const op of ops) for (let i = 0; i < 130; i++) rows.push({ did: `${op}-${i}`, home: op })
    const chosen = allocateStars(rows, 240)
    expect(chosen.length).toBe(240)
    expect(representedRegistries(rows, chosen)).toBe(16)
    // and no registry is starved to a token single star
    const g = groupByRegistry(rows.filter(r => new Set(chosen).has(r.did)))
    for (const [, dids] of g) expect(dids.length).toBeGreaterThanOrEqual(8)
  })
})

/*
 * PROPORTION, not levelling. Measured on his account: 4,448 agents on frame-c
 * and ~130 on each of 15 other registries. A round-robin remainder gave every
 * registry 15 stars, so a fleet that is 76% local drew as 6% local — visible
 * everywhere and wrong about itself. Floors are a floor; the big one stays big.
 */
describe('starQuota — the remainder follows population', () => {
  const fleet = (): StarCandidate[] => {
    const rows: StarCandidate[] = []
    for (let i = 0; i < 4448; i++) rows.push({ did: `local-${i}`, home: 'frame-c' })
    for (const op of ['berlin', 'doha', 'london', 'paris', 'riyadh', 'abudhabi', 'telaviv',
      'washington', 'newyork', 'chicago', 'houston', 'losangeles', 'A', 'B', 'qatest16'])
      for (let i = 0; i < 130; i++) rows.push({ did: `${op}-${i}`, home: op })
    return rows
  }

  it('the local fleet is the largest share, by a lot', () => {
    const rows = fleet()
    const chosen = new Set(allocateStars(rows, 240))
    const g = groupByRegistry(rows.filter(r => chosen.has(r.did)))
    const local = (g.get('frame-c') || []).length
    const anOp = (g.get('berlin') || []).length
    expect(local).toBeGreaterThan(60)          // round-robin would give it 15
    expect(local).toBeGreaterThan(anOp * 4)
  })

  it('and every registry still clears its floor', () => {
    const rows = fleet()
    const chosen = new Set(allocateStars(rows, 240))
    const g = groupByRegistry(rows.filter(r => chosen.has(r.did)))
    expect(g.size).toBe(16)
    for (const [, d] of g) expect(d.length).toBeGreaterThanOrEqual(8)
  })

  it('spends the whole budget, never more', () => {
    for (const cap of [16, 100, 240, 1000]) {
      const chosen = allocateStars(fleet(), cap)
      expect(chosen.length).toBe(Math.min(cap, 4448 + 15 * 130))
      expect(new Set(chosen).size).toBe(chosen.length)
    }
  })

  it('a registry smaller than its floor is not over-allocated', () => {
    const rows: StarCandidate[] = [
      ...Array.from({ length: 500 }, (_, i) => ({ did: `b-${i}`, home: 'big' })),
      { did: 't1', home: 'tiny' }, { did: 't2', home: 'tiny' },
    ]
    const chosen = allocateStars(rows, 50)
    const g = groupByRegistry(rows.filter(r => new Set(chosen).has(r.did)))
    expect((g.get('tiny') || []).length).toBe(2)
    expect((g.get('big') || []).length).toBe(48)
  })
})
