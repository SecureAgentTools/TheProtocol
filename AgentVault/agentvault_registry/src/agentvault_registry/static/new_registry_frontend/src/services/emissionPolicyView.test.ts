/**
 * The Emission policy page's rules (agentvault2-69, 2026-10-25): a lost event reads red on the side that loses it, a
 * refusal of what a side never writes is grey, a count that was not read is never 0, and the filters and order hold.
 */
import { describe, expect, it } from 'vitest'
import type { EffectivePolicy, MatrixRow } from './api/emissionPolicy'
import { barPercent, countText, findingCodes, matches, ordered, projectionCell, registryCell, severity, severityCounts, tegCell } from './emissionPolicyView'

const row = (o: Partial<MatrixRow>): MatrixRow => ({
  event_type: 'X', row: { emit_from_registry: true, emit_from_teg: false, skip_in_projection: false, description: null, updated_at: null },
  emitted_by: ['registry'], registry: 'allow', teg: 'refuse', projection: 'audit', balance_moving: false,
  store_count: 0, shadow_would_refuse: 0, findings: [], ...o,
})

describe('the cells', () => {
  it('a row the registry may write is green on its side and grey on the TEG\'s', () => {
    const r = row({})
    expect(registryCell(r)).toMatchObject({ tone: 'ok', key: 'mayEmit' })
    expect(tegCell(r)).toMatchObject({ tone: 'off', key: 'refused' })
  })
  it('a type the registry emits and its gate refuses reads lost, in red, on the registry side', () => {
    const r = row({ registry: 'refuse', findings: ['registry-emits-refused'] })
    expect(registryCell(r)).toMatchObject({ tone: 'bad', key: 'lost' })
    expect(severity(r)).toBe('bad')
  })
  it('the TEG fails closed: no row is red only where the TEG itself emits the type', () => {
    expect(tegCell(row({ row: null, teg: 'no-row-refused', emitted_by: ['teg'] })).tone).toBe('bad')
    expect(tegCell(row({ row: null, teg: 'no-row-refused', emitted_by: ['registry'] })).tone).toBe('off')
    expect(tegCell(row({ teg: 'always-allowed', emitted_by: ['teg'] }))).toMatchObject({ tone: 'ok', key: 'alwaysAllowed' })
  })
  it('the registry with no row says what its mode does', () => {
    expect(registryCell(row({ row: null, registry: 'no-row-shadow' }))).toMatchObject({ tone: 'warn', key: 'noRowCounted' })
    expect(registryCell(row({ row: null, registry: 'no-row-allowed' }))).toMatchObject({ tone: 'warn', key: 'noRowAllowed' })
    expect(registryCell(row({ row: null, registry: 'no-row-refused' })).tone).toBe('bad')
  })
  it('the projection: balance types in cyan, a skipped balance type in red', () => {
    expect(projectionCell(row({ projection: 'balance', balance_moving: true }))).toMatchObject({ tone: 'info', key: 'movesBalances' })
    expect(projectionCell(row({ projection: 'skipped', findings: ['balance-type-skipped'] })).tone).toBe('bad')
    expect(projectionCell(row({ projection: 'audit' })).key).toBe('notCounted')
  })
  it('an unknown gate value is never shown as a good one', () => {
    expect(registryCell(row({ registry: 'something-new' as any })).tone).toBe('warn')
    expect(severity(row({ findings: ['a-new-code' as any] }))).toBe('warn')
  })
})

describe('the counts', () => {
  it('a count that was not read is "not read", never 0', () => {
    expect(countText(null, 'en')).toBe('not read')
    expect(countText(undefined, 'en')).toBe('not read')
    expect(countText(0, 'en')).toBe('0')
    expect(countText(3063972, 'en')).toBe('3,063,972')
  })
  it('a bar is absent for a count not read, empty for none, and log-scaled', () => {
    expect(barPercent(null, 100)).toBeNull()
    expect(barPercent(0, 100)).toBe(0)
    expect(barPercent(100, 100)).toBe(100)
    const small = barPercent(3, 3063972)!
    expect(small).toBeGreaterThanOrEqual(2)
    expect(small).toBeLessThan(20)
  })
})

describe('filters and order', () => {
  const rows = [
    row({ event_type: 'Quiet', findings: ['row-without-emitter'], emitted_by: [], store_count: 0 }),
    row({ event_type: 'TokensTransferred', projection: 'balance', balance_moving: true, store_count: 226316, emitted_by: ['registry', 'teg'] }),
    row({ event_type: 'Lost', registry: 'refuse', findings: ['registry-emits-refused'], store_count: 4 }),
    row({ event_type: 'NoRow', row: null, registry: 'no-row-shadow', teg: 'no-row-refused', findings: ['emitted-without-row'], store_count: null }),
  ]
  it('worst first, then the balance-moving types, then the busiest', () => {
    expect(ordered(rows).map((r) => r.event_type)).toEqual(['Lost', 'NoRow', 'Quiet', 'TokensTransferred'])
  })
  it('a finding, the balance types, an emitter and a search each narrow the list', () => {
    const f = (o: Partial<Parameters<typeof matches>[1]>) => rows.filter((r) => matches(r, { finding: 'any', query: '', emitter: 'any', ...o })).map((r) => r.event_type)
    expect(f({ finding: 'registry-emits-refused' })).toEqual(['Lost'])
    expect(f({ finding: 'balance' })).toEqual(['TokensTransferred'])
    expect(f({ emitter: 'both' })).toEqual(['TokensTransferred'])
    expect(f({ emitter: 'none' })).toEqual(['Quiet'])
    expect(f({ query: 'tokens' })).toEqual(['TokensTransferred'])
  })
  it('the strip counts each type once, at its worst', () => {
    expect(severityCounts(rows)).toEqual({ bad: 1, warn: 1, note: 1, clean: 1 })
  })
  it('the finding chips: worst first, then the most frequent, none with a zero', () => {
    const view = { summary: { types: 4, rows: 3, findings: { 'row-without-emitter': 30, 'emitted-without-row': 101, 'registry-emits-refused': 1, 'both-may-emit': 0 } } } as unknown as EffectivePolicy
    expect(findingCodes(view)).toEqual(['registry-emits-refused', 'emitted-without-row', 'row-without-emitter'])
  })
})
