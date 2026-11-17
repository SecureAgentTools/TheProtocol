// V0664 C4 — the pure half of "My templates" and "My migrations" (order gwo_85a6015257385f6bb010682e). Nothing here fetches or
// touches the DOM. The shapes are the contract's: GET /workflow-templates/mine (order gwo_ef4d9981fcbba89cb8e5378b: each template with
// its visibility, pricing, fork share, versions, the listing's counts and its buyers), the workflow list's `template` block
// ({id, version, content_hash, title}, null for a workflow made by hand) and the certificates the TEG lists
// (attestation_type "migration.certificate"). A reader that cannot find a field says so on the page: it never invents one.
import { decimalWords } from '@/services/migrate/templates'

type Json = any

export interface MyVersion { version: number; published: boolean; content_hash: string; changelog: string; published_at: string }
export interface Buyer { agent_did: string; at: string; name: string }
export interface MyTemplate {
  id: string
  slug: string
  title: string
  summary: string
  visibility: string
  pricing_model: string
  price: string
  price_currency: string
  fork_share_bps: number
  versions: MyVersion[]
  uses: number
  used_by: number
  certified: number
  forks: number
  buyers: number
  /** the owner's own read: each buyer's agent and when (nothing else about a buyer) */
  buyer_rows: Buyer[]
}
export interface TemplateRef { id: string; version: number | null; content_hash: string | null; title: string | null }
export interface MyRun { id: string; title: string; status: string; total_budget: string; currency: string; created_at: string; template: TemplateRef | null }
export interface Certificate { id: string; target: string; type: string; claim: Json; record: string; raw: Json }

const num = (v: Json): number => { const n = Number(v); return Number.isFinite(n) ? n : 0 }
const str = (v: Json): string => (v === null || v === undefined ? '' : String(v))
const isObj = (v: Json): boolean => !!v && typeof v === 'object' && !Array.isArray(v)

export function normalizeVersion(raw: Json): MyVersion {
  const published = typeof raw?.published === 'boolean' ? raw.published
    : raw?.status !== undefined ? raw.status === 'published'
      : !!raw?.published_at
  return { version: num(raw?.version ?? raw?.number), published, content_hash: str(raw?.content_hash), changelog: str(raw?.changelog), published_at: str(raw?.published_at) }
}

export function normalizeMine(raw: Json): MyTemplate {
  const counts = isObj(raw?.counts) ? raw.counts : {}
  const b = raw?.buyers
  const rows: Buyer[] = (Array.isArray(b) ? b : Array.isArray(b?.list) ? b.list : Array.isArray(b?.items) ? b.items : [])
    .filter((x: Json) => isObj(x) && (x.agent_did || x.did))
    .map((x: Json) => ({ agent_did: str(x.agent_did ?? x.did), at: str(x.at ?? x.purchased_at ?? x.created_at), name: str(x.agent_name ?? x.name) }))
  const buyers = typeof b === 'number' ? b : num(b?.count ?? counts.buyers ?? raw?.buyer_count ?? rows.length)
  const versions: MyVersion[] = (Array.isArray(raw?.versions) ? raw.versions : []).map(normalizeVersion).sort((a: MyVersion, c: MyVersion) => c.version - a.version)
  return {
    id: str(raw?.id ?? raw?.template_id), slug: str(raw?.slug), title: str(raw?.title), summary: str(raw?.summary),
    visibility: str(raw?.visibility) || 'private', pricing_model: str(raw?.pricing_model) || 'free',
    price: str(raw?.price) || '0', price_currency: str(raw?.price_currency),
    fork_share_bps: num(raw?.fork_share_bps), versions,
    uses: num(counts.kit_downloads ?? raw?.uses), used_by: num(counts.instantiations ?? raw?.used_by),
    certified: num(counts.certified ?? raw?.certified), forks: num(counts.forks ?? raw?.forks),
    buyers, buyer_rows: rows,
  }
}

export function normalizeMineList(data: Json): MyTemplate[] {
  const rows = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : Array.isArray(data?.templates) ? data.templates : []
  return rows.map(normalizeMine).filter((t: MyTemplate) => t.id)
}

/** draft = no published version yet. A template with some published versions and a newer draft is "published" with a draft on top. */
export function stateOf(t: MyTemplate): 'draft' | 'published' | 'unlisted' {
  if (!t.versions.some((v) => v.published)) return 'draft'
  return t.visibility === 'public' ? 'published' : 'unlisted'
}
export const hasNewerDraft = (t: MyTemplate): boolean => {
  const pub = Math.max(0, ...t.versions.filter((v) => v.published).map((v) => v.version))
  return t.versions.some((v) => !v.published && v.version > pub) && pub > 0
}

/** The share a fork pays the original author, in the console's words: a share, never a rate of return. */
export function shareWords(bps: number): string {
  if (!bps) return 'No share for the original author'
  const pct = decimalWords((bps / 100).toFixed(2))
  return `A share of ${pct}% for the original author`
}

export function normalizeRun(raw: Json): MyRun {
  const t = raw?.template
  const template: TemplateRef | null = isObj(t) && t.id
    ? { id: str(t.id), version: t.version === null || t.version === undefined ? null : num(t.version), content_hash: t.content_hash ? str(t.content_hash) : null, title: t.title ? str(t.title) : null }
    : null
  return { id: str(raw?.id), title: str(raw?.title), status: str(raw?.status), total_budget: str(raw?.total_budget), currency: str(raw?.currency), created_at: str(raw?.created_at), template }
}
export function normalizeRuns(data: Json): MyRun[] {
  const rows = Array.isArray(data) ? data : Array.isArray(data?.workflows) ? data.workflows : Array.isArray(data?.items) ? data.items : []
  return rows.map(normalizeRun).filter((r: MyRun) => r.id)
}
/** Only the workflows that were made from a template are migrations: one made by hand is the Workflows page's. */
export const migrationsOnly = (runs: MyRun[]): MyRun[] => runs.filter((r) => r.template)

export function normalizeCertificates(data: Json): Certificate[] {
  const rows = Array.isArray(data) ? data : Array.isArray(data?.items) ? data.items : Array.isArray(data?.attestations) ? data.attestations : []
  return rows.filter((a: Json) => isObj(a) && a.attestation_type === 'migration.certificate' && isObj(a.attestation_data?.claim))
    .map((a: Json) => ({ id: str(a.attestation_id ?? a.id), target: str(a.target_agent_did), type: 'migration.certificate', claim: a.attestation_data.claim, record: str(a.attestation_data.record), raw: a }))
}

/** The certificates whose claim names this template: by the content hash of a version (exact), else by the name (slug). */
export function certificatesFor(certs: Certificate[], t: { slug?: string; content_hash?: string | null; versions?: { content_hash: string }[] }): Certificate[] {
  const hashes = new Set([...(t.versions || []).map((v) => v.content_hash), t.content_hash || ''].filter(Boolean))
  return certs.filter((c) => {
    const ct = c.claim?.template
    if (!isObj(ct)) return false
    if (ct.content_hash && hashes.has(String(ct.content_hash))) return true
    return !hashes.size && !!t.slug && ct.name === t.slug
  })
}

/** "certified by N developers": the distinct agents that hold a certificate for the template (the library's own count when it has one). */
export function certifiedBy(n: number): string {
  return n === 1 ? 'certified by 1 developer' : `certified by ${n} developers`
}

/** One line for a certificate's claim: what it says moved, and what it says of the reconcile. */
export function claimWords(c: Certificate): string {
  const k = c.claim || {}
  const verdict = k.verdict === 'pass' ? 'reconcile passed' : k.verdict ? `reconcile ${k.verdict}` : 'no reconcile verdict'
  return `${num(k.moved)} rows moved, ${num(k.rejected)} rejected, ${verdict}`
}
