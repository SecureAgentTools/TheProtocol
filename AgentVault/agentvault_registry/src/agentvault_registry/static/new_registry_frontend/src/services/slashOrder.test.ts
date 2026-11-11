import { describe, it, expect } from 'vitest'
import { FACTORY_ORDER, move, problems, sameOrder, toOrder, toRows, type SlashRow } from './slashOrder'

// V0658 (k): the slash order the admin view edits, read from and written to the registry's policy section
// (PUT /admin/enforcement/policy/section/slash_waterfall), with the registry's rules.

describe('slash order rows', () => {
  it('reads the factory order: the three own steps on, the cascade off and last', () => {
    expect(toRows(null)).toEqual([
      { source: 'bond', maxPercent: 100, enabled: true },
      { source: 'stake', maxPercent: 100, enabled: true },
      { source: 'liquid', maxPercent: 100, enabled: true },
      { source: 'cascade', maxPercent: 100, enabled: false },
    ])
    expect(toRows([])).toEqual(toRows(FACTORY_ORDER))
  })

  it('keeps a stored order, a step switched off and the cascade where it is on', () => {
    const rows = toRows([{ source: 'liquid', max_percent: 30 }, { source: 'bond', enabled: false },
      { source: 'stake', max_percent: 100 }, { source: 'cascade', max_percent: 25 }])
    expect(rows.map((r) => [r.source, r.maxPercent, r.enabled])).toEqual([
      ['liquid', 30, true], ['bond', 100, false], ['stake', 100, true], ['cascade', 25, true]])
  })

  it('shows a step the order does not list as off, after the listed ones', () => {
    expect(toRows([{ source: 'stake', max_percent: 50 }]).map((r) => [r.source, r.enabled])).toEqual([
      ['stake', true], ['bond', false], ['liquid', false], ['cascade', false]])
  })

  it('saves the cascade only while it is on, and a switched-off own step as enabled false', () => {
    const rows = toRows(FACTORY_ORDER)
    expect(toOrder(rows)).toEqual(FACTORY_ORDER)
    rows[0].enabled = false
    rows[3] = { source: 'cascade', maxPercent: 40, enabled: true }
    expect(toOrder(rows)).toEqual([{ source: 'bond', max_percent: 100, enabled: false },
      { source: 'stake', max_percent: 100 }, { source: 'liquid', max_percent: 100 },
      { source: 'cascade', max_percent: 40 }])
  })

  it('moves an own step and never the cascade', () => {
    const rows = toRows(FACTORY_ORDER)
    expect(move(rows, 2, -1).map((r) => r.source)).toEqual(['bond', 'liquid', 'stake', 'cascade'])
    expect(move(rows, 0, -1).map((r) => r.source)).toEqual(['bond', 'stake', 'liquid', 'cascade'])
    expect(move(rows, 2, 1).map((r) => r.source)).toEqual(['bond', 'stake', 'liquid', 'cascade'])
    expect(move(rows, 3, -1).map((r) => r.source)).toEqual(['bond', 'stake', 'liquid', 'cascade'])
    expect(rows.map((r) => r.source)).toEqual(['bond', 'stake', 'liquid', 'cascade'])   // the input is untouched
  })

  it('says what the registry would refuse', () => {
    const rows: SlashRow[] = toRows(FACTORY_ORDER).map((r) => ({ ...r, enabled: r.source === 'cascade' }))
    expect(problems(rows)).toEqual(['noOwnStep'])
    const bad = toRows(FACTORY_ORDER)
    bad[1].maxPercent = 120
    expect(problems(bad)).toEqual(['percent'])
    expect(problems(toRows(FACTORY_ORDER))).toEqual([])
  })

  it('tells an unchanged order from a changed one', () => {
    const a = toRows(FACTORY_ORDER)
    expect(sameOrder(a, toRows(FACTORY_ORDER))).toBe(true)
    expect(sameOrder(a, move(a, 1, 1))).toBe(false)
  })
})
