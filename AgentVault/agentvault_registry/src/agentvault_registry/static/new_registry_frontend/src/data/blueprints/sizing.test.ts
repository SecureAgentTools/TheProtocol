/**
 * V0660 (m): the sizing table's Containers column stays a count, not a sentence.
 *
 * WHY THIS GATE EXISTS, measured rather than recalled. The console proof of V0660 failed
 * axe `scrollable-region-focusable` (serious) on the five quantum chambers at 412 px, one node each, and
 * session-release found the cause (room seq 2820): `BlueprintDetailView`'s "What you actually run" table renders
 * `sizing[].containers` in `.bpd-mono`, which is `white-space: nowrap`, inside `.bpd-tablewrap`
 * (`overflow-x: auto`, no tabindex). The older chambers keep that cell to a few words — "0 of theirs",
 * "agents only", "one frame per plant", 11 to 19 characters — so their table fits a phone. The five new ones
 * carried 64 to 105 character sentences, so the wrap had to scroll, and a scroll container no keyboard can reach
 * is what axe refuses.
 *
 * The remedy session-lead chose (seq 2831) is the DATA one: a short Containers cell, the sentence in
 * "What it means". The view-side tabindex is backlogged deliberately, so a release does not change the layout
 * every blueprint page shares. This test holds the data to that, for every chamber rather than only the five,
 * because the next author's long cell would break the same page the same way.
 *
 * RED before the change: collegium 78/85/75, lattice 78/81/75, lodestar 78/81/75, alea 78/77/105,
 * ancilla 78/64/76 characters.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import { BLUEPRINTS } from './index'
// ⚠ the arch index exports LOADERS (id -> () => Promise<{ deep }>), not a flat object. My first version
// imported a name that does not exist and the file failed to load at all — a test that guesses a module's
// shape measures nothing, even when the thing it would have measured is right.
import { ARCH_LOADERS } from './arch/index'

// The older chambers' longest Containers cell is 19 characters ("one frame per plant"). 24 leaves room for
// "one frame per service" (21) and still cannot hold a sentence: the point is a count, not prose.
const MAX_CONTAINERS = 24
// A cell that reads like prose, whatever its length: a full stop followed by a space, or a comma and a verb.
const SENTENCE = /[.!?]\s|\bcarries\b|\bbeside\b|\bwith cross-registry\b/i

describe('the sizing table stays readable on a phone', () => {
  let chambers: Array<[string, any]> = []

  beforeAll(async () => {
    const loaded = await Promise.all(
      Object.entries(ARCH_LOADERS).map(async ([id, load]) => [id, (await load()).deep] as [string, any]),
    )
    chambers = loaded.filter(([, deep]) => deep?.sizing?.length)
  })

  it('has chambers with a sizing table at all, or every check below passes over nothing', () => {
    expect(chambers.length, 'no chamber carries a sizing table; this file would pass vacuously').toBeGreaterThan(5)
  })

  it('keeps every Containers cell a count rather than a sentence', () => {
    const tooLong: string[] = []
    const prose: string[] = []
    for (const [id, deep] of chambers) {
      for (const row of (deep as any).sizing as Array<{ level: string; what: string; containers: string }>) {
        const cell = String(row.containers ?? '')
        if (cell.length > MAX_CONTAINERS) tooLong.push(`${id} ${row.level}: ${cell.length} chars — ${cell}`)
        if (SENTENCE.test(cell)) prose.push(`${id} ${row.level}: ${cell}`)
      }
    }
    expect(tooLong, `a Containers cell longer than ${MAX_CONTAINERS} characters makes the table scroll on a `
      + `412 px phone, and nothing can reach that scroll with a keyboard`).toEqual([])
    expect(prose, 'a Containers cell reading as prose belongs in "What it means"').toEqual([])
  })

  it('still says what it means: the What column carries the description', () => {
    const thin: string[] = []
    for (const [id, deep] of chambers) {
      for (const row of (deep as any).sizing as Array<{ level: string; what: string }>) {
        if (String(row.what ?? '').trim().length < 20) thin.push(`${id} ${row.level}: ${row.what}`)
      }
    }
    expect(thin, 'moving the sentence out of Containers must not leave the row saying nothing').toEqual([])
  })

  it('every blueprint with a deep layer is covered by this gate', () => {
    const loaded = chambers.map(([id]) => id).sort()
    const known = BLUEPRINTS.map((b) => b.id)
    expect(loaded.every((id) => known.includes(id)),
      `a sizing table on a chamber the atlas does not list: ${loaded.filter((id) => !known.includes(id))}`).toBe(true)
    expect(loaded.length, 'the gate must cover every chamber whose deep layer has a sizing table')
      .toBe(Object.keys(ARCH_LOADERS).filter((id) => chambers.some(([c]) => c === id)).length)
  })
})
