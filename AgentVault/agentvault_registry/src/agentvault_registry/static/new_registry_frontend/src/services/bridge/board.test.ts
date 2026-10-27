import { describe, it, expect } from 'vitest'
import {
  createBoardIndex, noteBoardActivity, boardRows, boardSummary, quietLabel, filterByWindow,
  LIVE_WINDOW_MS, type BoardRegistry,
} from './board'

const REGS: BoardRegistry[] = [
  { key: 'frame-c', name: 'Frame-C', frame: 'C', currency: 'BVT', local: true },
  { key: 'registry-a', name: 'Registry-A', frame: 'A', currency: 'AVT' },
  { key: 'op-berlin', name: 'op-berlin', frame: 'A', currency: 'AVT' },
  { key: 'op-doha', name: 'op-doha', frame: 'C', currency: 'BVT' },
]
const MINE = { 'frame-c': 4448, 'op-berlin': 131, 'op-doha': 114 }

describe('boardRows', () => {
  it('is EXACT — it reports the fleet, not the drawn sample', () => {
    const rows = boardRows(REGS, MINE, createBoardIndex(0), 0)
    expect(rows.find(r => r.key === 'frame-c')!.mine).toBe(4448)
    expect(rows.reduce((n, r) => n + r.mine, 0)).toBe(4448 + 131 + 114)
  })

  it('puts home first, then the registries you actually use', () => {
    const rows = boardRows(REGS, MINE, createBoardIndex(0), 0)
    expect(rows.map(r => r.key)).toEqual(['frame-c', 'op-berlin', 'op-doha', 'registry-a'])
  })

  it('does NOT reshuffle when traffic moves', () => {
    // A board sorted by event count rearranges itself under the reader's eyes.
    const ix = createBoardIndex(0)
    noteBoardActivity(ix, ['op-doha'], 1000)
    noteBoardActivity(ix, ['op-doha'], 1100)
    noteBoardActivity(ix, ['op-doha'], 1200)
    const rows = boardRows(REGS, MINE, ix, 2000)
    expect(rows.map(r => r.key)).toEqual(['frame-c', 'op-berlin', 'op-doha', 'registry-a'])
  })

  it('a registry you own nothing on is still listed', () => {
    const rows = boardRows(REGS, MINE, createBoardIndex(0), 0)
    const a = rows.find(r => r.key === 'registry-a')!
    expect(a).toBeDefined()
    expect(a.mine).toBe(0)
  })

  it('never seen is null, not zero — absence is not silence', () => {
    const rows = boardRows(REGS, MINE, createBoardIndex(0), 5000)
    expect(rows.every(r => r.quietMs === null)).toBe(true)
    expect(rows.every(r => r.live === false)).toBe(true)
  })

  it('live means seen inside the window, and stops being live after it', () => {
    const ix = createBoardIndex(0)
    noteBoardActivity(ix, ['op-berlin'], 1_000)
    expect(boardRows(REGS, MINE, ix, 1_000 + LIVE_WINDOW_MS).find(r => r.key === 'op-berlin')!.live).toBe(true)
    expect(boardRows(REGS, MINE, ix, 1_001 + LIVE_WINDOW_MS).find(r => r.key === 'op-berlin')!.live).toBe(false)
  })
})

describe('noteBoardActivity', () => {
  it('one event counts once per registry, however many parties it had', () => {
    const ix = createBoardIndex(0)
    noteBoardActivity(ix, ['op-berlin', 'op-berlin', 'op-berlin'], 10)
    expect(ix.total.get('op-berlin')).toBe(1)
  })
  it('an event spanning two registries counts on both', () => {
    const ix = createBoardIndex(0)
    noteBoardActivity(ix, ['op-berlin', 'frame-c'], 10)
    expect(ix.total.get('op-berlin')).toBe(1)
    expect(ix.total.get('frame-c')).toBe(1)
  })
  it('ignores empty keys instead of inventing a bucket', () => {
    const ix = createBoardIndex(0)
    noteBoardActivity(ix, ['', null as any, undefined as any], 10)
    expect(ix.total.size).toBe(0)
  })
})

describe('boardSummary — it says what it can and cannot know', () => {
  it('names the fleet and calls itself exact', () => {
    const rows = boardRows(REGS, MINE, createBoardIndex(0), 0)
    const s = boardSummary(rows, 60_000, 0)
    expect(s).toMatch(/4,693 agents/)
    expect(s).toMatch(/3 of 4 registries/)
    expect(s).toMatch(/exact, not sampled/)
  })
  it('states how long it has been watching, because a session has no past', () => {
    const rows = boardRows(REGS, MINE, createBoardIndex(0), 0)
    expect(boardSummary(rows, 30_000, 0)).toMatch(/under a minute/)
    expect(boardSummary(rows, 60_000, 0)).toMatch(/watching 1 minute/)
    expect(boardSummary(rows, 600_000, 0)).toMatch(/watching 10 minutes/)
  })
  it('an empty account gets the truth, not an encouraging zero', () => {
    const rows = boardRows(REGS, {}, createBoardIndex(0), 0)
    expect(boardSummary(rows, 0, 0)).toMatch(/you own no agents on any of them/)
    expect(boardSummary([], 0, 0)).toMatch(/No registries known yet/)
  })
})

describe('quietLabel', () => {
  it('reads as a person would say it', () => {
    expect(quietLabel(null)).toBe('—')
    expect(quietLabel(500)).toBe('now')
    expect(quietLabel(45_000)).toBe('45s')
    expect(quietLabel(120_000)).toBe('2m')
    expect(quietLabel(7_200_000)).toBe('2h')
  })
})

describe('filterByWindow — the ACTIVE control, one level up', () => {
  const ix = createBoardIndex(0)
  noteBoardActivity(ix, ['op-berlin'], 1000)
  const rows = boardRows(REGS, MINE, ix, 1000 + 30_000)

  it('keeps registries seen inside the window', () => {
    expect(filterByWindow(rows, 60_000).map(r => r.key)).toContain('op-berlin')
  })
  it('hides the quiet ones', () => {
    expect(filterByWindow(rows, 10_000).map(r => r.key)).not.toContain('op-berlin')
  })
  it('NEVER hides your home registry — quiet is a fact about traffic, not ownership', () => {
    expect(filterByWindow(rows, 1).map(r => r.key)).toContain('frame-c')
  })
  it('no window means no filtering', () => {
    expect(filterByWindow(rows, null).length).toBe(rows.length)
  })
  it('the summary says how many it is hiding', () => {
    expect(boardSummary(rows, 0, 0, 3)).toMatch(/3 quiet and hidden/)
    expect(boardSummary([], 0, 0, 9)).toMatch(/Nothing has moved in this window/)
  })
})

describe('filterByWindow — the focused row', () => {
  const ix = createBoardIndex(0)
  noteBoardActivity(ix, ['op-berlin'], 1000)
  const rows = boardRows(REGS, MINE, ix, 1000 + 600_000)   // berlin went quiet 10m ago

  it('keeps the FOCUSED registry visible even when it goes quiet', () => {
    // Its selection is what is narrowing the fleet log and the ledger; hiding it
    // leaves a filtered rail with the thing that filtered it nowhere on screen.
    expect(filterByWindow(rows, 60_000, 'op-berlin').map(r => r.key)).toContain('op-berlin')
    expect(filterByWindow(rows, 60_000, null).map(r => r.key)).not.toContain('op-berlin')
  })
  it('a focus on a registry that is already visible changes nothing', () => {
    expect(filterByWindow(rows, 60_000, 'frame-c').length).toBe(filterByWindow(rows, 60_000).length)
  })
})
