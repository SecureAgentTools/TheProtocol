import { describe, it, expect } from 'vitest'
import { railOrder, railRank, railVisible } from './railOrder'

const L = (symbol: string, status: string) => ({ symbol, status } as any)

describe('railOrder', () => {
  it('puts trading first and delisted last, keeping the venue order inside a group', () => {
    const got = railOrder([L('D1', 'delisted'), L('T1', 'trading'), L('D2', 'delisted'), L('H1', 'halted'),
      L('I1', 'ipo'), L('T2', 'trading'), L('X1', 'paused-by-a-later-build')]).map((l) => l.symbol)
    expect(got).toEqual(['T1', 'T2', 'I1', 'H1', 'X1', 'D1', 'D2'])
  })
  it('does not mutate what the venue answered', () => {
    const src = [L('D1', 'delisted'), L('T1', 'trading')]
    railOrder(src)
    expect(src.map((l) => l.symbol)).toEqual(['D1', 'T1'])
  })
  it('ranks an unknown status between halted and delisted', () => {
    expect(railRank('halted')).toBeLessThan(railRank('weird'))
    expect(railRank('weird')).toBeLessThan(railRank('delisted'))
    expect(railRank(undefined)).toBe(3)
  })
})

describe('railVisible', () => {
  const rows = [{ id: 'a', status: 'trading' }, { id: 'b', status: 'delisted' }, { id: 'c', status: 'halted' }] as any[]
  it('folds delisted rows away unless asked', () => {
    expect(railVisible(rows, false).map((r) => r.id)).toEqual(['a', 'c'])
    expect(railVisible(rows, true).map((r) => r.id)).toEqual(['a', 'b', 'c'])
  })
  it('keeps the selected listing in view, delisted or not', () => {
    expect(railVisible(rows, false, 'b').map((r) => r.id)).toEqual(['a', 'b', 'c'])
  })
})
