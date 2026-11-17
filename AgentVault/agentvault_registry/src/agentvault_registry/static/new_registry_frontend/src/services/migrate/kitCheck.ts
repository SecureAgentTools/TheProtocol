// V0664 C4 (order gwo_85a6015257385f6bb010682e): the kit check, in the browser. This is the registry's publish gate (services/workflow_templates.check_kit,
// AgentVault v0664/cut: M4's upload rules) ported rule by rule, so a kit the console builds is told what the registry would refuse BEFORE it is
// downloaded or saved. Tested against vectors made by running that function (kitCheck.test.ts).
//
// The console works on the OBJECTS the builder holds (migration.yaml and proxy.yaml as data), so there is no YAML parser here; the files' texts
// matter for the file rules (names, size, no NUL). It returns every problem, the first of which is the sentence the registry gives.
import catalog from '@/data/proxy/catalog.generated.json'
import { validate } from '@/services/proxy/schemaCheck'

type Json = any
export interface KitProblem { rule: 'files' | 'schema' | 'manifest' | 'secret' | 'destination' | 'sample'; file: string; sentence: string; where?: string[] }
export interface KitResult { ok: boolean; problems: KitProblem[] }
export interface KitInput { files: Record<string, string>; manifest: Json; proxy: Json }
export interface KitOptions {
  /** 'registry': a ${PARAM} in a secret field is a written-out credential (what the registry's gate does today, which refuses all three
   *  shipped kits); 'intended' (default): it is a reference when it names a declared secret parameter, as the SDK's own check treats it. */
  secretPlaceholders?: 'registry' | 'intended'
}

const CAPS = (catalog as any).migration.kit_caps
const MAX_FILES: number = CAPS.max_files
const MAX_FILE_BYTES: number = CAPS.max_file_bytes
const MAX_KIT_BYTES: number = CAPS.max_total_bytes
const PATH_RE = new RegExp(CAPS.path_pattern)
export const REQUIRED_FILES = ['migration.yaml', 'proxy.yaml', 'README.md']
const MANIFEST_SCHEMA = (catalog as any).migration.manifest_schema

const SECRET_KEY = /(?:^|[_-])(?:secret|password|passwd|passphrase|token|api[_-]?key|private[_-]?key|credentials?)s?$/i
const REF = /^(env|file):(.+)$/s
export const isRef = (v: Json) => typeof v === 'string' && REF.test(v.trim())
const PLACEHOLDER_ONLY = /^\$\{([A-Za-z_][A-Za-z0-9_]{0,62})\}$/
const PARAM_URL = /^\$\{([A-Za-z_][A-Za-z0-9_]{0,62})\}([/?]\S*)?$/
const DESTINATION_KEYS = ['url', 'host', 'database', 'path', 'dir']
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '::1']
const isObj = (v: Json): v is Record<string, Json> => v !== null && typeof v === 'object' && !Array.isArray(v)
const utf8Len = (s: string) => new TextEncoder().encode(s).length
const pyRepr = (s: string) => `'${s.replace(/\\/g, '\\\\').replace(/'/g, "\\'")}'`

/** The paths in `doc` whose key says it holds a credential and whose value is written out (not a reference). */
export function writtenOutSecrets(doc: Json, prefix: string, declaredSecrets?: Set<string>): string[] {
  const out = new Set<string>()
  const fine = (v: string) => isRef(v) || (declaredSecrets !== undefined && (() => { const m = PLACEHOLDER_ONLY.exec(v.trim()); return !!m && declaredSecrets.has(m[1]) })())
  const walk = (node: Json, at: string) => {
    if (isObj(node)) {
      for (const [k, v] of Object.entries(node)) {
        const p = at ? `${at}.${k}` : String(k)
        if (typeof v === 'string' && v && SECRET_KEY.test(String(k).trim()) && !fine(v)) out.add(prefix + p)
        walk(v, p)
      }
    } else if (Array.isArray(node)) node.forEach((v, i) => walk(v, `${at}[${i}]`))
  }
  walk(doc, '')
  return [...out].sort()
}

function localDefault(value: Json, key: string): boolean {
  const v = String(value).trim()
  if (key === 'url') {
    let u: URL
    try { u = new URL(v) } catch { return false }
    return (u.protocol === 'http:' || u.protocol === 'https:') && !u.username && !u.password && LOCAL_HOSTS.includes(u.hostname.replace(/^\[|\]$/g, ''))
  }
  if (key === 'host') return LOCAL_HOSTS.includes(v.replace(/^\[|\]$/g, ''))
  if (!v || /^[/~\\]/.test(v) || v.includes(':') || v.includes('\\')) return false
  return !v.split('/').includes('..')
}

/** Every host, url, database and path in the kit's sources and sinks must be a ${PARAM} the manifest declares, and that parameter's default,
 *  when it has one, must be local. The paths that break the rule, never their values. */
export function destinationRefusals(proxy: Json, manifest: Json): string[] {
  const params: Record<string, Json> = isObj(manifest?.parameters) ? manifest.parameters : {}
  const out = new Set<string>()
  const walk = (node: Json, at: string) => {
    if (!isObj(node)) return
    for (const [k, v] of Object.entries(node)) {
      const p = `${at}.${k}`
      if (DESTINATION_KEYS.includes(String(k))) {
        const m = typeof v === 'string' ? (k === 'url' ? PARAM_URL : PLACEHOLDER_ONLY).exec(v) : null
        if (!m) { out.add(`proxy.yaml:${p}`); continue }
        const name = m[1]
        const spec = params[name]
        if (!isObj(spec)) out.add(`proxy.yaml:${p} (names \${${name}}, which migration.yaml does not declare)`)
        else if (k !== 'database' && spec.default !== undefined && spec.default !== null && spec.default !== '' && !localDefault(spec.default, String(k))) out.add(`migration.yaml:parameters.${name}.default`)
      } else if (isObj(v)) walk(v, p)
    }
  }
  for (const section of ['sources', 'sinks']) {
    const plugs = proxy?.[section]
    if (!isObj(plugs)) continue
    for (const [name, plug] of Object.entries(plugs)) if (isObj(plug)) walk(plug.config, `${section}.${name}.config`)
  }
  return [...out].sort()
}

function schemaSentence(e: { path: Array<string | number>; validator: string; message: string }, instance: Json): string {
  const path = e.path.map(String).join('.') || '(the document)'
  if (e.validator === 'additionalProperties') {
    let target = instance
    for (const p of e.path) target = target?.[p]
    const sub = (() => { let s: Json = MANIFEST_SCHEMA; for (const p of e.path) s = s?.properties?.[p] ?? s?.items ?? s?.additionalProperties; return s })()
    const allowed = new Set(Object.keys(sub?.properties || {}))
    const extra = Object.keys(isObj(target) ? target : {}).filter((k) => !allowed.has(k)).sort()
    return `migration.yaml ${path}: unknown key(s) ${extra.join(', ')}`
  }
  if (e.validator === 'required') return `migration.yaml ${path}: a required key is missing (${e.message.split(' ')[0]})`
  return `migration.yaml ${path}: fails the schema's ${e.validator} rule`
}

/** M3's checks beyond the schema, in its order. */
function manifestChecks(manifest: Json): KitProblem[] {
  const out: KitProblem[] = []
  const add = (sentence: string) => out.push({ rule: 'manifest', file: 'migration.yaml', sentence })
  for (const [name, p] of Object.entries(isObj(manifest.parameters) ? manifest.parameters : {})) {
    const spec = p as Json
    if (spec?.secret && 'default' in spec) add(`migration.yaml parameters.${name}.default: a secret parameter has no default (it is given as a reference, env:NAME or file:/path, when the kit runs)`)
    if (Array.isArray(spec?.enum) && 'default' in spec && !spec.enum.some((e: Json) => e === spec.default)) add(`migration.yaml parameters.${name}.default: the default is not one of its enum`)
  }
  const steps: string[] = (Array.isArray(manifest.workflow) ? manifest.workflow : []).map((w: Json) => w.key)
  for (const w of Array.isArray(manifest.workflow) ? manifest.workflow : []) {
    if (w.input_from && !steps.includes(w.input_from)) add(`migration.yaml workflow.${w.key}.input_from: names no step of the workflow`)
  }
  ;(Array.isArray(manifest.reconcile) ? manifest.reconcile : []).forEach((r: Json, i: number) => {
    if ((r?.source?.key || []).length !== (r?.target?.key || []).length) add(`migration.yaml reconcile[${i}]: the source and target keys name a different number of columns`)
  })
  return out
}

export function checkKit(input: KitInput, opts: KitOptions = {}): KitResult {
  const problems: KitProblem[] = []
  const files = input.files
  if (!isObj(files) || !Object.keys(files).length) return { ok: false, problems: [{ rule: 'files', file: 'kit', sentence: 'files is a JSON object of path to text' }] }
  const names = Object.keys(files)
  if (names.length > MAX_FILES) problems.push({ rule: 'files', file: 'kit', sentence: `a kit holds at most ${MAX_FILES} files (this one holds ${names.length})` })
  let total = 0
  for (const path of names) {
    const text = files[path]
    if (!PATH_RE.test(path) || path.length > 300) {
      problems.push({ rule: 'files', file: path, sentence: `a path breaks the path rule (relative, letters, digits, '.', '_', '-' and '/'): ${pyRepr(path.slice(0, 80))}` })
      return { ok: false, problems }                                  // the registry stops at the first file rule
    }
    if (typeof text !== 'string' || text.includes('\u0000')) {
      problems.push({ rule: 'files', file: path, sentence: `${path} is not text (a kit carries UTF-8 text only)` })
      return { ok: false, problems }
    }
    const size = utf8Len(text)
    if (size > MAX_FILE_BYTES) { problems.push({ rule: 'files', file: path, sentence: `${path} is over 256 KiB` }); return { ok: false, problems } }
    total += size
  }
  if (problems.length) return { ok: false, problems }
  if (total > MAX_KIT_BYTES) return { ok: false, problems: [{ rule: 'files', file: 'kit', sentence: 'the kit is over 2 MiB in all' }] }
  for (const name of REQUIRED_FILES) if (!(name in files)) return { ok: false, problems: [{ rule: 'files', file: name, sentence: `the kit has no ${name}` }] }

  const manifest = input.manifest
  const proxy = input.proxy
  // the schema: every error, in the registry's order (by the path as text), each as the registry words it
  const errs = validate(MANIFEST_SCHEMA, manifest).sort((a, b) => {
    const x = a.path.map(String), y = b.path.map(String)
    for (let i = 0; i < Math.min(x.length, y.length); i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1
    return x.length - y.length
  })
  for (const e of errs) problems.push({ rule: 'schema', file: 'migration.yaml', sentence: schemaSentence(e, manifest), where: e.path.map(String) })
  // the registry stops at the first thing it refuses; a person building a kit should see everything at once, so the rest is checked too (the
  // first problem listed is always the registry's own sentence). M3's four checks read the manifest's shape, so they wait for a valid schema.
  if (!errs.length) problems.push(...manifestChecks(manifest))

  const declared = opts.secretPlaceholders === 'registry' ? undefined
    : new Set(Object.entries(isObj(manifest.parameters) ? manifest.parameters : {}).filter(([, p]) => isObj(p) && (p as Json).secret === true).map(([n]) => n))
  const leaks = [...writtenOutSecrets(proxy, 'proxy.yaml:', declared), ...writtenOutSecrets(manifest, 'migration.yaml:', declared)]
  if (leaks.length) problems.push({ rule: 'secret', file: 'proxy.yaml', where: [...new Set(leaks)].sort(),
    sentence: `a credential is written out at ${[...new Set(leaks)].sort().join(', ')}: write an env:NAME or file:/path reference instead` })
  const places = destinationRefusals(proxy, manifest)
  if (places.length) problems.push({ rule: 'destination', file: 'proxy.yaml', where: places,
    sentence: `the kit names a destination of its own at ${places.join(', ')}: every host, url and path in its sources and sinks is a \${PARAM} the user sets, and a default for a host, url or path may only be local (localhost, 127.0.0.1, ::1, or a relative path inside the kit)` })
  for (const [source, s] of Object.entries(isObj(manifest.sample) ? manifest.sample : {})) {
    const f = (s as Json)?.file
    if (!(f in files)) problems.push({ rule: 'sample', file: 'migration.yaml', sentence: `the sample ${f} the manifest names for ${source} is not in the kit` })
  }
  return { ok: problems.length === 0, problems }
}
