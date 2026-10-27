/**
 * §MCPTEST30 (V0549): how deep a run's passing tool rows were checked. The pass rate counts four kinds of pass alike:
 * a success against a contract a person wrote, a success under the default contract (the shape went unchecked), a
 * refusal exactly as a written contract pins it, and a refusal under the default contract (the tool reached its route and
 * nothing more was checked: §FANCLAIM's thin coverage). The run summary carries the four counts as `pass_depth`
 * (tool rows only; probes and federation rows are outside it). A run recorded before V0549 has no such key, and then
 * nothing is shown: never four zeros that read as "nothing was deep".
 */

export const PASS_DEPTH_ORDER = ['success_contract', 'success_default', 'refusal_contract', 'refusal_default'] as const
export type PassDepthKey = (typeof PASS_DEPTH_ORDER)[number]
export type PassDepth = Record<PassDepthKey, number>

export interface PassDepthReading {
  /** the passing tool rows the four kinds cover */
  total: number
  /** of those, checked against a contract a person wrote (a success or a refusal) */
  contract: number
  parts: Array<{ key: PassDepthKey; n: number }>
}

/** What each kind means, as the page says it (key + English fallback). */
export const PASS_DEPTH_TEXT: Record<PassDepthKey, { key: string; fallback: string }> = {
  success_contract: { key: 'mcpTester.depth.successContract', fallback: 'succeeded against a contract a person wrote' },
  success_default: { key: 'mcpTester.depth.successDefault', fallback: 'succeeded with no written contract: the shape went unchecked' },
  refusal_contract: { key: 'mcpTester.depth.refusalContract', fallback: 'refused exactly as a written contract pins it' },
  refusal_default: { key: 'mcpTester.depth.refusalDefault', fallback: 'refused under the default contract: it reached its route, nothing more was checked' },
}

/**
 * The depth of a run's passes, or null when the run carries none to read: no `pass_depth` (a run before V0549), a value
 * that is not four non-negative counts, or four zeros (a run with no passing tool rows, such as a federation run).
 */
export function readPassDepth(raw: unknown): PassDepthReading | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const r = raw as Record<string, unknown>
  const parts: PassDepthReading['parts'] = []
  for (const key of PASS_DEPTH_ORDER) {
    const v = r[key]
    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0) return null
    parts.push({ key, n: Math.floor(v) })
  }
  const total = parts.reduce((sum, p) => sum + p.n, 0)
  if (total === 0) return null
  const n = (k: PassDepthKey) => parts.find((p) => p.key === k)?.n ?? 0
  return { total, contract: n('success_contract') + n('refusal_contract'), parts }
}
