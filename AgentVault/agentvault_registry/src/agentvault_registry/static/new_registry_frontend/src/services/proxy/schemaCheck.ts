// V0664 C4 (order gwo_85a6015257385f6bb010682e): a JSON-schema checker for the keywords the SDK's schemas use (the migration manifest, the proxy spec,
// the plugins' config schemas), so a kit the console builds is checked in the browser by the same rules the registry's kit check applies
// (jsonschema, Draft 2020-12). Tested against the real jsonschema (schemaCheck.test.ts). Keywords it does not know are ignored, as the
// validator ignores annotations (description, default, x-secret, $id, $schema).
type Json = any
/** `params` (V0665): what the keyword said, so the builder can put the error in the field's own words (problemWords.ts): the types a
 *  field may be (`allowed`), the enum's values, the pattern, a bound (`limit`), the missing key, the keys that are not settings
 *  (`extra`), and for a refused name in a map the name itself (`propertyName`). */
export interface SchemaError { path: Array<string | number>; validator: string; message: string; params?: Record<string, any> }

const isObj = (v: Json): v is Record<string, Json> => v !== null && typeof v === 'object' && !Array.isArray(v)
const isNum = (v: Json) => typeof v === 'number' && Number.isFinite(v)

function typeOf(v: Json): string[] {
  if (v === null) return ['null']
  if (typeof v === 'boolean') return ['boolean']
  if (typeof v === 'string') return ['string']
  if (typeof v === 'number') return Number.isInteger(v) ? ['integer', 'number'] : ['number']
  if (Array.isArray(v)) return ['array']
  return ['object']
}

/** Equal the way jsonschema compares: a bool is not a number, numbers by value, arrays and objects deep. */
function same(a: Json, b: Json): boolean {
  if (typeof a === 'boolean' || typeof b === 'boolean') return a === b
  if (isNum(a) && isNum(b)) return a === b
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => same(x, b[i]))
  if (isObj(a) && isObj(b)) { const ka = Object.keys(a); return ka.length === Object.keys(b).length && ka.every((k) => k in b && same(a[k], b[k])) }
  return a === b
}

const cp = (s: string) => [...s].length

function run(schema: Json, inst: Json, path: Array<string | number>, out: SchemaError[]): void {
  if (!isObj(schema)) return
  const add = (validator: string, message: string, params?: Record<string, any>) => out.push({ path, validator, message, ...(params ? { params } : {}) })
  const kinds = typeOf(inst)

  if ('type' in schema) {
    const want = Array.isArray(schema.type) ? schema.type : [schema.type]
    if (!want.some((t: string) => kinds.includes(t))) add('type', `must be ${want.join(' or ')}`, { allowed: want })
  }
  if ('enum' in schema && !(schema.enum as Json[]).some((e) => same(e, inst))) add('enum', `must be one of ${JSON.stringify(schema.enum)}`, { allowed: schema.enum })
  if ('const' in schema && !same(schema.const, inst)) add('const', `must be ${JSON.stringify(schema.const)}`, { allowed: [schema.const] })

  if (typeof inst === 'string') {
    if ('pattern' in schema && !new RegExp(schema.pattern).test(inst)) add('pattern', `does not match ${schema.pattern}`, { pattern: schema.pattern })
    if ('minLength' in schema && cp(inst) < schema.minLength) add('minLength', `must be at least ${schema.minLength} characters`, { limit: schema.minLength })
    if ('maxLength' in schema && cp(inst) > schema.maxLength) add('maxLength', `must be at most ${schema.maxLength} characters`, { limit: schema.maxLength })
  }
  if (isNum(inst)) {
    if ('minimum' in schema && inst < schema.minimum) add('minimum', `must be at least ${schema.minimum}`, { limit: schema.minimum })
    if ('maximum' in schema && inst > schema.maximum) add('maximum', `must be at most ${schema.maximum}`, { limit: schema.maximum })
    if ('exclusiveMinimum' in schema && inst <= schema.exclusiveMinimum) add('exclusiveMinimum', `must be above ${schema.exclusiveMinimum}`, { limit: schema.exclusiveMinimum })
  }
  if (Array.isArray(inst)) {
    if ('minItems' in schema && inst.length < schema.minItems) add('minItems', `must hold at least ${schema.minItems} item(s)`, { limit: schema.minItems })
    if (schema.uniqueItems && inst.some((x, i) => inst.findIndex((y) => same(x, y)) !== i)) add('uniqueItems', 'must hold no item twice')
    if (isObj(schema.items)) inst.forEach((x, i) => run(schema.items, x, [...path, i], out))
  }
  if (isObj(inst)) {
    if ('minProperties' in schema && Object.keys(inst).length < schema.minProperties) add('minProperties', `must hold at least ${schema.minProperties} key(s)`, { limit: schema.minProperties })
    if ('required' in schema) for (const k of schema.required as string[]) if (!(k in inst)) add('required', `'${k}' is a required property`, { key: k })
    const props: Record<string, Json> = isObj(schema.properties) ? schema.properties : {}
    for (const [k, sub] of Object.entries(props)) if (k in inst) run(sub, inst[k], [...path, k], out)
    if ('additionalProperties' in schema) {
      const extra = Object.keys(inst).filter((k) => !(k in props))
      if (schema.additionalProperties === false) { if (extra.length) add('additionalProperties', `unknown key(s): ${extra.join(', ')}`, { extra }) }
      else if (isObj(schema.additionalProperties)) for (const k of extra) run(schema.additionalProperties, inst[k], [...path, k], out)
    }
    if (isObj(schema.propertyNames)) {
      for (const k of Object.keys(inst)) {
        const e: SchemaError[] = []
        run(schema.propertyNames, k, path, e)
        for (const x of e) out.push({ ...x, params: { ...(x.params || {}), propertyName: k } })
      }
    }
  }
  if (Array.isArray(schema.anyOf)) {
    const ok = (schema.anyOf as Json[]).some((s) => { const e: SchemaError[] = []; run(s, inst, path, e); return e.length === 0 })
    if (!ok) add('anyOf', 'must match at least one of the allowed shapes')
  }
}

/** Every error of `inst` against `schema`: the path to it, the keyword it broke and a sentence. */
export function validate(schema: Json, inst: Json): SchemaError[] {
  const out: SchemaError[] = []
  run(schema, inst, [], out)
  return out
}
