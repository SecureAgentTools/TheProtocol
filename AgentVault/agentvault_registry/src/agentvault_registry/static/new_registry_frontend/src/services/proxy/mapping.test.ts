import { describe, it, expect } from 'vitest'
import vectors from './mapping.vectors.c4.json'
import shared from '@/data/proxy/mapping_vectors.generated.json'
import { MappingRefused, apply, checkFields, isValueNode, lookup, regexWarnings, takes, VALUE_KEYS } from './mapping'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): the TypeScript port of the value nodes (the SDK's proxy mapping.py, the chain's
 * final file at stack v0664/stack-cut 300a3bed) is tested against the Python itself: every expected value in the vectors file was
 * produced by running the real mapping.py over the case (scratchpad/c4/gen_vectors.py), never written by hand. A case that
 * disagrees with Python fails here. C1's shared vectors (src/data/proxy/mapping_vectors.generated.json, which the SDK's own tests read
 * as well) are read case by case in the second block: a case that disagrees with Python fails both suites.
 *
 * Known differences, named (JSON has one number type; regex dialects differ): a case that depends on a payload's FLOAT-ness is marked
 * `ts_skip` in the vectors; a regex error's own words (Python's `re` versus JavaScript's) are compared up to the sentence that names
 * the field and the rule.
 */
const record = vectors.record as any
const doc = (payload: any) => ({ payload, record_id: record.record_id, source: record.source, meta: record.meta, observed_at: record.observed_at })
const rec = (payload: any) => ({ record_id: record.record_id, source: record.source, meta: record.meta, observed_at: record.observed_at, payload })

describe('the value nodes agree with the Python mapping, case by case', () => {
  for (const c of vectors.cases as any[]) {
    const it_ = c.ts_skip ? it.skip : it
    it_(c.name, () => {
      if ('refused' in c.expected) {
        let err: any = null
        try { apply({ f: c.fields }, rec(c.payload)) } catch (e) { err = e }
        expect(err, `${c.name} should refuse`).toBeInstanceOf(MappingRefused)
        expect(err.detail).toBe(c.expected.refused)
      } else {
        const got = apply({ f: c.fields }, rec(c.payload))
        expect(got.f).toEqual(c.expected.value)
      }
    })
  }
})

describe('the shared vectors of the SDK (C1), case by case', () => {
  for (const c of (shared as any).cases as any[]) {
    it(c.name, () => {
      const r = { record_id: c.record.record_id, source: c.record.source, meta: c.record.meta, observed_at: c.record.observed_at ?? null, payload: c.record.payload }
      if ('refusal' in c) {
        let err: any = null
        try { apply(c.fields, r) } catch (e) { err = e }
        expect(err, `${c.name} should refuse`).toBeInstanceOf(MappingRefused)
        expect(err.detail).toBe(c.refusal)
        for (const never of c.never_contains || []) expect(err.detail).not.toContain(never)    // a refusal never repeats the record's value
      } else {
        expect(apply(c.fields, r)).toEqual(c.expect)
      }
    })
  }
})

describe('a record is taken only when its mapping\'s `when` holds', () => {
  for (const w of vectors.when as any[]) {
    it(w.name, () => { expect(takes(w.when, rec(w.payload))).toBe(w.expected) })
  }
})

describe('a bad node is named when the spec is loaded, by its field and the rule', () => {
  for (const c of vectors.checks as any[]) {
    it(c.name, () => {
      // a pattern's own error text is the regex engine's: compared up to the part that names the field and the rule
      const cut = (s: string) => s.replace(/ \(.*\)$/, '')
      expect(checkFields(c.fields).map(cut)).toEqual(c.problems.map(cut))
    })
  }
})

describe('the shape of the port', () => {
  it('has the same value vocabulary', () => {
    expect([...VALUE_KEYS].sort()).toEqual(['as', 'case', 'concat', 'default', 'format', 'group', 'map', 'map_default', 'null_if', 'path', 'regex', 'required', 'round', 'sep', 'tz', 'trim'].sort())
  })
  it('knows a value node from an object', () => {
    expect(isValueNode({ path: '$.payload.a', as: 'int' })).toBe(true)
    expect(isValueNode({ concat: ['$.payload.a'] })).toBe(true)
    expect(isValueNode({ path: 'no-dollar' })).toBe(false)
    expect(isValueNode({ path: '$.x', extra: 1 })).toBe(false)
    expect(isValueNode({})).toBe(false)
  })
  it('reads a path like Python: a list index, a missing part', () => {
    const d = doc({ a: { b: [10, 20] } })
    expect(lookup(d, '$.payload.a.b.1')).toBe(20)
    expect(lookup(d, '$.payload.a.b.2')).toBeUndefined()
    expect(lookup(d, '$.payload.nope')).toBeUndefined()
  })
  it('names the field and the rule in a refusal and never the record\'s value', () => {
    let err: any
    try { apply({ price: { path: '$.payload.p', as: 'int' } }, rec({ p: 'SECRET-123' })) } catch (e) { err = e }
    expect(err.detail).toBe('price: not a whole number')
    expect(String(err.detail)).not.toContain('SECRET')
  })
})

describe('a regex field warns about the spellings the two engines read differently', () => {
  it('says nothing about an ordinary pattern', () => {
    for (const p of ['ID-(\\d+)', '^[A-Z]{2}\\d{3,5}$', '(a|b)+c?', '\\.csv$']) expect(regexWarnings(p), p).toEqual([])
  })
  it('names a lookbehind, a Python named group, a possessive quantifier, an atomic group, a Unicode class, \\A and \\Z', () => {
    expect(regexWarnings('(?<=a)b')[0]).toMatch(/lookbehind/)
    expect(regexWarnings('(?<!a)b')[0]).toMatch(/lookbehind/)
    expect(regexWarnings('(?P<n>\\d+)')[0]).toMatch(/named group/)
    expect(regexWarnings('a++')[0]).toMatch(/possessive/)
    expect(regexWarnings('a*+b')[0]).toMatch(/possessive/)
    expect(regexWarnings('(?>a)')[0]).toMatch(/atomic/)
    expect(regexWarnings('\\p{L}+')[0]).toMatch(/Unicode class/)
    expect(regexWarnings('\\Aab\\Z').join(' ')).toMatch(/\\A and \\Z/)
  })
  it('does not take an escaped plus for a possessive quantifier', () => { expect(regexWarnings('a\\++')).toEqual([]) })
})
