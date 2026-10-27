import { describe, it, expect } from 'vitest'
import { buildAliasMap, resolveSessionKey, normKey } from './keyAlias'

const TARGETS = [
  { key: 'A', canonical: 'registry-a' },
  { key: 'B', canonical: 'frame-b' },
  { key: 'op-berlin', canonical: 'op-berlin' },
]
const has = (...keys: string[]) => (k: string) => keys.includes(k)

describe('buildAliasMap', () => {
  it('maps the letters onto the directory names', () => {
    expect(buildAliasMap(TARGETS)).toEqual({ a: 'registry-a', b: 'frame-b' })
  })
  it('does not record an alias that is the same as its canonical', () => {
    expect(buildAliasMap([{ key: 'op-doha', canonical: 'op-doha' }])).toEqual({})
  })
  it('tolerates junk rather than throwing on a bad payload', () => {
    expect(buildAliasMap(null)).toEqual({})
    expect(buildAliasMap(undefined)).toEqual({})
    expect(buildAliasMap([{}, { key: '' }, { canonical: 'x' }] as any)).toEqual({})
    expect(buildAliasMap('nope' as any)).toEqual({})
  })
  it('accumulates onto an existing map', () => {
    expect(buildAliasMap([{ key: 'C', canonical: 'frame-c' }], { a: 'registry-a' }))
      .toEqual({ a: 'registry-a', c: 'frame-c' })
  })
})

describe('resolveSessionKey', () => {
  const al = buildAliasMap(TARGETS)
  it('THE BUG: asked by the letter, finds the session held under the directory key', () => {
    expect(resolveSessionKey('A', has('registry-a'), al)).toBe('registry-a')
  })
  it('and the reverse — asked by the directory key, finds the letter', () => {
    expect(resolveSessionKey('registry-a', has('a'), al)).toBe('a')
  })
  it('prefers an exact hit over an alias', () => {
    expect(resolveSessionKey('a', has('a', 'registry-a'), al)).toBe('a')
  })
  it('invents nothing: with no session anywhere it returns the normalised input', () => {
    expect(resolveSessionKey('A', has(), al)).toBe('a')
    expect(resolveSessionKey('op-berlin', has(), al)).toBe('op-berlin')
  })
  it('does NOT connect an unrelated registry', () => {
    expect(resolveSessionKey('op-berlin', has('registry-a'), al)).toBe('op-berlin')
  })
  it('with no alias table it behaves exactly as before', () => {
    expect(resolveSessionKey('A', has('registry-a'), {})).toBe('a')
  })
  it('normalises case and whitespace', () => {
    expect(normKey('  Frame-B ')).toBe('frame-b')
    expect(resolveSessionKey('  A  ', has('registry-a'), al)).toBe('registry-a')
  })
})
