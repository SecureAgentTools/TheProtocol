// V0664 C4 (order gwo_85a6015257385f6bb010682e): the migration builder's model. Pure: a person's choices in (kinds, a source and a writer from the catalog, a field
// mapping with transforms, parameters, reconcile, rollback), the two files of a kit out (migration.yaml and proxy.yaml as data and as YAML), the
// registry's publish gate run over them (kitCheck), and a preview of the mapping on a sample the person pasted or chose, which never leaves the
// browser (mapping.ts, pinned against Python). The shapes follow the SDK's shipped kits (theprotocol-sdk/proxy/migrations) and
// `tp-proxy migrate new`'s skeletons.
import catalog from '@/data/proxy/catalog.generated.json'
import { MappingRefused, apply as applyMapping, checkFields } from '@/services/proxy/mapping'
import { checkKit, type KitResult } from './kitCheck'
import { toYaml } from './yaml'
import { fillRows, reasonRows } from './reportView'

type Json = any
export type Kind = 'sql' | 'file' | 'rest'
export const KINDS: Kind[] = ['sql', 'file', 'rest']
const PLUGINS = (catalog as any).plugins as Record<string, Array<{ name: string; description?: string; config_schema: Json }>>
export const plugin = (role: 'source' | 'sink', name: string) => PLUGINS[role].find((p) => p.name === name)

/** The catalog's plugins a kit of this kind may use: a migration reads a table, a folder or an SFTP folder, and writes a table, a REST endpoint or files. */
export const SOURCES_FOR: Record<Kind, string[]> = { sql: ['sqlpoll'], file: ['filedrop', 'sftp'], rest: ['webhook'] }
export const WRITERS_FOR: Record<Kind, string[]> = { sql: ['sql_upsert'], file: ['file_out'], rest: ['rest'] }

const DESTINATION_KEYS = ['url', 'host', 'database', 'path', 'dir']
const SECRET_KEY = /(?:^|[_-])(?:secret|password|passwd|passphrase|token|api[_-]?key|private[_-]?key|credentials?)s?$/i

export interface MapPair { from: string; to: string }
export interface FieldRow {
  id: string
  target: string
  mode: 'path' | 'constant' | 'concat'
  path: string
  constant: string
  concat: string
  sep: string
  as: '' | 'text' | 'int' | 'decimal' | 'float' | 'bool' | 'date' | 'datetime' | 'json'
  format: string
  tz: string
  trim: boolean
  case: '' | 'upper' | 'lower' | 'title'
  round: string
  nullIf: string
  def: string
  optional: boolean
  map: MapPair[]
  mapDefault: string
  regex: string
  group: string
}
export interface ParamSpec { description: string; default: string; secret: boolean; enum: string }
export interface BuilderState {
  name: string
  title: string
  summary: string
  from: { kind: Kind; what: string }
  to: { kind: Kind; engines: string; what: string }
  source: { name: string; type: string; config: Record<string, Json> }
  sink: { name: string; type: string; config: Record<string, Json> }
  mapping: { name: string; fields: FieldRow[] }
  key: string
  parameters: Record<string, ParamSpec>
  rollback: 'auto' | 'manual'
  batchRows: string
  cutover: string
  sample: { text: string; format: 'csv' | 'json' | 'jsonl'; name: string }
}

let seq = 0
export const newField = (target = '', path = ''): FieldRow => ({ id: `f${++seq}`, target, mode: 'path', path, constant: '', concat: '', sep: ' ', as: '', format: '', tz: '', trim: false,
  case: '', round: '', nullIf: '', def: '', optional: false, map: [], mapDefault: '', regex: '', group: '' })

export function skeleton(from: Kind, to: Kind): BuilderState {
  const src = SOURCES_FOR[from][0]
  const snk = WRITERS_FOR[to][0]
  const sourceConfig: Record<string, Json> = src === 'sqlpoll' ? { engine: 'sqlite', path: '${SOURCE_PATH}', table: 'customers', cursor: 'id', poll_seconds: 0 }
    : src === 'filedrop' ? { path: '${SOURCE_DIR}', format: 'csv', settle_seconds: 0, poll_seconds: 0 } : {}
  const sinkConfig: Record<string, Json> = snk === 'sql_upsert' ? { engine: 'postgresql', host: '${TARGET_HOST}', database: '${TARGET_DATABASE}', user: '${TARGET_USER}', password: '${TARGET_PASSWORD}', table: '${TARGET_TABLE}', key: ['id'], on_conflict: 'update' }
    : snk === 'rest' ? { url: '${TARGET_URL}', method: 'PUT', bearer: '${TARGET_TOKEN}' } : { path: '${TARGET_DIR}', format: 'csv' }
  const base = src === 'sqlpoll' ? '$.payload.' : src === 'webhook' ? '$.payload.' : '$.payload.data.'
  return {
    name: '', title: '', summary: '',
    from: { kind: from, what: '' }, to: { kind: to, engines: to === 'sql' ? 'postgresql' : '', what: '' },
    source: { name: 'old', type: src, config: sourceConfig }, sink: { name: 'new', type: snk, config: sinkConfig },
    mapping: { name: 'main', fields: [newField('id', `${base}id`), newField('name', `${base}name`), newField('email', `${base}email`)] },
    key: 'id', parameters: {}, rollback: 'auto', batchRows: '1000', cutover: 'Stop the old system\nLoad again (only new rows move)\nReconcile again\nPoint the readers at the new system',
    sample: { text: '', format: 'jsonl', name: '' },
  }
}

// ── fields -> value nodes ─────────────────────────────────────────────────────────────────────────────────────────────

const num = (s: string): number | string => (/^-?\d+(\.\d+)?$/.test(s.trim()) ? Number(s) : s)
const list = (s: string) => s.split(/[\n,]/).map((x) => x.trim()).filter(Boolean)

/** The mapping's value for one field: a path, a constant, or a value node when transforms are chosen. */
export function fieldValue(r: FieldRow): Json {
  if (r.mode === 'constant') return r.constant
  const node: Record<string, Json> = {}
  if (r.mode === 'concat') { node.concat = list(r.concat); if (r.sep !== '') node.sep = r.sep }
  else node.path = r.path.trim()
  if (r.optional) node.required = false
  if (r.def !== '') node.default = r.def
  if (r.nullIf.trim()) node.null_if = list(r.nullIf)
  if (r.trim) node.trim = true
  if (r.case) node.case = r.case
  if (r.regex) { node.regex = r.regex; if (r.group !== '') node.group = /^\d+$/.test(r.group) ? Number(r.group) : r.group }
  const pairs = r.map.filter((p) => p.from !== '')
  if (pairs.length) { node.map = Object.fromEntries(pairs.map((p) => [p.from, p.to])); if (r.mapDefault !== '') node.map_default = r.mapDefault }
  if (r.as) node.as = r.as
  if (r.format) node.format = r.format
  if (r.tz) node.tz = r.tz
  if (r.round !== '' && /^-?\d+$/.test(r.round)) node.round = Number(r.round)
  return Object.keys(node).length === 1 && 'path' in node ? node.path : node
}

export function mappingFields(s: BuilderState): Record<string, Json> {
  const out: Record<string, Json> = {}
  for (const r of s.mapping.fields) if (r.target.trim()) out[r.target.trim()] = fieldValue(r)
  return out
}

// ── parameters ────────────────────────────────────────────────────────────────────────────────────────────────────────

const PLACEHOLDER = /\$\{([A-Za-z_][A-Za-z0-9_]*)\}/g
/** The parameter names a value uses, in order of first use. */
export function placeholders(doc: Json, found: Set<string> = new Set()): Set<string> {
  if (typeof doc === 'string') for (const m of doc.matchAll(PLACEHOLDER)) found.add(m[1])
  else if (Array.isArray(doc)) doc.forEach((x) => placeholders(x, found))
  else if (doc && typeof doc === 'object') Object.values(doc).forEach((x) => placeholders(x, found))
  return found
}

function secretNames(config: Json, out: Set<string> = new Set()): Set<string> {
  if (config && typeof config === 'object' && !Array.isArray(config)) {
    for (const [k, v] of Object.entries(config)) {
      if (typeof v === 'string' && SECRET_KEY.test(k)) for (const m of v.matchAll(PLACEHOLDER)) out.add(m[1])
      else secretNames(v, out)
    }
  }
  return out
}

/** The parameters the kit declares: every placeholder it uses (secret ones marked, with no default), with what the person wrote about each. */
export function parametersFor(s: BuilderState): Record<string, Json> {
  const used = new Set<string>()
  placeholders(s.source.config, used); placeholders(s.sink.config, used); placeholders(mappingFields(s), used)
  const secret = secretNames(s.source.config, secretNames(s.sink.config))
  const out: Record<string, Json> = {}
  for (const name of [...used, ...Object.keys(s.parameters).filter((n) => !used.has(n))]) {
    const p = s.parameters[name] || { description: '', default: '', secret: false, enum: '' }
    const spec: Record<string, Json> = {}
    if (p.description) spec.description = p.description
    const isSecret = secret.has(name) || p.secret
    if (isSecret) spec.secret = true
    else {
      if (p.default !== '') spec.default = p.default
      if (p.enum.trim()) spec.enum = list(p.enum)
    }
    out[name] = spec
  }
  return out
}

// ── the kit ───────────────────────────────────────────────────────────────────────────────────────────────────────────

export interface Kit { manifest: Json; proxy: Json; files: Record<string, string>; yaml: { manifest: string; proxy: string }; check: KitResult; fieldProblems: string[] }

function readme(s: BuilderState): string {
  return `# ${s.name || 'a-migration'}: ${s.title || 'a migration'}\n\n${s.summary || 'Written with the migration builder.'}\n\n`
    + `Try it with no account and no system: \`tp-proxy migrate dry-run --sample\`. Then against your own system, read-only: set each parameter with \`--set NAME=value\` `
    + `(a secret only as a reference: \`--set NAME=env:NAME\`).\n`
}

export function buildKit(s: BuilderState): Kit {
  const fields = mappingFields(s)
  const keyCols = list(s.key)
  const mapped = Object.keys(fields)
  const reconcileFields = mapped.filter((f) => !keyCols.includes(f))
  const manifest: Record<string, Json> = {
    schema: 'theprotocol.migration/v1', name: s.name, title: s.title,
    ...(s.summary ? { summary: s.summary } : {}),
    from: { kind: s.from.kind, ...(s.from.what ? { what: s.from.what } : {}) },
    to: { kind: s.to.kind, ...(list(s.to.engines).length ? { engines: list(s.to.engines) } : {}), ...(s.to.what ? { what: s.to.what } : {}) },
  }
  const params = parametersFor(s)
  if (Object.keys(params).length) manifest.parameters = params
  manifest.load = { mappings: [s.mapping.name], ...(/^\d+$/.test(s.batchRows) && Number(s.batchRows) > 0 ? { batch_rows: Number(s.batchRows) } : {}) }
  if (keyCols.length && s.sink.type === 'sql_upsert' && reconcileFields.length) {
    manifest.reconcile = [{ mapping: s.mapping.name, source: { key: keyCols, fields: reconcileFields }, target: { key: keyCols, fields: reconcileFields },
      pairs: Object.fromEntries(reconcileFields.map((f) => [f, f])) }]
  }
  const sampleFile = s.sample.text.trim() ? `sample/${s.sample.format === 'csv' ? 'sample.csv' : s.sample.format === 'json' ? 'sample.json' : 'sample.jsonl'}` : ''
  if (sampleFile) manifest.sample = { [s.source.name]: { file: sampleFile, format: s.sample.format } }
  const cut = s.cutover.split('\n').map((x) => x.trim()).filter(Boolean)
  if (cut.length) manifest.cutover = { checklist: cut }
  manifest.rollback = s.rollback

  const proxy: Record<string, Json> = {
    version: 1, name: s.name,
    sources: { [s.source.name]: { type: s.source.type, config: s.source.config } },
    sinks: { [s.sink.name]: { type: s.sink.type, config: s.sink.config } },
    mappings: [{ name: s.mapping.name, version: 1, from: s.source.name, to: s.sink.name, fields }],
  }
  const files: Record<string, string> = {}
  const yaml = { manifest: toYaml(manifest), proxy: toYaml(proxy, ['no registry and no identity: nothing here calls TheProtocol']) }
  files['migration.yaml'] = yaml.manifest
  files['proxy.yaml'] = yaml.proxy
  files['README.md'] = readme(s)
  if (sampleFile) files[sampleFile] = s.sample.text.endsWith('\n') ? s.sample.text : s.sample.text + '\n'
  const check = checkKit({ files, manifest, proxy })
  return { manifest, proxy, files, yaml, check, fieldProblems: checkFields(fields, '') }
}

// ── the sample and the preview ────────────────────────────────────────────────────────────────────────────────────────

/** RFC 4180 CSV: quoted fields, doubled quotes, a comma or a line break inside quotes; the first row names the columns. */
export function parseCsv(text: string): Array<Record<string, string>> {
  const rows: string[][] = []
  let row: string[] = [], cur = '', quoted = false
  const t = text.replace(/^﻿/, '')
  for (let i = 0; i < t.length; i++) {
    const c = t[i]
    if (quoted) {
      if (c === '"') { if (t[i + 1] === '"') { cur += '"'; i++ } else quoted = false } else cur += c
    } else if (c === '"') quoted = true
    else if (c === ',') { row.push(cur); cur = '' }
    else if (c === '\n' || c === '\r') { if (c === '\r' && t[i + 1] === '\n') i++; row.push(cur); cur = ''; if (row.some((x) => x !== '') || row.length > 1) rows.push(row); row = [] }
    else cur += c
  }
  if (cur !== '' || row.length) { row.push(cur); if (row.some((x) => x !== '')) rows.push(row) }
  if (!rows.length) return []
  const head = rows[0]
  return rows.slice(1).map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ''])))
}

export interface SampleRead { rows: Array<Record<string, Json>>; error: string }
/** What a pasted sample looks like: a JSON array, JSON lines, or (anything else) CSV. The person can still choose another format. */
export function sniffFormat(text: string): 'csv' | 'json' | 'jsonl' {
  const t = text.trimStart()
  if (t.startsWith('[')) return 'json'
  if (t.startsWith('{')) return 'jsonl'
  return 'csv'
}

export function parseSample(text: string, format: 'csv' | 'json' | 'jsonl'): SampleRead {
  const body = text.trim()
  if (!body) return { rows: [], error: '' }
  try {
    if (format === 'csv') return { rows: parseCsv(text), error: '' }
    if (format === 'jsonl') {
      const rows = body.split(/\r?\n/).filter((l) => l.trim()).map((l, i) => { try { return JSON.parse(l) } catch { throw new Error(`line ${i + 1} is not JSON`) } })
      if (rows.some((r) => !r || typeof r !== 'object' || Array.isArray(r))) return { rows: [], error: 'every line is a JSON object (one row)' }
      return { rows, error: '' }
    }
    const doc = JSON.parse(body)
    const rows = Array.isArray(doc) ? doc : Object.values(doc).find((v) => Array.isArray(v)) as Json[] | undefined
    if (!rows || rows.some((r) => !r || typeof r !== 'object' || Array.isArray(r))) return { rows: [], error: 'a JSON array of objects (one per row), or an object holding one' }
    return { rows, error: '' }
  } catch (e: any) { return { rows: [], error: String(e?.message || e) } }
}

/** What each source puts in a record's payload (the SDK's own shapes): a table gives the row itself, a file source {file, row, data}. */
export function payloadFor(sourceType: string, row: Record<string, Json>, index: number, file = 'sample'): Json {
  return sourceType === 'filedrop' || sourceType === 'sftp' ? { file, row: index, data: row } : row
}

export interface PreviewRow { index: number; ok: boolean; out?: Record<string, Json>; refused?: string }
export interface Preview { rows: PreviewRow[]; taken: number; mapped: number; rejected: number; reasons: ReturnType<typeof reasonRows>; fill: ReturnType<typeof fillRows>; sampleError: string; fieldProblems: string[] }

/** The mapping run over the sample the person gave: each row mapped or refused with the rule (never the value), and the counts a dry run reports. */
export function preview(s: BuilderState): Preview {
  const read = parseSample(s.sample.text, s.sample.format)
  const fields = mappingFields(s)
  const problems = checkFields(fields, '')
  const rows: PreviewRow[] = []
  const by: Record<string, number> = {}
  const fill: Record<string, { filled: number; null: number }> = {}
  read.rows.forEach((r, i) => {
    try {
      const out = applyMapping(fields, { record_id: String(i), source: s.source.name, meta: {}, observed_at: null, payload: payloadFor(s.source.type, r, i) })
      rows.push({ index: i, ok: true, out })
      for (const [f, v] of Object.entries(out)) { const c = (fill[f] ||= { filled: 0, null: 0 }); c[v === null || v === '' ? 'null' : 'filled']++ }
    } catch (e) {
      const why = e instanceof MappingRefused ? e.detail : 'could not be mapped'
      rows.push({ index: i, ok: false, refused: why }); by[why] = (by[why] || 0) + 1
    }
  })
  const rejected = rows.filter((r) => !r.ok).length
  const m = { rejected_by_reason: by, fields: fill }
  return { rows, taken: rows.length, mapped: rows.length - rejected, rejected, reasons: reasonRows(m), fill: fillRows(m), sampleError: read.error, fieldProblems: problems }
}
