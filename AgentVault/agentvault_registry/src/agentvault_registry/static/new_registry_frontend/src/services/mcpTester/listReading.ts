/**
 * §MCPTEST30: how the tester page's tool list is read and narrowed (moved out of AdminMcpTester.vue so it is unit-tested):
 * the HTTP-status buckets, the lenient passes the strict mode hides, the toolbar's filters and the sweep's timing
 * statistics.
 *
 * Two readings changed in the move, each measured by its spec:
 * - the strict-pass chip counted a lenient pass as "no status or >= 400" while the strict filter hid every healthy row
 *   that was not 2xx, so a healthy 1xx/3xx row was hidden and not counted; one predicate (isLenientPass) now decides both;
 * - the p95 read the value at index floor(0.95·n), which for up to 20 timed rows is the maximum and above that one rank
 *   too high; it is the nearest-rank p95 now, the value at rank ceil(0.95·n).
 */
export type StatusBucket = '' | '2xx' | '4xx' | '401' | '403' | '404' | '5xx'
export const STATUS_BUCKETS = ['2xx', '4xx', '401', '403', '404', '5xx'] as const

/** A row at or above this is slow (the "slow only" chip). */
export const SLOW_THRESHOLD_MS = 1500

/** what the readers need of a row: a sweep's McpTesterToolRow, or anything shaped like it (fields may be missing) */
type Row = { tool: string; tier?: string | null; status?: number | null; healthy?: boolean; skipped?: boolean; elapsed?: number | null }

export function matchesStatusBucket(s: number | undefined | null, bucket: StatusBucket): boolean {
  if (!bucket) return true
  if (!s) return false
  if (bucket === '2xx') return s >= 200 && s < 300
  if (bucket === '4xx') return s >= 400 && s < 500
  if (bucket === '5xx') return s >= 500 && s < 600
  return Number(bucket) === s
}

/** A pass the predicate accepted without a 2xx: a 4xx taken as "the endpoint exists", any other non-2xx, or no status at
 *  all. The strict-pass chip counts exactly these and the strict filter hides exactly these. */
export function isLenientPass(r: Pick<Row, 'healthy' | 'skipped' | 'status'>): boolean {
  return !!r.healthy && !r.skipped && !matchesStatusBucket(r.status, '2xx')
}

/** How many rows answered in each status bucket; 401, 403 and 404 count in 4xx as well (the chips overlap by design). */
export function statusDistribution(rows: Array<Pick<Row, 'status'>>): Record<(typeof STATUS_BUCKETS)[number], number> {
  const d = { '2xx': 0, '4xx': 0, '5xx': 0, '401': 0, '403': 0, '404': 0 }
  for (const r of rows) {
    const s = r.status
    if (!s) continue
    if (s >= 200 && s < 300) d['2xx']++
    else if (s === 401) { d['401']++; d['4xx']++ }
    else if (s === 403) { d['403']++; d['4xx']++ }
    else if (s === 404) { d['404']++; d['4xx']++ }
    else if (s >= 400 && s < 500) d['4xx']++
    else if (s >= 500) d['5xx']++
  }
  return d
}

export interface ListFilter {
  text: string
  tier: string
  category: string
  onlyFailures: boolean
  onlySlow: boolean
  statusBucket: StatusBucket
  strictPass: boolean
}

/** The rows the toolbar leaves: a name containing the text (any case), the tier, the category (as the page derives it),
 *  failures only (neither healthy nor skipped), slow only, a status bucket, and in strict mode no lenient pass. */
export function filterRows<T extends Row>(rows: T[], f: ListFilter, categorize: (tool: string, tier?: string) => string): T[] {
  const ft = f.text.toLowerCase().trim()
  return rows.filter((r) => {
    if (ft && !r.tool.toLowerCase().includes(ft)) return false
    if (f.tier && r.tier !== f.tier) return false
    if (f.category && categorize(r.tool, r.tier ?? undefined) !== f.category) return false
    if (f.onlyFailures && (r.healthy || r.skipped)) return false
    if (f.onlySlow && (Number(r.elapsed) || 0) < SLOW_THRESHOLD_MS) return false
    if (f.statusBucket && !matchesStatusBucket(r.status, f.statusBucket)) return false
    if (f.strictPass && isLenientPass(r)) return false
    return true
  })
}

export interface LatencyStats<T> { median: number; p95: number; max: number; slowest: T[] }

/** The sweep's timing over the rows that carry a positive elapsed: the median (the mean of the two middle values for an
 *  even count, rounded), the nearest-rank p95, the maximum, and the slowest rows, slowest first. */
export function latencyStats<T extends Pick<Row, 'elapsed'>>(rows: T[], slowestN = 10): LatencyStats<T> {
  const sorted = rows.filter((r) => typeof r.elapsed === 'number' && r.elapsed > 0)
    .slice().sort((a, b) => (a.elapsed || 0) - (b.elapsed || 0))
  const n = sorted.length
  if (n === 0) return { median: 0, p95: 0, max: 0, slowest: [] }
  const at = (i: number) => sorted[i]?.elapsed || 0
  const mid = Math.floor(n / 2)
  const median = n % 2 === 0 ? Math.round((at(mid - 1) + at(mid)) / 2) : at(mid)
  const p95 = at(Math.min(n - 1, Math.max(0, Math.ceil(0.95 * n) - 1)))
  return { median, p95, max: at(n - 1), slowest: sorted.slice(-slowestN).reverse() }
}
