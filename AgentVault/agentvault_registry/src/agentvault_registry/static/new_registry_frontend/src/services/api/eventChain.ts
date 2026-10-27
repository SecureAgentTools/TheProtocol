// services/api/eventChain.ts — §FEDEVENTS 2026-08-03: windowed aggregate chains.
//
// The old chain rail (GET /admin/events/aggregate/{id}) is UNBOUNDED — no
// limit, no window. Production aggregates run to 1.4M events (measured on
// frame-a), which can never survive the 15s registry→ES proxy hop, so the
// "chain" drilldown timed out exactly on the aggregates worth investigating.
//
// New rail: the indexed, statement-timeout-armed ES forensics search
// (aggregate_id filter, ≤1000/page, offset paging) walked inside a bounded
// time window (ES caps a window at 31d). One fetch = one window; the caller
// steps older/newer explicitly. When the newest window is empty, we auto-walk
// back a bounded number of windows to find the latest activity instead of
// showing a bare "no events".
import type { EventStoreEvent } from './eventStoreAdmin'

export interface ChainWindow { start: string; end: string }

export interface ChainResult {
  events: EventStoreEvent[]
  window: ChainWindow
  /** True when the window itself holds more rows than maxRows. */
  truncated: boolean
  /** Windows auto-stepped back to find activity (0 = found in the requested one). */
  walkedBack: number
  error?: string
}

export interface ChainPage {
  events?: EventStoreEvent[]
  count?: number
  truncated?: boolean
  error?: string
}

/** One forensics-search page fetch, frame routing supplied by the caller. */
export type ChainPageFetcher = (params: Record<string, any>) => Promise<ChainPage>

export const CHAIN_WINDOW_DAYS = 30           // stays inside the ES 31d span cap
// 500/page, not the 1000 cap: LIMIT bounds the planner's timestamp-index scan
// through regions where the aggregate is SPARSE (measured: most pages ~300ms,
// sparse-region pages spike to ~8s at 1000 rows — brushing the ES 9s statement
// timeout). Halving the limit halves the worst-case scan.
const CHAIN_PAGE = 500
const CHAIN_PAGE_TRIES = 3                     // statement-timeout 500s are transient
const CHAIN_MAX_ROWS = 10_000                  // browser guard per window (~10MB of events)
const CHAIN_AUTO_WALK = 6                      // ≈6 months of empty-window probing

export function chainWindowFor(end: Date, days = CHAIN_WINDOW_DAYS): ChainWindow {
  const endMs = end.getTime()
  return {
    start: new Date(endMs - days * 86_400_000).toISOString(),
    end: new Date(endMs).toISOString(),
  }
}

/**
 * Fetch an aggregate's full chain inside one window (oldest-first), paging the
 * forensics search until the window is exhausted or the row guard trips.
 * `windowEnd` defaults to now; pass an older end to step back through history.
 */
export async function fetchAggregateChain(
  fetchPage: ChainPageFetcher,
  aggregateId: string,
  opts?: { windowEnd?: Date; autoWalk?: boolean },
): Promise<ChainResult> {
  let walkedBack = 0
  let window = chainWindowFor(opts?.windowEnd ?? new Date())

  for (;;) {
    const events: EventStoreEvent[] = []
    const seen = new Set<string>()
    let truncated = false
    let error: string | undefined
    // Timestamp-CURSOR paging, never deep OFFSET: each page re-anchors `start`
    // at the last row's timestamp (inclusive — boundary dupes fall to the id
    // de-dupe), so every page is a fresh indexed range scan. Deep offsets on a
    // million-event aggregate degrade page by page and hit the ES statement
    // timeout; cursors stay flat.
    let cursorStart = window.start
    for (;;) {
      // Retry transient failures (ES statement-timeout 500s on sparse-region
      // pages); a page that still fails ends the walk but KEEPS what was
      // fetched — a partial chain beats a blank error for investigation.
      let page: ChainPage | undefined
      for (let attempt = 1; attempt <= CHAIN_PAGE_TRIES; attempt++) {
        try {
          page = await fetchPage({
            aggregate_id: aggregateId,
            start: cursorStart,
            end: window.end,
            order: 'asc',
            limit: CHAIN_PAGE,
            offset: 0,
          })
        } catch (e: any) {
          page = { error: e?.response?.data?.detail || e?.message || 'page fetch failed' }
        }
        if (!page?.error) break
        if (attempt < CHAIN_PAGE_TRIES) await new Promise((r) => setTimeout(r, 500 * attempt))
      }
      if (page?.error) { error = page.error; truncated = events.length > 0; break }
      const rows = page?.events ?? []
      for (const ev of rows) {
        if (ev?.id) {
          if (seen.has(ev.id)) continue
          seen.add(ev.id)
        }
        events.push(ev)
      }
      if (rows.length < CHAIN_PAGE) break
      const lastTs = rows[rows.length - 1]?.timestamp
      // Epoch compare (JS emits `Z`, the ES emits `+00:00` — string compare is
      // format-dependent). No forward progress (pathological same-timestamp
      // page) or cursor at the window edge → stop honestly rather than loop.
      const lastMs = lastTs ? new Date(lastTs).getTime() : NaN
      if (!lastTs || !(lastMs > new Date(cursorStart).getTime()) || lastMs >= new Date(window.end).getTime()) {
        truncated = true
        break
      }
      cursorStart = lastTs
      if (events.length >= CHAIN_MAX_ROWS) { truncated = true; break }
    }

    if (events.length || error || !(opts?.autoWalk ?? true) || walkedBack >= CHAIN_AUTO_WALK) {
      return { events, window, truncated, walkedBack, error }
    }
    // Empty window — step back once more looking for the latest activity.
    walkedBack += 1
    window = chainWindowFor(new Date(new Date(window.start).getTime()))
  }
}
