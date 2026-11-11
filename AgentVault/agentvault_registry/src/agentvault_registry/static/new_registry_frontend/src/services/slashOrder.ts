/**
 * V0658 (k): the slash order, as the console edits it.
 *
 * Every slash on a registry drains one configured order (the enforcement policy's `slash_waterfall` section; the
 * registry: services/slash_order.py): the agent's bond, its locked units, its liquid units, each capped at a share of
 * the requested amount (`max_percent`), and a fourth step, the cascade, that drains the same developer's other agents
 * on the registry (off unless the order lists it, and always last). This module turns the section's value into the rows
 * the admin view edits and back, and says what the registry would refuse, with the registry's own rules
 * (crud_enforcement.validate_policy_json): each source once, max_percent 0..100, the cascade last, at least one of the
 * agent's own steps on.
 */

export type SlashSource = 'bond' | 'stake' | 'liquid' | 'cascade'

/** A step as the registry stores it. */
export interface SlashStep {
  source: SlashSource
  max_percent?: number
  enabled?: boolean
}

/** A row the admin view edits. */
export interface SlashRow {
  source: SlashSource
  maxPercent: number
  enabled: boolean
}

export const OWN_SOURCES: SlashSource[] = ['bond', 'stake', 'liquid']
export const CASCADE: SlashSource = 'cascade'
/** The factory order, as the registry ships it (crud_enforcement.DEFAULT_POLICY_JSON["slash_waterfall"]). */
export const FACTORY_ORDER: SlashStep[] = [
  { source: 'bond', max_percent: 100 },
  { source: 'stake', max_percent: 100 },
  { source: 'liquid', max_percent: 100 },
]

function isSource(s: unknown): s is SlashSource {
  return s === 'bond' || s === 'stake' || s === 'liquid' || s === 'cascade'
}

function percent(v: unknown): number {
  const n = typeof v === 'number' ? v : Number(v)
  if (!Number.isFinite(n)) return 100
  return Math.min(100, Math.max(0, n))
}

/** The rows for an order: its own steps in the order it lists them (a step it does not list is shown off, after them),
 *  then the cascade, on only when the order lists it switched on. An unreadable value is the factory order. */
export function toRows(value: unknown): SlashRow[] {
  const steps = Array.isArray(value) && value.length ? value : FACTORY_ORDER
  const rows: SlashRow[] = []
  let cascade: SlashRow = { source: CASCADE, maxPercent: 100, enabled: false }
  for (const raw of steps as unknown[]) {
    const step = (raw && typeof raw === 'object') ? raw as Record<string, unknown> : {}
    const source = step.source
    if (!isSource(source)) continue
    const row: SlashRow = { source, maxPercent: percent(step.max_percent ?? 100), enabled: step.enabled !== false }
    if (source === CASCADE) cascade = row
    else if (!rows.some((r) => r.source === source)) rows.push(row)
  }
  for (const source of OWN_SOURCES) {
    if (!rows.some((r) => r.source === source)) rows.push({ source, maxPercent: 100, enabled: false })
  }
  return [...rows, cascade]
}

/** The order to save: every own step in its place (`enabled: false` kept for one switched off), and the cascade only
 *  while it is on (off, it is left out, as in the factory order). */
export function toOrder(rows: SlashRow[]): SlashStep[] {
  const out: SlashStep[] = []
  for (const r of rows) {
    if (r.source === CASCADE) continue
    const step: SlashStep = { source: r.source, max_percent: percent(r.maxPercent) }
    if (!r.enabled) step.enabled = false
    out.push(step)
  }
  const cascade = rows.find((r) => r.source === CASCADE)
  if (cascade?.enabled) out.push({ source: CASCADE, max_percent: percent(cascade.maxPercent) })
  return out
}

export type SlashOrderProblem = 'noOwnStep' | 'percent'

/** What the registry would refuse in these rows. */
export function problems(rows: SlashRow[]): SlashOrderProblem[] {
  const out: SlashOrderProblem[] = []
  if (!rows.some((r) => r.source !== CASCADE && r.enabled)) out.push('noOwnStep')
  if (rows.some((r) => !Number.isFinite(r.maxPercent) || r.maxPercent < 0 || r.maxPercent > 100)) out.push('percent')
  return out
}

/** Move an own step up (-1) or down (+1); the cascade stays last. */
export function move(rows: SlashRow[], index: number, dir: -1 | 1): SlashRow[] {
  const next = rows.map((r) => ({ ...r }))
  const to = index + dir
  const ownCount = next.filter((r) => r.source !== CASCADE).length
  if (index < 0 || index >= ownCount || to < 0 || to >= ownCount) return next
  ;[next[index], next[to]] = [next[to], next[index]]
  return next
}

/** True when two row lists save the same order. */
export function sameOrder(a: SlashRow[], b: SlashRow[]): boolean {
  return JSON.stringify(toOrder(a)) === JSON.stringify(toOrder(b))
}
