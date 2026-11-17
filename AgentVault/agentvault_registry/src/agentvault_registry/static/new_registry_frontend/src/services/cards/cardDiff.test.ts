/**
 * V0663 (order gwo_f8251964b96cb1759350b69d, his suggestion 9, his yes at room seq 3068): two agent cards side by side,
 * the differences marked, so a reader sees what makes a card different (a quantum card's extension, say).
 *
 * services/cards/cardDiff compares two cards as JSON, path by path:
 *   - every leaf is one path (objects by key, arrays by index), marked same, changed, only in A or only in B;
 *   - a whole object or array present on one side only is one path, not one per leaf;
 *   - the order follows A, then what only B has, so the table reads like the cards;
 *   - each card prints as JSON lines, each line carrying the path it belongs to and its mark for that side, so a pane
 *     can mark the lines that differ;
 *   - a card that is not an object compares as one value.
 * Red on b27f2ebaf: the module does not exist.
 */
import { describe, expect, it } from 'vitest'
import { diffCards, cardLines, diffSummary } from './cardDiff'

const A = { name: 'Qubit Broker', version: '1.0', skills: [{ id: 'route' }, { id: 'price' }],
  capabilities: { streaming: true }, extensions: [{ uri: 'pay' }] }
const B = { name: 'Qubit Broker', version: '1.1', skills: [{ id: 'route' }],
  capabilities: { streaming: true, quantum: { backends: 2 } }, iconUrl: 'https://i.example.org/q.png' }

describe('diffCards', () => {
  const rows = diffCards(A, B)
  const by = Object.fromEntries(rows.map((r) => [r.path, r.status]))

  it('marks each leaf same, changed, only in A or only in B', () => {
    expect(by['name']).toBe('same')
    expect(by['version']).toBe('changed')
    expect(by['skills[0].id']).toBe('same')
    expect(by['capabilities.streaming']).toBe('same')
    expect(by['iconUrl']).toBe('only_b')
  })

  it('a subtree on one side only is one path', () => {
    expect(by['skills[1]']).toBe('only_a')
    expect(by['extensions']).toBe('only_a')
    expect(by['capabilities.quantum']).toBe('only_b')
    expect(Object.keys(by).some((p) => p.startsWith('capabilities.quantum.'))).toBe(false)
  })

  it("follows A's order, then what only B has", () => {
    expect(rows.map((r) => r.path)).toEqual(['name', 'version', 'skills[0].id', 'skills[1]', 'capabilities.streaming',
      'capabilities.quantum', 'extensions', 'iconUrl'])
  })

  it('carries both values on a row', () => {
    const v = rows.find((r) => r.path === 'version')!
    expect([v.a, v.b]).toEqual(['1.0', '1.1'])
  })

  it('counts what differs', () => {
    expect(diffSummary(rows)).toEqual({ same: 3, changed: 1, only_a: 2, only_b: 2 })
  })

  it('compares a value that is not an object as one value', () => {
    expect(diffCards(null, { a: 1 })).toEqual([{ path: '', status: 'changed', a: null, b: { a: 1 } }])
    expect(diffCards({ a: 1 }, { a: 1 })).toEqual([{ path: 'a', status: 'same', a: 1, b: 1 }])
  })

  it('a value that changes type is changed, not a subtree on both sides', () => {
    const r = diffCards({ x: { y: 1 } }, { x: 'flat' })
    expect(r).toEqual([{ path: 'x', status: 'changed', a: { y: 1 }, b: 'flat' }])
  })
})

describe('cardLines', () => {
  it("prints a card as JSON lines, each with its path and this side's mark", () => {
    const rows = diffCards(A, B)
    const left = cardLines(A, rows, 'a')
    const right = cardLines(B, rows, 'b')
    const lineOf = (lines: ReturnType<typeof cardLines>, needle: string) => lines.find((l) => l.text.includes(needle))!
    expect(lineOf(left, '"version"').mark).toBe('changed')
    expect(lineOf(right, '"version"').mark).toBe('changed')
    expect(lineOf(left, '"name"').mark).toBe('same')
    expect(lineOf(right, '"iconUrl"').mark).toBe('only')
    expect(lineOf(left, '"extensions"').mark).toBe('only')
    expect(lineOf(left, '"uri": "pay"').mark).toBe('only')   // a line inside a one-sided subtree is marked too
    expect(left.map((l) => l.text).join('\n')).toBe(JSON.stringify(A, null, 2))
  })
})
