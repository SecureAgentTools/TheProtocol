/**
 * §COCKPIT P5 — the ONE reducer behind the Latency and Telemetry panes.
 *
 * §12: the instrument shows its own numbers. Two panes reading the same receipts and
 * each doing their own arithmetic would eventually disagree, and the first thing a
 * reader would lose is the belief that either is right — so the arithmetic lives here,
 * once, and both panes render it.
 *
 * ⚠ EVERY leg here is measured from SERVER timestamps only (R5). `first_presented_at`
 * is client-asserted and is deliberately absent from every calculation below; it is
 * rendered elsewhere, labelled, and never averaged into an attested number.
 *
 * ⚠ `null` is not zero. A leg the server never observed — a decision that was never
 * acked, so ARRIVE has no end — is EXCLUDED from its percentile rather than counted as
 * instant. A zero there would quietly make the system look faster the more often its
 * delivery rail failed.
 */
import type { Receipt } from '@/services/api/liability'

export interface LegStat {
  key: 'arrive' | 'read' | 'consent'
  n: number
  p50: number | null
  p95: number | null
  min: number | null
  max: number | null
  /** How many receipts had this leg unobservable. Rendered, never hidden. */
  missing: number
}

export function percentile(sorted: number[], p: number): number | null {
  if (!sorted.length) return null
  // Nearest-rank. With the handful of samples a young corridor produces, interpolation
  // invents precision the sample size cannot support.
  const idx = Math.min(sorted.length - 1, Math.max(0, Math.ceil((p / 100) * sorted.length) - 1))
  return sorted[idx]
}

export function legStat(receipts: Receipt[], key: LegStat['key']): LegStat {
  const vals: number[] = []
  let missing = 0
  for (const r of receipts) {
    const v = r.legs_ms?.[key]
    if (typeof v === 'number' && Number.isFinite(v) && v >= 0) vals.push(v)
    else if (r.challenge) missing++
  }
  vals.sort((a, b) => a - b)
  return {
    key, n: vals.length, missing,
    p50: percentile(vals, 50), p95: percentile(vals, 95),
    min: vals.length ? vals[0] : null, max: vals.length ? vals[vals.length - 1] : null,
  }
}

export interface Buckets { edges: number[]; counts: number[]; overflow: number }

/** A histogram over fixed edges — fixed so two reads of the same pane are comparable,
 *  rather than re-scaling under the reader and looking like a change in the system. */
export function bucketise(values: number[], edges: number[]): Buckets {
  const counts = new Array(edges.length).fill(0)
  let overflow = 0
  for (const v of values) {
    const i = edges.findIndex(e => v <= e)
    if (i === -1) overflow++
    else counts[i]++
  }
  return { edges, counts, overflow }
}

export interface DecisionTelemetry {
  decisions: number
  approved: number
  denied: number
  refused: number
  denialRate: number | null
  /** Longest run of consecutive identical approvals in the window, by the SERVER's
   *  facts digest — never a second client-side notion of sameness. */
  longestStreak: number
  readMs: number[]
  perDay: Array<{ day: string; n: number }>
  denyReasons: Record<string, number>
}

export function telemetry(receipts: Receipt[]): DecisionTelemetry {
  const decided = receipts
    .filter(r => r.event_type === 'challenge_approved' || r.event_type === 'challenge_denied')
    .sort((a, b) => new Date(b.at).getTime() - new Date(a.at).getTime())
  const approved = decided.filter(r => r.event_type === 'challenge_approved').length
  const denied = decided.filter(r => r.event_type === 'challenge_denied').length
  const refused = receipts.filter(r => r.event_type === 'challenge_refused').length

  let longest = 0, run = 0, lastDigest: string | null = null
  for (const r of decided) {
    const d = r.challenge?.facts_digest ?? null
    if (r.event_type === 'challenge_approved' && d && d === lastDigest) run++
    else { run = r.event_type === 'challenge_approved' ? 1 : 0; lastDigest = d }
    if (run > longest) longest = run
  }

  const perDayMap = new Map<string, number>()
  for (const r of decided) {
    const day = String(r.at).slice(0, 10)
    perDayMap.set(day, (perDayMap.get(day) || 0) + 1)
  }
  const denyReasons: Record<string, number> = {}
  for (const r of decided) {
    if (r.event_type !== 'challenge_denied') continue
    const why = String(r.payload?.reason || 'user_denied')
    denyReasons[why] = (denyReasons[why] || 0) + 1
  }
  return {
    decisions: decided.length, approved, denied, refused,
    // null, not 0, when nothing has been decided: "0% denials" out of zero decisions
    // is a claim about a system nobody has used.
    denialRate: decided.length ? denied / decided.length : null,
    longestStreak: longest,
    readMs: decided.map(r => r.legs_ms?.read).filter((v): v is number => typeof v === 'number' && v >= 0),
    perDay: [...perDayMap.entries()].sort((a, b) => (a[0] < b[0] ? 1 : -1)).map(([day, n]) => ({ day, n })),
    denyReasons,
  }
}
