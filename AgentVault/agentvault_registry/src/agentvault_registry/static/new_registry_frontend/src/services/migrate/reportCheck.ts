// V0664 C4 (order gwo_85a6015257385f6bb010682e): the report viewer's logic. Nothing here talks to a server: a report or a certificate a person
// drops on the page is read and checked in the browser (WebCrypto sha256 over canonical JSON).
//
// The formulas are the SDK's (theprotocol.proxy.migrate): a report's report_sha256 is the sha256 of the canonical JSON of the report without
// that field (reports.seal / hash_holds); canonical JSON is json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False) in UTF-8
// (schema.canonical); a certificate is an attestation whose data holds a claim {template, reports {step: report_sha256}, verdict, moved,
// rejected, finished_at} and a record key "tpm-" + sha256(canonical(claim))[:40] (commands.cmd_certify). The vectors are Python's own.
import { canonicalJson } from '@/services/proxy/mapping'

export const REPORT_SCHEMA = 'theprotocol.migration.report/v1'
const STEPS = ['inventory', 'dry_run', 'load', 'reconcile'] as const
type Json = any

export function canonicalBytes(doc: Json): Uint8Array { return new TextEncoder().encode(canonicalJson(doc)) }

export async function sha256Hex(bytes: Uint8Array): Promise<string> {
  const d = await crypto.subtle.digest('SHA-256', bytes as unknown as ArrayBuffer)
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, '0')).join('')
}

/** The hash a report's own report_sha256 should hold: of the report without that field. */
export async function reportHash(report: Json): Promise<string> {
  const body: Record<string, Json> = {}
  for (const [k, v] of Object.entries(report || {})) if (k !== 'report_sha256') body[k] = v
  return sha256Hex(canonicalBytes(body))
}
export async function hashHolds(report: Json): Promise<boolean> {
  return typeof report?.report_sha256 === 'string' && report.report_sha256 === await reportHash(report)
}
export async function claimHash(claim: Json): Promise<string> { return sha256Hex(canonicalBytes(claim)) }

const isObj = (v: Json) => v !== null && typeof v === 'object' && !Array.isArray(v)
export function classify(doc: Json): 'report' | 'certificate' | 'unknown' {
  if (!isObj(doc)) return 'unknown'
  if (doc.schema === REPORT_SCHEMA && typeof doc.step === 'string') return 'report'
  if (doc.attestation_type === 'migration.certificate' && isObj(doc.attestation_data) && isObj(doc.attestation_data.claim)) return 'certificate'
  return 'unknown'
}

export type CheckState = 'ok' | 'bad' | 'unknown'
export interface Check { key: string; state: CheckState; detail: string }
export interface CertificateCheck { claimSha256: string; checks: Check[] }

const grp = (n: unknown): string => (Number.isFinite(Number(n)) ? new Intl.NumberFormat('en-US').format(Number(n)) : String(n))
const sum = (o: Json, field: string) => Object.values(isObj(o) ? o : {}).reduce((n: number, t: Json) => n + (Number(t?.[field]) || 0), 0)

/** A certificate against the reports given with it: what holds, what does not, and what could not be checked (never failed for that). */
export async function checkCertificate(cert: Json, reports: Json[]): Promise<CertificateCheck> {
  const claim = cert?.attestation_data?.claim ?? {}
  const claimSha256 = await claimHash(claim)
  const checks: Check[] = []
  const add = (key: string, state: CheckState, detail: string) => checks.push({ key, state, detail })

  const record = String(cert?.attestation_data?.record ?? '')
  add('record', record === 'tpm-' + claimSha256.slice(0, 40) ? 'ok' : 'bad',
    record === 'tpm-' + claimSha256.slice(0, 40) ? 'The record key is the hash of the claim.' : 'The record key is not the hash of the claim: the claim was changed.')

  const byStep: Record<string, Json[]> = {}
  for (const r of reports) if (isObj(r) && typeof r.step === 'string') (byStep[r.step] ||= []).push(r)
  for (const step of STEPS) {
    const claimed = claim?.reports?.[step]
    const key = `report:${step}`
    if (!claimed) { add(key, 'unknown', `The claim names no ${step} report.`); continue }
    const given = byStep[step] || []
    if (!given.length) { add(key, 'unknown', `The ${step} report was not given: its hash ${String(claimed).slice(0, 12)} could not be checked.`); continue }
    let result: Check | null = null
    for (const g of given) {
      if (!(await hashHolds(g))) { result = { key, state: 'bad', detail: `The ${step} report's own hash does not hold: it changed after it was sealed.` }; continue }
      if (g.report_sha256 === claimed) { result = { key, state: 'ok', detail: `The ${step} report's hash matches the claim.` }; break }
      result = result ?? { key, state: 'bad', detail: `The ${step} report given is another one than the claim names (its hash differs).` }
    }
    checks.push(result!)
  }

  const given = reports.filter(isObj)
  const tpl = canonicalJson(claim?.template ?? null)
  const withTpl = given.filter((r) => r.template !== undefined)
  add('template', !withTpl.length ? 'unknown' : withTpl.every((r) => canonicalJson(r.template) === tpl) ? 'ok' : 'bad',
    !withTpl.length ? 'No report was given to compare the template with.' : withTpl.every((r) => canonicalJson(r.template) === tpl) ? 'Every report is for the template version the claim names.' : 'A report is for another version of the template than the claim names.')

  const load = (byStep.load || [])[0]
  const rec = (byStep.reconcile || [])[0]
  if (load) {
    const moved = sum(load.targets, 'written') + sum(load.targets, 'unchanged')
    add('moved', moved === Number(claim?.moved) ? 'ok' : 'bad', moved === Number(claim?.moved) ? `The load report moved ${grp(moved)} rows, as the claim says.` : `The load report moved ${grp(moved)} rows, the claim says ${grp(claim?.moved)}.`)
    const rejected = sum(load.mappings, 'rejected')
    add('rejected', rejected === Number(claim?.rejected) ? 'ok' : 'bad', rejected === Number(claim?.rejected) ? `The load report rejected ${grp(rejected)} rows, as the claim says.` : `The load report rejected ${grp(rejected)} rows, the claim says ${grp(claim?.rejected)}.`)
  } else {
    add('moved', 'unknown', 'The load report was not given: the rows moved could not be checked.')
    add('rejected', 'unknown', 'The load report was not given: the rows rejected could not be checked.')
  }
  if (load && rec) {
    const fresh = String(rec.finished_at) >= String(load.finished_at)
    add('fresh', fresh ? 'ok' : 'bad', fresh ? 'The reconcile came after the load.' : 'The reconcile is older than the load: it did not read back this load.')
  } else add('fresh', 'unknown', 'Needs both the load and the reconcile report.')
  if (rec) {
    const pass = rec.verdict === 'pass' && claim?.verdict === 'pass'
    add('verdict', pass ? 'ok' : 'bad', pass ? 'The reconcile passed, as the claim says.' : `The reconcile's verdict is ${rec.verdict}; the claim says ${claim?.verdict}.`)
  } else add('verdict', 'unknown', 'The reconcile report was not given.')
  return { claimSha256, checks }
}
