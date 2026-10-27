// The Emission policy page's rules, kept pure so a unit test can hold them (agentvault2-69, 2026-10-25). Each cell
// says what one side does with an event type in words and in a tone; colour is never the only signal.
import type { EffectivePolicy, FindingCode, MatrixRow } from './api/emissionPolicy'

export type Tone = 'ok' | 'warn' | 'bad' | 'off' | 'info'
/** a cell: its tone, the i18n key of its word (emissionPolicy.cell.<key>) and the English */
export interface Cell { tone: Tone; key: string; word: string }
export type Severity = 'bad' | 'warn' | 'note' | 'clean'

/** bad: an event is lost or could be counted twice; warn: a gap the next check or mode change turns into a loss;
 *  note: a row nothing here emits (an agent's own events, a retired feature, a test row). */
export const FINDING_SEVERITY: Record<FindingCode, Severity> = {
  'registry-emits-refused': 'bad',
  'teg-emits-refused': 'bad',
  'both-may-emit': 'bad',
  'balance-type-skipped': 'bad',
  'emitted-without-row': 'warn',
  'in-store-without-row': 'warn',
  'shadow-would-refuse': 'warn',
  'row-without-emitter': 'note',
}
const RANK: Record<Severity, number> = { bad: 3, warn: 2, note: 1, clean: 0 }

/** the English the page shows for a finding when the read does not carry its sentence */
export const FINDING_FALLBACK: Record<FindingCode, string> = {
  'emitted-without-row': "emitted by this code, no row: the registry's gate decides by its mode, the TEG refuses it",
  'registry-emits-refused': "the registry emits it, its gate refuses it, and the TEG does not record it: the event is lost",
  'teg-emits-refused': "the TEG emits it, its gate refuses it, and the registry does not record it: the event is lost",
  'both-may-emit': "the row lets both the registry and the TEG emit it: one event could be recorded twice",
  'balance-type-skipped': "a balance-moving type the projection is told to skip: the event store refuses such writes",
  'row-without-emitter': "a row no code here emits (an agent's own events, a retired feature, or a test row)",
  'in-store-without-row': "in this frame's store with no row: the event store logs it as an unknown type",
  'shadow-would-refuse': "the registry's shadow mode counted emits that enforce would refuse",
}

export function severity(r: MatrixRow): Severity {
  let worst: Severity = 'clean'
  for (const f of r.findings) {
    const s = FINDING_SEVERITY[f] ?? 'warn'   // a code this page does not know yet is never read as clean
    if (RANK[s] > RANK[worst]) worst = s
  }
  return worst
}

const emits = (r: MatrixRow, side: 'registry' | 'teg') => r.emitted_by.includes(side)

/** The registry's gate: the tone and the words. A refusal of what the registry itself emits is a loss. */
export function registryCell(r: MatrixRow): Cell {
  if (r.findings.includes('registry-emits-refused')) return { tone: 'bad', key: 'lost', word: 'refused: lost' }
  switch (r.registry) {
    case 'allow': return { tone: 'ok', key: 'mayEmit', word: 'may emit' }
    case 'refuse': return { tone: 'off', key: 'refused', word: 'refused' }
    case 'no-row-allowed': return { tone: 'warn', key: 'noRowAllowed', word: 'no row: allowed' }
    case 'no-row-shadow': return { tone: 'warn', key: 'noRowCounted', word: 'no row: counted' }
    case 'no-row-refused': return { tone: emits(r, 'registry') ? 'bad' : 'off', key: 'noRowRefused', word: 'no row: refused' }
    default: return { tone: 'warn', key: 'unknown', word: String(r.registry) }
  }
}

/** The TEG's gate (fails closed). A refusal only matters where the TEG emits the type. */
export function tegCell(r: MatrixRow): Cell {
  if (r.findings.includes('teg-emits-refused')) return { tone: 'bad', key: 'lost', word: 'refused: lost' }
  switch (r.teg) {
    case 'allow': return { tone: 'ok', key: 'mayEmit', word: 'may emit' }
    case 'always-allowed': return { tone: 'ok', key: 'alwaysAllowed', word: 'always allowed' }
    case 'refuse': return { tone: 'off', key: 'refused', word: 'refused' }
    case 'no-row-refused': return { tone: emits(r, 'teg') ? 'bad' : 'off', key: 'noRowRefused', word: 'no row: refused' }
    default: return { tone: 'warn', key: 'unknown', word: String(r.teg) }
  }
}

export function projectionCell(r: MatrixRow): Cell {
  if (r.findings.includes('balance-type-skipped')) return { tone: 'bad', key: 'skippedBalance', word: 'skipped: a balance type' }
  if (r.projection === 'balance') return { tone: 'info', key: 'movesBalances', word: 'moves balances' }
  if (r.projection === 'skipped') return { tone: 'off', key: 'skipped', word: 'skipped' }
  return { tone: 'off', key: 'notCounted', word: 'not counted' }
}

/** A count the page shows, or the words for a count it could not read. Null is never 0. */
export function countText(n: number | null | undefined, locale: string): string {
  if (n === null || n === undefined) return 'not read'
  return new Intl.NumberFormat(locale).format(n)
}

/** A bar's width for a count, on a log scale against the largest count (0 for none, null for not read). */
export function barPercent(n: number | null | undefined, max: number): number | null {
  if (n === null || n === undefined) return null
  if (n <= 0 || max <= 0) return 0
  return Math.max(2, Math.round((Math.log10(n + 1) / Math.log10(max + 1)) * 100))
}

export type EmitterFilter = 'any' | 'registry' | 'teg' | 'both' | 'none'
export interface RowFilter { finding: FindingCode | 'any' | 'balance'; query: string; emitter: EmitterFilter }

export function matches(r: MatrixRow, f: RowFilter): boolean {
  if (f.finding === 'balance' ? !r.balance_moving : f.finding !== 'any' && !r.findings.includes(f.finding)) return false
  const reg = emits(r, 'registry'), teg = emits(r, 'teg')
  if (f.emitter === 'registry' && !reg) return false
  if (f.emitter === 'teg' && !teg) return false
  if (f.emitter === 'both' && !(reg && teg)) return false
  if (f.emitter === 'none' && (reg || teg)) return false
  const q = f.query.trim().toLowerCase()
  if (q && !r.event_type.toLowerCase().includes(q) && !(r.row?.description || '').toLowerCase().includes(q)) return false
  return true
}

/** Worst first, then the balance-moving types, then the busiest in this store, then by name. */
export function ordered(rows: MatrixRow[]): MatrixRow[] {
  return [...rows].sort((a, b) =>
    RANK[severity(b)] - RANK[severity(a)]
    || Number(b.balance_moving) - Number(a.balance_moving)
    || (b.store_count ?? -1) - (a.store_count ?? -1)
    || a.event_type.localeCompare(b.event_type))
}

/** How many types sit at each severity (for the strip at the top). */
export function severityCounts(rows: MatrixRow[]): Record<Severity, number> {
  const out: Record<Severity, number> = { bad: 0, warn: 0, note: 0, clean: 0 }
  for (const r of rows) out[severity(r)]++
  return out
}

/** The finding codes present, in the order the page lists them (worst first, then most frequent). */
export function findingCodes(view: EffectivePolicy): FindingCode[] {
  const counts = view.summary?.findings || {}
  return (Object.keys(counts) as FindingCode[])
    .filter((c) => (counts[c] || 0) > 0)
    .sort((a, b) => RANK[FINDING_SEVERITY[b] ?? 'warn'] - RANK[FINDING_SEVERITY[a] ?? 'warn'] || (counts[b] || 0) - (counts[a] || 0))
}
