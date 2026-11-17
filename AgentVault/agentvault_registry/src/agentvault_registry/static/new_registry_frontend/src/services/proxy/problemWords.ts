// V0665 (order gwo_1533f427a9c3be0351088250, session-lead's note on C3: the builder's list still read jsonschema's
// "'listen' is a required property"): a schema error in the field's own words. Pure. The checker (schemaCheck.ts) says which
// keyword broke and with what (`params`); this turns that into a sentence that names the SETTING the way the form does
// (fieldWords: "Listen", "Timeout (seconds)"), never the schema's key or its quotes. Every sentence goes through the i18n layer
// with its parameters (the caller hands in `t` and `tp`), so a test needs no app. An error the mapping does not know comes back
// as the schema's own text (`what`), never as nothing. The place (the spec path) is not this module's: the builder keeps it.
import type { SchemaError } from './schemaCheck'

type Json = any

export interface Translate {
  t: (key: string, fallback: string) => string
  tp: (key: string, fallback: string, params: Record<string, string | number>) => string
}
export interface WordsContext {
  /** a config key as the form words it (spec.ts fieldWords) */
  label: (key: string) => string
  /** when the error is inside a plugin's config: which one (the role and the type's name), and the SDK the catalog was made from */
  plugin?: { role: string; type: string }
  sdkVersion?: string
}

/** What a JSON type is called to a person. */
const TYPE_WORDS: Record<string, [string, string]> = {
  string: ['proxy.b.w.type.string', 'text'],
  integer: ['proxy.b.w.type.integer', 'a whole number'],
  number: ['proxy.b.w.type.number', 'a number'],
  boolean: ['proxy.b.w.type.boolean', 'true or false'],
  object: ['proxy.b.w.type.object', 'a group of settings'],
  array: ['proxy.b.w.type.array', 'a list'],
  null: ['proxy.b.w.type.null', 'empty'],
}

/** The patterns the catalog's schemas use, each as what the value must do ("{field} must <rule>"). A pattern not in this table
 *  falls back to the schema's own text. A test reads the catalog and fails when a pattern is missing here. */
export const PATTERN_RULES: Record<string, [string, string]> = {
  '^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$': ['proxy.b.w.rule.name', 'use only letters, digits, dot, dash and underscore, start with a letter or digit, and be at most 63 characters'],
  '^https?://': ['proxy.b.w.rule.http', 'start with http:// or https://'],
  '^https?://[^/\\s]+': ['proxy.b.w.rule.httpHost', 'start with http:// or https:// and a host name'],
  '^[^:]*:\\d+$': ['proxy.b.w.rule.hostPort', 'be written host:port, for example 0.0.0.0:8080'],
  '^did:': ['proxy.b.w.rule.did', 'start with did:'],
  '^lm_[A-Za-z0-9]+$': ['proxy.b.w.rule.mandate', 'look like lm_ followed by letters or digits'],
  '\\.ics$': ['proxy.b.w.rule.ics', 'end with .ics'],
  '^[A-Z0-9]{2,10}$': ['proxy.b.w.rule.currency', 'be a code of 2 to 10 capital letters or digits'],
  '^/': ['proxy.b.w.rule.slash', 'start with /'],
}

const show = (v: Json): string => (typeof v === 'string' ? v : JSON.stringify(v))
const lastKey = (path: Array<string | number>): string | undefined => [...path].reverse().find((x) => typeof x === 'string') as string | undefined

/**
 * One schema error as a sentence in the field's words. `what` is the checker's own message (the fallback). The result never
 * names a schema keyword or a quoted key.
 */
export function sayProblem(e: SchemaError, what: string, ctx: WordsContext, tt: Translate): string {
  const p = e.params || {}
  const key = e.validator === 'required' ? (p.key as string | undefined) : lastKey(e.path)
  if (!key && e.validator !== 'additionalProperties') return what
  const field = key ? ctx.label(key) : ''
  const word = (t: string) => { const w = TYPE_WORDS[t]; return w ? tt.t(w[0], w[1]) : t }
  const n = (v: Json) => (typeof v === 'number' ? v : Number(v))
  switch (e.validator) {
    case 'required':
      return tt.tp('proxy.b.w.required', '{field} is required', { field })
    case 'type': {
      const allowed = (Array.isArray(p.allowed) ? p.allowed : []) as string[]
      if (!allowed.length) return what
      const what2 = allowed.map(word).reduce((a, b) => tt.tp('proxy.b.w.or', '{a} or {b}', { a, b }))
      return tt.tp('proxy.b.w.typeIs', '{field} must be {what}', { field, what: what2 })
    }
    case 'enum':
      return tt.tp('proxy.b.w.enum', '{field} must be one of {values}', { field, values: (Array.isArray(p.allowed) ? p.allowed : []).map(show).join(', ') })
    case 'const':
      return tt.tp('proxy.b.w.const', '{field} must be {value}', { field, value: show((p.allowed || [])[0]) })
    case 'pattern': {
      const rule = PATTERN_RULES[p.pattern as string]
      if (!rule) return what
      const text = tt.t(rule[0], rule[1])
      // a name in a map the schema keeps names for (the sources, actions and sinks): the name itself is what is refused
      if (p.propertyName !== undefined) return tt.tp('proxy.b.w.badName', '{name} is not a valid name in {field}: it must {rule}', { name: String(p.propertyName), field, rule: text })
      return tt.tp('proxy.b.w.pattern', '{field} must {rule}', { field, rule: text })
    }
    case 'minLength':
      return n(p.limit) === 1 ? tt.tp('proxy.b.w.minLengthOne', '{field} must have at least {n} character', { field, n: n(p.limit) })
        : tt.tp('proxy.b.w.minLengthMany', '{field} must have at least {n} characters', { field, n: n(p.limit) })
    case 'maxLength':
      return n(p.limit) === 1 ? tt.tp('proxy.b.w.maxLengthOne', '{field} must have at most {n} character', { field, n: n(p.limit) })
        : tt.tp('proxy.b.w.maxLengthMany', '{field} must have at most {n} characters', { field, n: n(p.limit) })
    case 'minimum':
      return tt.tp('proxy.b.w.minimum', '{field} must be at least {n}', { field, n: n(p.limit) })
    case 'maximum':
      return tt.tp('proxy.b.w.maximum', '{field} must be at most {n}', { field, n: n(p.limit) })
    case 'exclusiveMinimum':
      return tt.tp('proxy.b.w.exclusiveMinimum', '{field} must be more than {n}', { field, n: n(p.limit) })
    case 'minItems':
      return n(p.limit) === 1 ? tt.tp('proxy.b.w.minItemsOne', '{field} needs at least {n} item', { field, n: n(p.limit) })
        : tt.tp('proxy.b.w.minItemsMany', '{field} needs at least {n} items', { field, n: n(p.limit) })
    case 'uniqueItems':
      return tt.tp('proxy.b.w.uniqueItems', '{field} may not list the same item twice', { field })
    case 'minProperties':
      return n(p.limit) === 1 ? tt.tp('proxy.b.w.minPropertiesOne', '{field} needs at least {n} setting', { field, n: n(p.limit) })
        : tt.tp('proxy.b.w.minPropertiesMany', '{field} needs at least {n} settings', { field, n: n(p.limit) })
    case 'additionalProperties': {
      const extra = (Array.isArray(p.extra) ? p.extra : []) as string[]
      if (!extra.length) return what
      const fields = extra.map(ctx.label).join(', ')
      const many = extra.length > 1
      if (ctx.plugin && ctx.sdkVersion) {
        const params = { fields, type: ctx.plugin.type, role: tt.t(`proxy.b.w.role.${ctx.plugin.role}`, ctx.plugin.role), version: ctx.sdkVersion }
        return many ? tt.tp('proxy.b.w.extraOfMany', '{fields} are not settings of the {type} {role} in SDK {version}', params)
          : tt.tp('proxy.b.w.extraOfOne', '{fields} is not a setting of the {type} {role} in SDK {version}', params)
      }
      return many ? tt.tp('proxy.b.w.extraHereMany', '{fields} are not settings here', { fields })
        : tt.tp('proxy.b.w.extraHereOne', '{fields} is not a setting here', { fields })
    }
    case 'anyOf':
      return tt.tp('proxy.b.w.anyOf', '{field} is not in a shape that is allowed', { field })
    default:
      return what
  }
}
