import { describe, it, expect } from 'vitest'
import vectors from './schema.vectors.c4.json'
import catalog from '@/data/proxy/catalog.generated.json'
import { validate } from './schemaCheck'

/**
 * V0664 C4 (order gwo_85a6015257385f6bb010682e): the console's JSON-schema checker (the keywords the SDK's schemas use) is tested against the
 * real Python jsonschema (Draft 2020-12, what the registry's kit check runs): the same schema and instance must give the same errors as
 * (path, keyword) pairs. 240 cases: the shipped kits' manifests, proxy specs and plugin configs, and many mutations of each
 * (scratchpad/c4/gen_schema_vectors.py).
 */
const SCHEMAS: Record<string, any> = { manifest: (catalog as any).migration.manifest_schema, core: (catalog as any).core_schema }
for (const kind of ['source', 'sink']) for (const p of (catalog as any).plugins[kind]) SCHEMAS[`${kind}:${p.name}`] = p.config_schema
const sig = (errs: Array<{ path: Array<string | number>; validator: string }>) => errs.map((e) => `${JSON.stringify(e.path)}|${e.validator}`).sort()

describe('the schema checker agrees with Python\'s jsonschema, case by case', () => {
  for (const c of (vectors as any).cases as any[]) {
    it(c.name, () => {
      expect(sig(validate(SCHEMAS[c.schema], c.instance))).toEqual(sig(c.errors))
    })
  }
})

describe('the keywords, one at a time', () => {
  it('says each rule by its name and path, with a sentence a person can read', () => {
    const errs = validate({ type: 'object', required: ['a'], additionalProperties: false, properties: { a: { type: 'integer', minimum: 1 } } }, { a: 0, z: 1 })
    expect(errs.map((e) => e.validator).sort()).toEqual(['additionalProperties', 'minimum'])
    expect(errs.find((e) => e.validator === 'minimum')!.message).toMatch(/at least 1/)
    expect(errs.find((e) => e.validator === 'additionalProperties')!.message).toMatch(/z/)
  })
  it('keeps a bool apart from a number, in a type and in an enum', () => {
    expect(validate({ type: 'integer' }, true)).toHaveLength(1)
    expect(validate({ enum: [1] }, true)).toHaveLength(1)
    expect(validate({ type: ['string', 'integer'] }, 5)).toHaveLength(0)
  })
  it('counts a string\'s length in code points, as Python does', () => {
    expect(validate({ maxLength: 1 }, '😀')).toHaveLength(0)
    expect(validate({ maxLength: 1 }, 'ab')).toHaveLength(1)
  })
  it('skips the keywords that do not apply to the instance\'s type', () => {
    expect(validate({ pattern: '^a', minLength: 3, minimum: 5, required: ['x'], minItems: 2 }, null)).toHaveLength(0)
  })
})
