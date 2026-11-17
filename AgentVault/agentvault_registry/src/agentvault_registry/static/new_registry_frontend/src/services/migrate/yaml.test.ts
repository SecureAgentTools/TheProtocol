import { describe, it, expect } from 'vitest'
import golden from './yaml.golden.c4.json'
import { toYaml } from './yaml'

/** V0664 C4 (order gwo_85a6015257385f6bb010682e): the YAML the builder writes. Each golden output was checked when it was made: Python's yaml.safe_load
 *  (what the registry and the SDK read with) gave back exactly the data it was written from (scratchpad/c4/yamlrt). The writer must keep producing
 *  those very texts; a change that alters one has to be checked the same way again. */
describe('the YAML writer', () => {
  for (const g of golden as any[]) {
    it(`writes ${g.name} as it was checked`, () => { expect(toYaml(g.doc)).toBe(g.yaml) })
  }
  it('quotes what a reader could take for something else, and leaves plain words plain', () => {
    const y = toYaml({ a: 'yes', b: '1e3', c: 'a: b', d: '${HOST}', e: 'plain-word', f: 'a/b.csv', g: '', h: '0123' })
    expect(y).toContain('a: "yes"')
    expect(y).toContain('b: "1e3"')
    expect(y).toContain('c: "a: b"')
    expect(y).toContain('d: "${HOST}"')
    expect(y).toContain('e: plain-word')
    expect(y).toContain('f: a/b.csv')
    expect(y).toContain('g: ""')
    expect(y).toContain('h: "0123"')
  })
  it('writes a float that PyYAML reads as a number, and escapes the line breaks YAML adds to JSON\'s', () => {
    expect(toYaml({ j: 1e-7 })).toContain('j: 1.0e-7')
    expect(toYaml({ s: 'a b' })).toContain('"a\\u2028b"')
  })
  it('puts leading comments first', () => {
    expect(toYaml({ a: 1 }, ['made by the console', 'check it'])).toBe('# made by the console\n# check it\na: 1\n')
  })
})
