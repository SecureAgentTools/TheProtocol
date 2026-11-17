import { describe, it, expect } from 'vitest'
import { groups, keyOf, newUnlocks, unlockedCount, percent, drawn, section, readSeen, writeSeen, SEEN_KEY, nextTitle, nextTrackItem, isBlacked, wornTitleOf, nextOpenTier } from './contributorTrackView'
import type { TrackItem } from '@/services/api/contributorTrack'

const it_ = (o: Partial<TrackItem> & { kind: TrackItem['kind']; key: string }): TrackItem => ({ tier: null, side: false, condition: 'c', unlocked: false, progress: { n: 0, of: 1 }, later: null, ...o })

const ITEMS: TrackItem[] = [
  it_({ kind: 'corner', key: 'initiate', tier: 1, unlocked: true, progress: { n: 1, of: 1 } }),
  it_({ kind: 'encirclement', key: 'lantern', tier: 2, progress: { n: 0, of: 1 } }),
  it_({ kind: 'corner', key: 'crown-of-the-commons', tier: 10, unlocked: true }),
  it_({ kind: 'encirclement', key: 'supernova', tier: 10 }),
  it_({ kind: 'title', key: 'first-light', progress: { n: 3, of: 5 } }),
  it_({ kind: 'title', key: 'bug-slayer', later: 'nothing marks a change as the fix of a reported defect yet' }),
  it_({ kind: 'title', key: 'off-by-one', side: true }),
  it_({ kind: 'encirclement', key: 'ouroboros', later: 'its condition is not set yet' }),
]

describe('the pass beyond the ten tiers (the Commander\'s word on the preview, room seq 4592)', () => {
  const long = [
    it_({ kind: 'corner', key: 'a', tier: 1, unlocked: true }), it_({ kind: 'corner', key: 'b', tier: 2 }), it_({ kind: 'title', key: 'c', tier: 11 }),
    it_({ kind: 'encirclement', key: 'd', tier: 12, unlocked: true }), it_({ kind: 'title', key: 'e', tier: 43 }),
  ]
  it('groups every tier the pass has, in order, not only the first ten', () => {
    expect(groups(long).tiers.map((t) => t.tier)).toEqual([1, 2, 11, 12, 43])
  })
  it('names the first tier not done yet: where the jump control goes', () => {
    expect(nextOpenTier(groups(long).tiers)).toBe(2)
    expect(nextOpenTier(groups(long.map((i) => ({ ...i, unlocked: true }))).tiers)).toBeNull()
    expect(nextOpenTier([])).toBeNull()
  })
  it('a tier that holds two items is a pair, drawn side by side', () => {
    const two = [it_({ kind: 'corner', key: 'x', tier: 10 }), it_({ kind: 'encirclement', key: 'y', tier: 10 }), it_({ kind: 'title', key: 'z', tier: 11 })]
    expect(groups(two).tiers.map((t) => t.items.length)).toEqual([2, 1])
  })
})

describe('the track grouped for the page', () => {
  it('puts the ten tiers in order, a tier with two items done only when both are, partial when one is', () => {
    const g = groups(ITEMS)
    expect(g.tiers.map((t) => t.tier)).toEqual([1, 2, 10])
    expect(g.tiers[0].done).toBe(true)
    expect(g.tiers[1].done).toBe(false)
    expect(g.tiers[2]).toMatchObject({ done: false, partial: true })
  })
  it('keeps the design titles, the side quests and the art\'s waiting items apart', () => {
    const g = groups(ITEMS)
    expect(g.titles.map((i) => i.key)).toEqual(['first-light', 'bug-slayer'])
    expect(g.side.map((i) => i.key)).toEqual(['off-by-one'])
    expect(g.later.map((i) => i.key)).toEqual(['ouroboros'])
  })
  it('is empty for an empty track', () => {
    expect(groups([])).toEqual({ tiers: [], titles: [], side: [], later: [] })
  })
})

describe('progress and counts', () => {
  it('percent is the share done, 100 when unlocked, 0 with no progress and never out of range', () => {
    expect(percent(it_({ kind: 'title', key: 'a', progress: { n: 3, of: 5 } }))).toBe(60)
    expect(percent(it_({ kind: 'title', key: 'a', unlocked: true, progress: { n: 0, of: 5 } }))).toBe(100)
    expect(percent(it_({ kind: 'title', key: 'a', progress: { n: 9, of: 5 } }))).toBe(100)
    expect(percent(it_({ kind: 'title', key: 'a', progress: undefined }))).toBe(0)
    expect(percent(it_({ kind: 'title', key: 'a', progress: { n: 1, of: 0 } }))).toBe(0)
  })
  it('counts only what can be earned today: an item waiting for a condition is not in the total', () => {
    expect(unlockedCount(ITEMS)).toEqual({ done: 2, total: 6 })
  })
})

describe('what is new on this device', () => {
  it('is the unlocked items the device has not seen', () => {
    const fresh = newUnlocks(ITEMS, new Set(['corner:initiate']))
    expect(fresh.map(keyOf)).toEqual(['corner:crown-of-the-commons'])
    expect(newUnlocks(ITEMS, new Set())).toHaveLength(2)
  })
  it('reads and writes the seen set per developer, and survives a broken store', () => {
    const mem: Record<string, string> = {}
    const store = { getItem: (k: string) => mem[k] ?? null, setItem: (k: string, v: string) => { mem[k] = v } }
    writeSeen(store, 7, ['corner:initiate'])
    expect([...readSeen(store, 7)]).toEqual(['corner:initiate'])
    expect([...readSeen(store, 8)]).toEqual([])
    mem[SEEN_KEY(9)] = '{not json'
    expect([...readSeen(store, 9)]).toEqual([])
    expect(() => writeSeen({ setItem: () => { throw new Error('quota') } }, 1, ['x'])).not.toThrow()
  })
})

describe('naming', () => {
  it('maps the registry kinds to the art components and to the i18n sections', () => {
    expect(drawn('encirclement')).toBe('ring'); expect(drawn('corner')).toBe('badge'); expect(drawn('title')).toBe('title')
    expect(section('encirclement')).toBe('rings'); expect(section('corner')).toBe('badges'); expect(section('title')).toBe('titles')
  })
})

// V0665 (his feedback on the Track tab, room seq 4404, through session-lead seq 4405): what is not yet unlocked is blacked out, only the next title shows, the commander tier wears its title by default
describe('the next title and what is blacked out', () => {
  it('the next title is the locked title closest to unlocking, never one that waits for a condition, never an unlocked one', () => {
    expect(nextTitle(ITEMS)?.key).toBe('first-light')                                      // 3 of 5; bug-slayer waits for a signal; off-by-one is 0 of 1
    const more = ITEMS.map((i) => (i.key === 'off-by-one' ? { ...i, progress: { n: 4, of: 5 } } : i))
    expect(nextTitle(more)?.key).toBe('off-by-one')                                        // a side quest counts: it is a title too
    const done = ITEMS.map((i) => (i.key === 'first-light' ? { ...i, unlocked: true } : i))
    expect(nextTitle(done)?.key).toBe('off-by-one')
  })
  it('a tie goes to the title that comes first in the track', () => {
    const tie = [it_({ kind: 'title', key: 'a-first', progress: { n: 1, of: 2 } }), it_({ kind: 'title', key: 'b-second', progress: { n: 2, of: 4 } })]
    expect(nextTitle(tie)?.key).toBe('a-first')
  })
  it('no next title when none can unlock, or when there is no progress to rank (a visitor)', () => {
    expect(nextTitle([it_({ kind: 'title', key: 'x', later: 'waits' })])).toBeNull()
    expect(nextTitle([it_({ kind: 'title', key: 'x', progress: undefined as any, unlocked: undefined as any })])).toBeNull()
    expect(nextTitle([])).toBeNull()
  })
  it('the next item of the pass track is the first one not yet unlocked, tier by tier (his feedback, room seq 4568: the first of the pass track shows too)', () => {
    expect(nextTrackItem(ITEMS)?.key).toBe('lantern')                                       // tier 1 is unlocked, tier 2 is the first not
    const two = ITEMS.map((i) => (i.key === 'lantern' ? { ...i, unlocked: true } : i))
    expect(nextTrackItem(two)?.key).toBe('supernova')                                       // tier 10 holds two: the first not unlocked, in the track's order
    expect(nextTrackItem(ITEMS.map((i) => (i.tier != null ? { ...i, unlocked: true } : i)))).toBeNull()   // the whole pass unlocked
  })
  it('the next pass-track item needs progress to be ranked, as the next title does: a visitor has none', () => {
    expect(nextTrackItem(ITEMS.map((i) => ({ ...i, progress: undefined as any, unlocked: undefined as any })))).toBeNull()
    expect(nextTrackItem([])).toBeNull()
  })
  it('an item is blacked out unless it is unlocked, the next title or the next item of the pass track', () => {
    const t = nextTitle(ITEMS), p = nextTrackItem(ITEMS)
    expect(isBlacked(ITEMS.find((i) => i.key === 'initiate')!, t, p)).toBe(false)          // unlocked: shown as it is
    expect(isBlacked(ITEMS.find((i) => i.key === 'first-light')!, t, p)).toBe(false)       // the next title
    expect(isBlacked(ITEMS.find((i) => i.key === 'lantern')!, t, p)).toBe(false)           // the next item of the pass track
    for (const k of ['supernova', 'bug-slayer', 'off-by-one', 'ouroboros']) expect(isBlacked(ITEMS.find((i) => i.key === k)!, t, p)).toBe(true)
    expect(isBlacked(ITEMS.find((i) => i.key === 'lantern')!, null, null)).toBe(true)
  })
})

describe('the title a person wears', () => {
  it('is the one they chose, else the COMMANDER title for the commander flare tier (a rule of the code, nothing is stored)', () => {
    expect(wornTitleOf('first-light', null)).toBe('first-light')
    expect(wornTitleOf('first-light', 'commander')).toBe('first-light')                    // he can still pick another
    expect(wornTitleOf('', 'commander')).toBe('commander')
    expect(wornTitleOf(null, 'commander')).toBe('commander')
    expect(wornTitleOf(undefined, 'founder')).toBe('')
    expect(wornTitleOf(null, null)).toBe('')
  })
})
