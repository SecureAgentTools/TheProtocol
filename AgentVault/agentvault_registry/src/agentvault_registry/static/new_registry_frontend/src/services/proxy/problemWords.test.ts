import { describe, it, expect } from 'vitest'
import en from '@/i18n/locales/en.json'
import catalog from '@/data/proxy/catalog.generated.json'
import { addPart, checkSpec, checkSpecDetailed, CORE_SCHEMA, fieldWords, newSpec, plugin, SDK_VERSION, type Role } from './spec'
import { PATTERN_RULES, sayProblem, type Translate, type WordsContext } from './problemWords'
import { validate, type SchemaError } from './schemaCheck'

/**
 * V0665 (order gwo_1533f427a9c3be0351088250): the builder's problems in the field's own words. One test per error kind, each read
 * from a real schema of the generated catalog (the SDK's own), plus the fallback: an error the mapping does not know comes back as
 * the schema's text, never as nothing. The translator below reads en.json and REFUSES a key that is missing or whose English is not
 * the fallback in the code, so the bundle and the code cannot drift.
 */
const bundle = (key: string): unknown => key.split('.').reduce<any>((n, k) => (n && typeof n === 'object' ? n[k] : undefined), en)
const fill = (s: string, p: Record<string, string | number>) => s.replace(/\{(\w+)\}/g, (_m, k) => String(p[k]))
const tt: Translate = {
  t: (key, fallback) => {
    expect(bundle(key), `en.json has ${key}`).toBe(fallback)
    return fallback
  },
  tp: (key, fallback, params) => {
    expect(bundle(key), `en.json has ${key}`).toBe(fallback)
    return fill(fallback, params)
  },
}
const ctxFor = (role?: Role, type?: string): WordsContext => ({ label: fieldWords, plugin: role && type ? { role, type } : undefined, sdkVersion: SDK_VERSION })
const sayAll = (schema: any, inst: any, role?: Role, type?: string): string[] =>
  validate(schema, inst).map((e) => sayProblem(e, e.message, ctxFor(role, type), tt))
const cfg = (role: Role, type: string) => plugin(role, type)!.config_schema

describe('a schema error in the field\'s own words', () => {
  it('required: "Listen is required", for each missing setting, in the schema\'s order', () => {
    expect(sayAll(cfg('source', 'webhook'), {}, 'source', 'webhook')).toEqual(['Listen is required', 'Path is required'])
  })

  it('type: a whole number, and a number or text for a setting that takes either', () => {
    const base = { mandate: 'lm_abc', max_amount: 5 }
    expect(sayAll(cfg('action', 'payment'), { ...base, ttl_seconds: 'x' }, 'action', 'payment')).toEqual(['TTL seconds must be a whole number'])
    expect(sayAll(cfg('action', 'payment'), { ...base, max_amount: true }, 'action', 'payment')).toEqual(['Max amount must be a number or text'])
    expect(sayAll(cfg('sink', 'webhook'), { url: 'https://x.test/a', headers: [] }, 'sink', 'webhook')).toEqual(['Headers must be a group of settings'])
  })

  it('enum: "Method must be one of POST, PUT"', () => {
    expect(sayAll(cfg('sink', 'webhook'), { url: 'https://x.test/a', method: 'GET' }, 'sink', 'webhook')).toEqual(['Method must be one of POST, PUT'])
  })

  it('const: the version of the spec', () => {
    const doc = { ...newSpec('x'), version: 2 }
    expect(sayAll(CORE_SCHEMA, doc)).toEqual(['Version must be 1'])
  })

  it('pattern: what the value has to look like, in words', () => {
    expect(sayAll(cfg('source', 'webhook'), { listen: '8080', path: '/in' }, 'source', 'webhook')).toEqual(['Listen must be written host:port, for example 0.0.0.0:8080'])
    expect(sayAll(cfg('source', 'webhook'), { listen: ':8080', path: 'in' }, 'source', 'webhook')).toEqual(['Path must start with /'])
    expect(sayAll(cfg('sink', 'webhook'), { url: 'ftp://x' }, 'sink', 'webhook')).toEqual(['URL must start with http:// or https://'])
    expect(sayAll(cfg('action', 'payment'), { mandate: 'nope', max_amount: 1 }, 'action', 'payment'))
      .toEqual(['Mandate must look like lm_ followed by letters or digits'])
  })

  it('a refused name in a map (propertyNames) says which name and where', () => {
    const doc = { ...newSpec('x'), actions: { 'bad name': { type: 'payment', config: {} } } }
    const out = sayAll(CORE_SCHEMA, doc)
    expect(out).toEqual(['bad name is not a valid name in Actions: it must use only letters, digits, dot, dash and underscore, start with a letter or digit, and be at most 63 characters'])
  })

  it('minimum, maximum and exclusiveMinimum: the bound, with the number', () => {
    expect(sayAll(cfg('source', 'webhook'), { listen: ':1', path: '/p', max_bytes: 10 }, 'source', 'webhook')).toEqual(['Max bytes must be at least 1024'])
    expect(sayAll(cfg('source', 'webhook'), { listen: ':1', path: '/p', commit_timeout_s: 0 }, 'source', 'webhook')).toEqual(['Commit timeout (seconds) must be more than 0'])
    const sftp = sayAll(cfg('sink', 'file_out'), { dir: '/o', format: 'csv', columns: ['a'], sftp: { host: 'h', port: 70000, user: 'u' } }, 'sink', 'file_out')
    expect(sftp).toContain('Port must be at most 65535')
  })

  it('minLength and maxLength: one or many characters', () => {
    expect(sayAll(cfg('source', 'webhook'), { listen: ':1', path: '/p', id_field: '' }, 'source', 'webhook')).toEqual(['ID field must have at least 1 character'])
    expect(sayAll(cfg('action', 'attestation'), { target_agent_did: 'did:x', attestation_type: 'x'.repeat(121) }, 'action', 'attestation'))
      .toContain('Attestation type must have at most 120 characters')
    const many = { path: ['x'], validator: 'minLength', message: 'm', params: { limit: 3 } } as SchemaError
    expect(sayProblem(many, many.message, ctxFor(), tt)).toBe('X must have at least 3 characters')
  })

  it('minItems and uniqueItems: a list that is too short, or names an item twice', () => {
    expect(sayAll(cfg('sink', 'email_digest'), { to: [] }, 'sink', 'email_digest')).toContain('To needs at least 1 item')
    expect(sayAll(cfg('sink', 'file_out'), { dir: '/o', format: 'csv', columns: ['a', 'a'] }, 'sink', 'file_out')).toContain('Columns may not list the same item twice')
  })

  it('additionalProperties inside a plugin: names the plugin and the SDK the catalog was made from', () => {
    expect(sayAll(cfg('source', 'webhook'), { listen: ':1', path: '/p', poll_s: 5 }, 'source', 'webhook'))
      .toEqual([`Poll (seconds) is not a setting of the webhook source in SDK ${SDK_VERSION}`])
    expect(sayAll(cfg('source', 'webhook'), { listen: ':1', path: '/p', poll_s: 5, retries: 3 }, 'source', 'webhook'))
      .toEqual([`Poll (seconds), Retries are not settings of the webhook source in SDK ${SDK_VERSION}`])
  })

  it('additionalProperties outside a plugin: "is not a setting here"', () => {
    const doc: any = { ...newSpec('x'), colour: 'red' }
    expect(sayAll(CORE_SCHEMA, doc)).toEqual(['Colour is not a setting here'])
  })

  it('anyOf: the shapes a list item may take', () => {
    const out = sayAll(cfg('source', 'mqtt'), { host: 'h', topics: [5] }, 'source', 'mqtt')
    expect(out).toContain('Topics is not in a shape that is allowed')
  })

  it('minProperties (no catalog schema uses it yet): one or many', () => {
    const e = validate({ type: 'object', minProperties: 2 }, { a: 1 })
    const withPath = e.map((x) => ({ ...x, path: ['headers'] }))
    expect(withPath.map((x) => sayProblem(x, x.message, ctxFor(), tt))).toEqual(['Headers needs at least 2 settings'])
  })

  it('never names a schema keyword or a quoted key', () => {
    const all = [
      ...sayAll(cfg('source', 'webhook'), {}, 'source', 'webhook'), ...sayAll(cfg('source', 'webhook'), { listen: 8, path: 'p', zz: 1 }, 'source', 'webhook'),
      ...sayAll(cfg('sink', 'webhook'), { url: 'x', method: 'GET' }, 'sink', 'webhook'),
    ]
    for (const s of all) expect(s, s).not.toMatch(/required property|'[\w-]+'|does not match|unknown key/)
  })
})

describe('what the mapping does not know', () => {
  it('an unknown keyword comes back as the schema\'s own text', () => {
    const e = { path: ['x'], validator: 'dependentRequired', message: 'depends on y' } as SchemaError
    expect(sayProblem(e, e.message, ctxFor(), tt)).toBe('depends on y')
  })
  it('a pattern the table has no words for comes back as the schema\'s own text', () => {
    const e = { path: ['x'], validator: 'pattern', message: 'does not match ^q+$', params: { pattern: '^q+$' } } as SchemaError
    expect(sayProblem(e, e.message, ctxFor(), tt)).toBe('does not match ^q+$')
  })
  it('an error with no setting to name (the whole document) and one with no parameters keep the schema\'s text', () => {
    const root = { path: [], validator: 'type', message: 'must be object', params: { allowed: ['object'] } } as SchemaError
    expect(sayProblem(root, root.message, ctxFor(), tt)).toBe('must be object')
    const bare = { path: ['x'], validator: 'type', message: 'must be integer' } as SchemaError
    expect(sayProblem(bare, bare.message, ctxFor(), tt)).toBe('must be integer')
    const extra = { path: ['x'], validator: 'additionalProperties', message: 'unknown key(s): ' } as SchemaError
    expect(sayProblem(extra, extra.message, ctxFor(), tt)).toBe('unknown key(s): ')
  })
  it('every pattern the catalog uses has its words (a new one in a later SDK fails here, not in front of a person)', () => {
    const seen = new Set<string>()
    const walk = (n: any) => {
      if (Array.isArray(n)) n.forEach(walk)
      else if (n && typeof n === 'object') {
        if (typeof n.pattern === 'string') seen.add(n.pattern)
        Object.values(n).forEach(walk)
      }
    }
    walk(CORE_SCHEMA)
    for (const role of Object.keys((catalog as any).plugins)) for (const p of (catalog as any).plugins[role]) walk(p.config_schema)
    expect(seen.size).toBeGreaterThan(5)
    expect([...seen].filter((p) => !(p in PATTERN_RULES))).toEqual([])
  })
})

describe('the builder\'s list: a webhook source and a payment action with their required settings missing', () => {
  const spec = () => {
    const doc = newSpec('field-words')
    addPart(doc, 'source', 'in', 'webhook')
    addPart(doc, 'action', 'pay', 'payment')
    return doc
  }
  it('says each of the four in its own words and keeps the place as tp-proxy validate names it', () => {
    const d = checkSpecDetailed(spec())
    expect(d.map((x) => x.say!(tt))).toEqual(['Listen is required', 'Path is required', 'Mandate is required', 'Max amount is required'])
    expect(d.map((x) => x.raw)).toEqual([
      "sources.in.config: 'listen' is a required property", "sources.in.config: 'path' is a required property",
      "actions.pay.config: 'mandate' is a required property", "actions.pay.config: 'max_amount' is a required property",
    ])
  })
  it('checkSpec is unchanged: the same strings, in the same order', () => {
    expect(checkSpec(spec())).toEqual(checkSpecDetailed(spec()).map((x) => x.raw))
  })
  it('a problem that is not a schema error (a name used twice, a credential in the clear) keeps its own sentence, with no words function', () => {
    const doc = spec()
    doc.identity.client_secret = 'plain-secret-value'
    const d = checkSpecDetailed(doc)
    const secret = d.find((x) => x.raw.startsWith('identity.client_secret'))
    expect(secret).toBeTruthy()
    expect(secret!.say).toBeUndefined()
  })
})
