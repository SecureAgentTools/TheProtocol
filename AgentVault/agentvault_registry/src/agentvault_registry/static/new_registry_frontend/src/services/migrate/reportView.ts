// V0664 C4 (order gwo_85a6015257385f6bb010682e): what the report page shows, as plain data. Counts, names and hashes only: a report never holds
// a record's value (reports.py), and nothing here sends anything anywhere.
import { REPORT_SCHEMA, classify, hashHolds } from './reportCheck'

type Json = any
export const STEP_ORDER = ['inventory', 'dry_run', 'load', 'reconcile'] as const
export const STEP_WORDS: Record<string, string> = { inventory: 'Inventory', dry_run: 'Dry run', load: 'Load', reconcile: 'Reconcile' }
export const MAX_FILE_BYTES = 5 * 1024 * 1024

export type Tone = 'ok' | 'bad' | 'warn'
export function verdictWords(v: unknown): { label: string; tone: Tone } {
  if (v === 'pass') return { label: 'Passed', tone: 'ok' }
  if (v === 'fail') return { label: 'Failed', tone: 'bad' }
  if (v === 'not_measured' || v === undefined || v === null || v === '') return { label: 'Not measured', tone: 'warn' }
  return { label: String(v), tone: 'warn' }
}

export interface ReasonRow { reason: string; n: number; pct: number }
/** A mapping's rejected rows by reason, the most frequent first, each with its share of the rejected rows. */
export function reasonRows(m: Json): ReasonRow[] {
  const by: Record<string, number> = m && typeof m.rejected_by_reason === 'object' && m.rejected_by_reason ? m.rejected_by_reason : {}
  const total = Object.values(by).reduce((a: number, n: any) => a + (Number(n) || 0), 0)
  return Object.entries(by)
    .map(([reason, n]) => ({ reason, n: Number(n) || 0, pct: total ? Math.round(((Number(n) || 0) / total) * 100) : 0 }))
    .sort((a, b) => b.n - a.n || (a.reason < b.reason ? -1 : a.reason > b.reason ? 1 : 0))
}

export interface FillRow { field: string; filled: number; null: number; pct: number }
/** The fill per target field: how many rows filled it, how many left it null, the filled share. */
export function fillRows(m: Json): FillRow[] {
  const f: Record<string, Json> = m && typeof m.fields === 'object' && m.fields ? m.fields : {}
  return Object.keys(f).sort().map((field) => {
    const filled = Number(f[field]?.filled) || 0
    const nul = Number(f[field]?.null) || 0
    return { field, filled, null: nul, pct: filled + nul ? Math.round((filled / (filled + nul)) * 100) : 0 }
  })
}

export type Item =
  | { kind: 'report'; name: string; doc: Json; holds: boolean }
  | { kind: 'certificate'; name: string; doc: Json }
  | { kind: 'error'; name: string; error: string }

/** Read each dropped or pasted text: a report (its hash recomputed here), a certificate, or the reason it is neither. */
export async function readTexts(files: Array<{ name: string; text: string }>): Promise<Item[]> {
  const out: Item[] = []
  for (const f of files) {
    if (f.text.length > MAX_FILE_BYTES) { out.push({ kind: 'error', name: f.name, error: 'This file is too large to be a report (over 5 MB).' }); continue }
    let doc: Json
    try { doc = JSON.parse(f.text) } catch { out.push({ kind: 'error', name: f.name, error: 'This is not JSON, so it is not a migration report or certificate.' }); continue }
    const kind = classify(doc)
    if (kind === 'report') out.push({ kind, name: f.name, doc, holds: await hashHolds(doc) })
    else if (kind === 'certificate') out.push({ kind, name: f.name, doc })
    else out.push({ kind: 'error', name: f.name, error: `This is not a migration report or certificate (a report has schema ${REPORT_SCHEMA}; a certificate is a migration.certificate attestation).` })
  }
  return out
}

/** Certificates first, then the reports in the order of the steps (then by when they finished), then what could not be read. */
export function sortItems(items: Item[]): Item[] {
  const rank = (i: Item) => (i.kind === 'certificate' ? 0 : i.kind === 'report' ? 1 : 2)
  const step = (i: Item) => (i.kind === 'report' ? Math.max(0, STEP_ORDER.indexOf(i.doc.step)) : 0)
  return [...items].sort((a, b) => rank(a) - rank(b) || step(a) - step(b)
    || (a.kind === 'report' && b.kind === 'report' ? String(a.doc.finished_at).localeCompare(String(b.doc.finished_at)) : 0))
}
