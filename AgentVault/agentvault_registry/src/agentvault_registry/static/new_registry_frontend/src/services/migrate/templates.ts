// V0664 M5 (order gwo_5a4ea8476b97147f3056405e): the pure half of the Migrate console, on the contract's names
// (sessionlogs2026/DESIGN_2026-11-14_MIGRATION_TEMPLATES.md §C and §D): the library's routes are /api/v1/workflow-templates, the
// commands are `tp-proxy migrate`. Nothing here fetches or touches the DOM, so the views and their tests call it.
//
// A secret never travels through this console: a parameter that holds one is offered only as an environment reference
// (`--set NAME=env:NAME`, the rule of the proxy's spec), and the README is rendered through the same sanitizing renderer the
// chat and the docs use (markdown-it with html off, then DOMPurify), never as raw markup.
import { renderMarkdown } from '@/services/chat/messageText'

export type MigrationKind = 'sql' | 'file' | 'rest'

export interface TemplateListing {
  id: string
  slug: string
  title: string
  summary: string
  kind: string
  from_kind: string
  to_kind: string
  owner_agent_did: string
  visibility: string
  pricing_model: 'free' | 'purchase' | string
  price: string
  price_currency: string
  fork_share_bps: number
  forked_from_template_id: string | null
  current_version: number
  /** kit downloads (what the Most used sort orders by) */
  uses: number
  /** distinct users of the template as a workflow */
  used_by: number
  certified: number
  forks: number
}

export interface VersionRow { version: number; content_hash: string; published_at: string; changelog: string }
export interface StepRow { key: string; role: string; acceptance: string; budget_share: number | null }
export interface Structure {
  steps: StepRow[]
  parameter_names: string[]
  /** parameters that hold a secret: only ever an environment reference */
  secret_parameters: string[]
  connector_kinds: { from: string[]; to: string[] }
  /** the mapping name -> how many fields are reconciled */
  field_counts: Record<string, number>
  what: { from: string; to: string }
  samples: number
  cutover_steps: number
  rollback: string
}
export interface TemplateDetail {
  listing: TemplateListing
  versions: VersionRow[]
  structure: Structure
}

export interface Filters { from: string; to: string; price: 'any' | 'free' | 'paid'; q: string; sort: 'new' | 'uses' | 'certified' }
export const DEFAULT_FILTERS: Filters = { from: '', to: '', price: 'any', q: '', sort: 'new' }

const KIND_WORDS: Record<string, string> = { sql: 'a SQL database', file: 'files', rest: 'a REST API' }
export function kindWords(kind: string): string {
  return KIND_WORDS[kind] || kind
}

/** A decimal as the column pads it ("5.0000000000") read plainly ("5"); anything that is not a decimal is returned as it came. */
export function decimalWords(v: string): string {
  const x = String(v ?? '')
  if (!/^-?\d+(\.\d+)?$/.test(x)) return x
  return x.includes('.') ? x.replace(/0+$/, '').replace(/\.$/, '') : x
}

export function priceWords(t: Pick<TemplateListing, 'pricing_model' | 'price' | 'price_currency'>): string {
  if (t.pricing_model === 'free') return 'Free'
  return `${t.price} ${t.price_currency}`.trim()
}

/** The query the list route takes (contract §D: kind, from, to, pricing, q, sort): only what is set is sent. */
export function listQuery(f: Filters): Record<string, string> {
  const q: Record<string, string> = { kind: 'migration' }
  if (f.from) q.from = f.from
  if (f.to) q.to = f.to
  if (f.price === 'free') q.pricing = 'free'
  if (f.price === 'paid') q.pricing = 'purchase'
  if (f.q.trim()) q.q = f.q.trim()
  q.sort = f.sort
  return q
}

/** The same filters on a list already in hand (a registry that answers with everything, the gallery's own narrowing). */
export function matchesFilters(t: TemplateListing, f: Filters): boolean {
  if (f.from && t.from_kind !== f.from) return false
  if (f.to && t.to_kind !== f.to) return false
  if (f.price === 'free' && t.pricing_model !== 'free') return false
  if (f.price === 'paid' && t.pricing_model === 'free') return false
  const q = f.q.trim().toLowerCase()
  if (q && !`${t.title} ${t.summary} ${t.slug}`.toLowerCase().includes(q)) return false
  return true
}

const SECRET_NAME = /(secret|password|passwd|token|api_?key|private|credential)/i

/** "Try it free": install the engine, the kit, a dry run on its sample data (none of the three needs an account or a system), then a dry run on their own system, read-only.
 *  A parameter that holds a secret is offered only as an environment reference. */
export function tryItFree(o: { ref: string; registry: string; parameters: string[] }): string[] {
  const secrets = o.parameters.filter((p) => SECRET_NAME.test(p)).map((p) => `--set ${p}=env:${p}`)
  return [
    'pip install "theprotocol-sdk[proxy]"',
    `tp-proxy migrate get ${o.ref}${o.registry ? ` --registry ${o.registry}` : ''} --out ${o.ref}`,
    `tp-proxy migrate dry-run ${o.ref} --sample`,
    `tp-proxy migrate dry-run ${o.ref}${secrets.length ? ' ' + secrets.join(' ') : ''}`,
  ]
}

/** "Write your own": scaffold, check, publish (publish asks for an identity; the first two ask for none). */
export function writeYourOwn(): string[] {
  return [
    'tp-proxy migrate new my-migration --from sql --to sql',
    'tp-proxy migrate check my-migration',
    'tp-proxy migrate publish my-migration --visibility public',
  ]
}

export function readmeHtml(text: string): string {
  return renderMarkdown(String(text ?? ''))
}

const str = (v: unknown, d = ''): string => (typeof v === 'string' ? v : v == null ? d : String(v))
const num = (v: unknown, d = 0): number => (typeof v === 'number' && Number.isFinite(v) ? v : d)
const strs = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x) => typeof x === 'string') as string[] : [])

export function normalizeListing(raw: any): TemplateListing {
  const r = raw && typeof raw === 'object' ? raw : {}
  const c = r.counts && typeof r.counts === 'object' ? r.counts : {}
  return {
    id: str(r.id), slug: str(r.slug), title: str(r.title), summary: str(r.summary), kind: str(r.kind, 'migration'),
    from_kind: str(r.from_kind), to_kind: str(r.to_kind), owner_agent_did: str(r.owner_agent_did), visibility: str(r.visibility, 'public'),
    pricing_model: str(r.pricing_model, 'free'), price: decimalWords(str(r.price, '0')), price_currency: str(r.price_currency),
    fork_share_bps: num(r.fork_share_bps), forked_from_template_id: r.forked_from_template_id ? str(r.forked_from_template_id) : null,
    current_version: num(r.current_version ?? r.version),
    // M4 nests them: counts {kit_downloads, instantiations, certified, forks}; a flat answer is read too
    uses: num(c.kit_downloads ?? r.uses), used_by: num(c.instantiations ?? r.used_by), certified: num(c.certified ?? r.certified), forks: num(c.forks ?? r.forks),
  }
}

export function normalizeDetail(raw: any): TemplateDetail {
  const r = raw && typeof raw === 'object' ? raw : {}
  const s = r.structure && typeof r.structure === 'object' ? r.structure : {}
  const side = (v: any) => (v && typeof v === 'object' ? v : {})
  const from = side(s.from), to = side(s.to)
  // the mappings and the fields each one reconciles; an older answer's connector_kinds / field_counts are read too
  const fc: Record<string, number> = {}
  for (const x of Array.isArray(s.reconcile) ? s.reconcile : []) if (x && typeof x.mapping === 'string') fc[x.mapping] = num(x.fields)
  for (const [k, v] of Object.entries(s.field_counts && typeof s.field_counts === 'object' ? s.field_counts : {})) fc[k] = num(v)
  const old = s.connector_kinds && typeof s.connector_kinds === 'object' ? s.connector_kinds : {}
  // the files of a paid template are never part of this answer: only the version route carries them, and only to a reader
  return {
    listing: normalizeListing(r.template && typeof r.template === 'object' ? r.template : r),
    versions: (Array.isArray(r.versions) ? r.versions : []).map((v: any) => ({
      version: num(v?.version), content_hash: str(v?.content_hash), published_at: str(v?.published_at), changelog: str(v?.changelog),
    })),
    structure: {
      steps: (Array.isArray(s.steps) ? s.steps : []).map((x: any) => ({
        key: str(x?.key), role: str(x?.role), acceptance: str(x?.acceptance), budget_share: typeof x?.budget_share === 'number' ? x.budget_share : null,
      })),
      parameter_names: strs(s.parameters ?? s.parameter_names),
      secret_parameters: strs(s.secret_parameters),
      connector_kinds: { from: from.kind ? [str(from.kind)] : strs(old.from), to: to.kind ? [str(to.kind)] : strs(old.to) },
      field_counts: fc,
      what: { from: str(from.what), to: str(to.what) },
      samples: num(s.samples), cutover_steps: num(s.cutover_steps), rollback: str(s.rollback),
    },
  }
}
