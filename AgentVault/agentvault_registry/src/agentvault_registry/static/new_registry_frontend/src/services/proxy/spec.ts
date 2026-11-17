// V0664 C3 (order gwo_4110e12c11a69a93de878829): the proxy spec builder's model. Pure: the plugins the SDK ships and their
// config schemas (the generated catalog), the eight recipes (generated from the SDK's proxy/recipes), a spec document in
// proxy.yaml's own shape (the builder edits it in place), the checks theprotocol-sdk's spec.py parse() makes (the core schema,
// each plugin's own config schema, the credential rule, the mappings' names), and what a person takes away: proxy.yaml, a
// compose snippet and the run commands. A live preview of a mapping runs on a row the person pasted, which never leaves the
// browser (services/proxy/mapping.ts, pinned against the Python mapping). Nothing here talks to a server.
import catalog from '@/data/proxy/catalog.generated.json'
import recipes from '@/data/proxy/recipes.generated.json'
import { toYaml } from '@/services/migrate/yaml'
import { payloadFor } from '@/services/migrate/builder'
import { MappingRefused, apply as applyMapping, checkFields, takes } from './mapping'
import { validate } from './schemaCheck'
import { sayProblem, type Translate } from './problemWords'

type Json = any

export type Role = 'source' | 'action' | 'sink'
export const ROLES: Role[] = ['source', 'action', 'sink']
export const SECTION: Record<Role, 'sources' | 'actions' | 'sinks'> = { source: 'sources', action: 'actions', sink: 'sinks' }

export interface PluginEntry { kind: Role; name: string; description?: string; config_schema: Json; internal?: boolean }
const PLUGINS = (catalog as any).plugins as Record<Role, PluginEntry[]>
export const CORE_SCHEMA: Json = (catalog as any).core_schema
export const SDK_VERSION: string = (catalog as any).sdk_version

/** A role's plugins as a person may choose them: by name, never one the SDK marks internal (the migration CLI's own). */
export function pluginsOf(role: Role): PluginEntry[] {
  return [...(PLUGINS[role] || [])].filter((p) => !p.internal).sort((a, b) => a.name.localeCompare(b.name))
}

export function plugin(role: Role, type: string): PluginEntry | undefined {
  return (PLUGINS[role] || []).find((p) => p.name === type)
}

/** How a setting is edited: a sub-form for an object whose fields are known, one item a line for a list of text, a
 *  name: value line each for a map of text, and JSON only for a setting with no fixed shape (said so on screen). */
export type FieldShape = 'form' | 'lines' | 'pairs' | 'json'

export interface FieldDesc {
  key: string
  type: string
  required: boolean
  secret: boolean
  shape?: FieldShape
  /** the object's own schema, for a sub-form */
  schema?: Json
  enumValues?: Json[]
  description?: string
  pattern?: string
  minimum?: number
  default?: Json
}

// ── a setting's key in words (pass 2, session-lead seq 4069: agent_did reads Agent DID, the key itself shown beside it) ──
const ACRONYMS: Record<string, string> = {
  did: 'DID', id: 'ID', ids: 'IDs', url: 'URL', uri: 'URI', api: 'API', tls: 'TLS', mtls: 'mTLS', ssl: 'SSL', sftp: 'SFTP',
  mqtt: 'MQTT', smtp: 'SMTP', qos: 'QoS', csv: 'CSV', json: 'JSON', jsonl: 'JSONL', xml: 'XML', sql: 'SQL', ca: 'CA', pem: 'PEM',
  http: 'HTTP', https: 'HTTPS', ttl: 'TTL', ip: 'IP', s3: 'S3', erp: 'ERP', dms: 'DMS', utc: 'UTC',
}
const WORDS: Record<string, string> = { dir: 'folder', s: '(seconds)', ms: '(milliseconds)' }
/** A config key as words: underscores read as spaces, acronyms as one writes them, a trailing _s as (seconds). */
export function fieldWords(key: string): string {
  const parts = key.split(/[_-]+/).filter(Boolean)
  const out = parts.map((w, i) => {
    const lw = w.toLowerCase()
    if (ACRONYMS[lw]) return ACRONYMS[lw]
    if (WORDS[lw] && (i > 0 || lw === 'dir')) return WORDS[lw]
    return lw
  })
  const first = out[0] || key
  if (!ACRONYMS[(parts[0] || '').toLowerCase()]) out[0] = first.charAt(0).toUpperCase() + first.slice(1)
  return out.join(' ')
}

const typeWord = (s: Json): string => {
  if (Array.isArray(s?.enum)) return 'enum'
  if (Array.isArray(s?.type)) return s.type.filter((t: string) => t !== 'null')[0] || 'string'
  return s?.type || (s?.properties ? 'object' : 'string')
}

/** A plugin's fields, from its config_schema: required ones first, then the rest, each in the schema's order. */
export function fieldsOf(schema: Json): FieldDesc[] {
  const props: Record<string, Json> = schema?.properties || {}
  const req = new Set<string>(schema?.required || [])
  const out = Object.entries(props).map(([key, s]): FieldDesc => {
    const f: FieldDesc = { key, type: typeWord(s), required: req.has(key), secret: !!s?.['x-secret'] }
    if (Array.isArray(s?.enum)) f.enumValues = s.enum
    if (s?.description) f.description = s.description
    if (s?.pattern) f.pattern = s.pattern
    const min = s?.minimum ?? s?.exclusiveMinimum
    if (typeof min === 'number') f.minimum = min
    if (s?.default !== undefined) f.default = s.default
    if (f.type === 'object') {
      if (s?.properties && Object.keys(s.properties).length) { f.shape = 'form'; f.schema = s }
      else f.shape = s?.additionalProperties?.type === 'string' ? 'pairs' : 'json'
    } else if (f.type === 'array') f.shape = s?.items?.type === 'string' ? 'lines' : 'json'
    return f
  })
  return [...out.filter((f) => f.required), ...out.filter((f) => !f.required)]
}

// ── the credential rule: theprotocol-sdk's spec.py REF and SECRET_KEY, copied (the stack's check_migration_pins.py pins
// the registry's copies; this is the console's): a key whose name says it holds a credential, or a field its schema marks
// x-secret, holds a reference, env:NAME or file:/path, never the credential itself ──────────────────────────────────────

export const REF = /^(env|file):(.+)$/
export const SECRET_KEY = /(?:^|[_-])(?:secret|password|passwd|passphrase|token|api[_-]?key|private[_-]?key|credentials?)s?$/i
export const isRef = (v: Json): boolean => typeof v === 'string' && REF.test(v.trim())
export const SECRET_RULE = 'a credential is written out: give it as env:NAME or file:/path'

/** For a form field: null when the value may stand (empty, or a reference), else why it may not (never the value). */
export function secretProblem(v: Json): string | null {
  if (v === undefined || v === null || v === '') return null
  return isRef(v) ? null : 'a credential is given as env:NAME or file:/path (a variable or a file the proxy reads), never written into the spec'
}

/** The dotted paths a config schema marks x-secret (spec.py _secret_paths). */
export function secretPaths(schema: Json, prefix = ''): string[] {
  const out: string[] = []
  for (const [k, s] of Object.entries((schema?.properties || {}) as Record<string, Json>)) {
    const p = `${prefix}${k}`
    if (s && typeof s === 'object') {
      if (s['x-secret']) out.push(p)
      out.push(...secretPaths(s, `${p}.`))
    }
  }
  return out
}

const get = (doc: Json, path: string): Json => path.split('.').reduce((n, k) => (n && typeof n === 'object' ? n[k] : undefined), doc)

/** spec.py literal_secrets: a declared secret path or a key named like a credential, holding a value that is not a reference. */
export function literalSecrets(doc: Json, declared: string[], prefix: string): string[] {
  const out = new Set<string>()
  for (const p of declared) {
    const v = get(doc, p)
    if (v !== undefined && v !== null && v !== '' && !isRef(v)) out.add(`${prefix}${p}`)
  }
  const walk = (node: Json, at: string) => {
    if (Array.isArray(node)) node.forEach((v, i) => walk(v, `${at}[${i}]`))
    else if (node && typeof node === 'object') {
      for (const [k, v] of Object.entries(node)) {
        const p = at ? `${at}.${k}` : k
        if (typeof v === 'string' && v && SECRET_KEY.test(k.trim()) && !isRef(v)) out.add(`${prefix}${p}`)
        walk(v, p)
      }
    }
  }
  walk(doc, '')
  return [...out].sort()
}

/** A problem the builder lists: `raw` is what tp-proxy validate's words give ("where: what", the form checkSpec has always returned
 *  and problemTarget reads), `say` (a schema error only) puts it in the field's own words through the i18n layer (V0665). */
export interface ProblemDetail { raw: string; say?: (tt: Translate) => string }
const plain = (raw: string): ProblemDetail => ({ raw })

const schemaDetails = (inst: Json, schema: Json, where: string, plugin?: { role: string; type: string }): ProblemDetail[] =>
  validate(schema, inst)
    .slice()
    .sort((a, b) => a.path.join('.').localeCompare(b.path.join('.')))
    .map((e) => ({
      raw: `${where}${e.path.length ? '.' + e.path.join('.') : ''}: ${e.message}`,
      say: (tt: Translate) => sayProblem(e, e.message, { label: fieldWords, plugin, sdkVersion: SDK_VERSION }, tt),
    }))

const TP_SOURCES = new Set(['theprotocol_events'])
const q = (s: string) => `'${s}'`

/** Every problem `tp-proxy validate` would name (spec.py parse(); a schema error in schemaCheck's words), or none. */
/** A problem as the builder shows it: where (the spec path, as tp-proxy validate names it) and what, and the id or test id
 *  of the control that fixes it (a part's field, the identity's field, a mapping's end), or null when no one control does. */
export function problemTarget(problem: string): { where: string; what: string; target: string | null } {
  const at = problem.indexOf(': ')
  if (at < 0) return { where: '', what: problem, target: null }
  const where = problem.slice(0, at)
  const what = problem.slice(at + 2)
  const required = /^'([\w-]+)' is a required property/.exec(what)?.[1]
  const ROLE: Record<string, Role> = { sources: 'source', actions: 'action', sinks: 'sink' }
  let m = /^(sources|actions|sinks)\.([^.]+)\.config(?:\.([\w-]+))?$/.exec(where)
  if (m) {
    const field = m[3] || required
    return { where, what, target: field ? `ppf-${ROLE[m[1]!]}-${m[2]}-${field}` : null }
  }
  m = /^(?:spec\.)?identity(?:\.([\w-]+))?$/.exec(where)
  if (m) {
    const field = m[1] || required
    return { where, what, target: field ? `ppf-identity-${field}` : null }
  }
  m = /^mappings\[(\d+)\](?:\.(name|from|to))?/.exec(where)
  if (m) return { where, what, target: m[2] ? `pb-mapping-${m[1]}-${m[2]}` : `pb-mapping-${m[1]}` }
  return { where, what, target: null }
}

export function checkSpec(doc: Json): string[] { return checkSpecDetailed(doc).map((d) => d.raw) }

/** checkSpec's problems, each with its words (V0665): the list the builder shows. */
export function checkSpecDetailed(doc: Json): ProblemDetail[] {
  const core = schemaDetails(doc, CORE_SCHEMA, 'spec')
  if (core.length) return core                       // as parse(): the rest is read only from a spec the core schema takes
  const problems: ProblemDetail[] = literalSecrets(doc.identity || {}, ['client_secret'], 'identity.').map((p) => plain(`${p}: ${SECRET_RULE}`))
  const needs = [
    ...Object.entries(doc.actions || {}).map(([n, s]: [string, Json]) => `actions.${n} (${s?.type})`),
    ...Object.entries(doc.sources || {}).filter(([, s]: [string, Json]) => TP_SOURCES.has(s?.type)).map(([n, s]: [string, Json]) => `sources.${n} (${s?.type})`),
  ]
  for (const part of ['registry', 'identity']) {
    if (needs.length && !doc[part]) {
      problems.push(plain(`spec.${part}: ${needs.join(', ')} ${needs.length === 1 ? 'calls' : 'call'} TheProtocol and ` +
        `${needs.length === 1 ? 'needs' : 'need'} the proxy's ${part}`))
    }
  }
  const names: Record<Role, Set<string>> = { source: new Set(), action: new Set(), sink: new Set() }
  for (const role of ROLES) {
    const section = SECTION[role]
    for (const [name, sec] of Object.entries((doc[section] || {}) as Record<string, Json>)) {
      names[role].add(name)
      const where = `${section}.${name}`
      const cfg = sec?.config || {}
      const p = plugin(role, sec?.type)
      if (!p) { problems.push(plain(`${where}.type: no ${role} called ${q(String(sec?.type))}`)); continue }
      problems.push(...schemaDetails(cfg, p.config_schema, `${where}.config`, { role, type: String(sec?.type) }))
      problems.push(...literalSecrets(cfg, secretPaths(p.config_schema), `${where}.config.`).map((x) => plain(`${x}: ${SECRET_RULE}`)))
    }
  }
  for (const both of [...names.action].filter((n) => names.sink.has(n)).sort()) {
    problems.push(plain(`sinks.${both}: an action is called ${q(both)} too (actions and sinks share one namespace)`))
  }
  const seen = new Set<string>()
  ;(doc.mappings || []).forEach((m: Json, i: number) => {
    const where = `mappings[${i}]`
    if (seen.has(m.name)) problems.push(plain(`${where}.name: ${q(m.name)} names another mapping too`))
    seen.add(m.name)
    if (!names.source.has(m.from)) problems.push(plain(`${where}.from: no source called ${q(m.from)}`))
    if (!names.action.has(m.to) && !names.sink.has(m.to)) problems.push(plain(`${where}.to: no action or sink called ${q(m.to)}`))
    for (const p of checkFields({ ...(m.fields || {}) }, '')) problems.push(plain(`${where}.fields.${p} (mapping ${q(m.name)})`))
  })
  return problems
}

// ── building it ──────────────────────────────────────────────────────────────────────────────────────────────────────

/** A new spec: the registry the console runs beside, the identity by reference, the retry the recipes use. */
export function newSpec(name = 'my-proxy'): Json {
  return {
    version: 1, name, registry: 'https://api.theprotocol.cloud',
    identity: { agent_did: 'env:AGENT_DID', client_id: 'env:CLIENT_ID', client_secret: 'env:CLIENT_SECRET' },
    state: `/data/${name}.proxy.db`, sources: {}, actions: {}, sinks: {}, mappings: [],
    retry: { first_s: 2, max_s: 300, attempts: 8 },
  }
}

export function addPart(doc: Json, role: Role, name: string, type: string): void {
  const section = SECTION[role]
  doc[section] ||= {}
  doc[section][name] = { type, config: {} }
}

/** Remove a source, action or sink, and the mappings that used it (a mapping names both ends). */
export function removePart(doc: Json, role: Role, name: string): void {
  delete (doc[SECTION[role]] || {})[name]
  const end = role === 'source' ? 'from' : 'to'
  doc.mappings = (doc.mappings || []).filter((m: Json) => m[end] !== name)
}

/** A new mapping from a source to an action or sink, named for what it joins (a number keeps the name unique). */
export function addMapping(doc: Json, from: string, to: string): Json {
  doc.mappings ||= []
  const taken = new Set(doc.mappings.map((m: Json) => m.name))
  let name = `${from}-to-${to}`.replace(/[^A-Za-z0-9_.-]/g, '-').slice(0, 63)
  for (let n = 2; taken.has(name); n++) name = `${from}-to-${to}-${n}`.slice(0, 63)
  const m = { name, version: 1, from, to, fields: {} as Record<string, Json> }
  doc.mappings.push(m)
  return m
}

const ORDER = ['version', 'name', 'registry', 'identity', 'state', 'sources', 'actions', 'sinks', 'mappings', 'retry', 'breaker', 'service']

/** proxy.yaml as `tp-proxy` reads it: the spec's own key order, credentials by reference. */
export function toProxyYaml(doc: Json): string {
  const ordered: Record<string, Json> = {}
  for (const k of ORDER) if (doc[k] !== undefined) ordered[k] = doc[k]
  for (const k of Object.keys(doc)) if (!(k in ordered)) ordered[k] = doc[k]
  return toYaml(ordered, [
    `${doc.name}: made in TheProtocol's proxy builder (theprotocol-sdk ${SDK_VERSION}).`,
    'Check it before a run: tp-proxy validate proxy.yaml',
  ])
}

/** The variables a spec reads its credentials from (every env:NAME in it). */
export function envNames(doc: Json): string[] {
  const out = new Set<string>()
  const walk = (n: Json) => {
    if (typeof n === 'string') { const m = REF.exec(n.trim()); if (m && m[1] === 'env') out.add(m[2]!) }
    else if (Array.isArray(n)) n.forEach(walk)
    else if (n && typeof n === 'object') Object.values(n).forEach(walk)
  }
  walk(doc)
  return [...out].sort()
}

/** A compose service that runs the spec: the SDK from PyPI at the version this catalog was made from (0.8.0 carries the
 *  proxy), the file mounted read-only, the state on a volume, the credentials from the environment. */
export function composeSnippet(doc: Json): string {
  const name = String(doc.name || 'my-proxy')
  const env = envNames(doc)
  return [
    `# ${name}: the proxy beside the system it reads. A connector that needs a driver has its own extra beside`,
    '# proxy: proxy-mqtt, proxy-sftp, proxy-s3, proxy-quantum, proxy-sql with proxy-postgresql, proxy-mysql or proxy-sqlserver.',
    'services:',
    `  ${name}:`,
    `    image: python:3.12-slim`,
    `    command: sh -c "pip install --quiet 'theprotocol-sdk[proxy]==${SDK_VERSION}' && tp-proxy run /app/proxy.yaml"`,
    '    restart: unless-stopped',
    '    volumes:',
    '      - ./proxy.yaml:/app/proxy.yaml:ro',
    `      - ${name}-data:/data`,
    ...(env.length ? ['    environment:', ...env.map((v) => `      ${v}: \${${v}}`)] : []),
    'volumes:',
    `  ${name}-data: {}`,
    '',
  ].join('\n')
}

export function runCommands(_doc: Json): string[] {
  return ['tp-proxy validate proxy.yaml', 'tp-proxy run proxy.yaml --dry-run', 'tp-proxy run proxy.yaml']
}

export interface PreviewOut { taken: boolean; fields?: Record<string, Json>; refused?: string }

/** One mapping on one row, as its source would deliver it: not taken (its `when`), taken and mapped, or refused with the rule. */
export function previewMapping(m: Json, sourceType: string, row: Record<string, Json>): PreviewOut {
  const rec = { record_id: 'preview', source: m.from, meta: {}, observed_at: null, payload: payloadFor(sourceType, row, 0) }
  if (!takes(m.when, rec)) return { taken: false }
  try {
    return { taken: true, fields: applyMapping({ ...(m.fields || {}) }, rec) }
  } catch (e) {
    return { taken: true, refused: e instanceof MappingRefused ? e.detail : 'could not be mapped' }
  }
}

// ── the recipes ──────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Recipe {
  id: string; name: string; summary: string; legacy: string; on_theprotocol: string; needs: string; try_it: string
  commands: string[]; check: string; proxy_yaml: string
  table: { legacy_system: string; source: string; on_theprotocol: string; out: string }
}
export const RECIPES: Recipe[] = (recipes as any).recipes
