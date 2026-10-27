/**
 * §ACTIVITY (2026-08-20) — who has actually DONE something lately.
 *
 * His ask: "show only active agents in the last 10-15 minutes or set a
 * timeframe yourself, so the inactive agents disappear and reappear based on
 * activity."
 *
 * Fed from the live event stream the bridge already consumes, so this needs no
 * endpoint and no history API. That has one honest consequence which the UI
 * must state rather than hide: THIS ONLY KNOWS WHAT THIS SESSION HAS SEEN. A
 * page opened one minute ago cannot answer "active in the last 15 minutes", and
 * pretending otherwise would turn absence-of-observation into absence-of-
 * activity — the same lie the pulse bar exists to avoid.
 *
 * Pure and total: no Vue, no clock of its own (callers pass `now`), so it can
 * be driven at speed in a test instead of waited on.
 */

/** did -> epoch ms of the last event that named it. */
export interface ActivityIndex {
  seen: Map<string, number>
  /** When observation began, so the window can say what it can actually cover. */
  since: number
}

export function createActivityIndex(now: number): ActivityIndex {
  return { seen: new Map(), since: now }
}

/** Hard cap so a long session cannot grow this without bound. */
export const ACTIVITY_MAX_DIDS = 20000

/** Record that these DIDs were named by an event at `now`. */
export function noteActivity(ix: ActivityIndex, dids: Iterable<string>, now: number): void {
  for (const d of dids) {
    if (!d) continue
    ix.seen.set(d, now)
  }
  if (ix.seen.size > ACTIVITY_MAX_DIDS) {
    // Drop the oldest by timestamp, not by insertion order: a DID that keeps
    // acting must survive, and Map order is insertion, not recency.
    const rows = [...ix.seen.entries()].sort((a, b) => a[1] - b[1])
    for (let i = 0; i < rows.length - ACTIVITY_MAX_DIDS; i++) ix.seen.delete(rows[i][0])
  }
}

/** DIDs seen within `windowMs` of `now`. */
export function activeDids(ix: ActivityIndex, windowMs: number, now: number): Set<string> {
  const cut = now - windowMs
  const out = new Set<string>()
  for (const [d, t] of ix.seen) if (t >= cut) out.add(d)
  return out
}

/**
 * How much of the requested window this index can actually vouch for.
 * `covered` is the observed span; `full` says whether it reaches the whole
 * window. The UI uses this to avoid claiming a 15-minute answer 2 minutes in.
 */
export function coverage(ix: ActivityIndex, windowMs: number, now: number):
  { coveredMs: number; full: boolean } {
  const coveredMs = Math.max(0, now - ix.since)
  return { coveredMs, full: coveredMs >= windowMs }
}

/** Windows offered in the UI. `null` = the mode is off. */
export const ACTIVITY_WINDOWS: ReadonlyArray<{ label: string; ms: number }> = Object.freeze([
  { label: '5m', ms: 5 * 60_000 },
  { label: '15m', ms: 15 * 60_000 },
  { label: '1h', ms: 60 * 60_000 },
])

/** Clamp a hand-typed minute value to something sane. */
export function windowFromMinutes(min: number): number | null {
  if (!Number.isFinite(min) || min <= 0) return null
  return Math.min(24 * 60, Math.max(1, Math.floor(min))) * 60_000
}

/** Human sentence for what the filter is currently claiming. */
export function activityNote(
  ix: ActivityIndex, windowMs: number, now: number, shown: number, total: number,
): string {
  const { coveredMs, full } = coverage(ix, windowMs, now)
  const mins = Math.round(windowMs / 60_000)
  const covMin = Math.floor(coveredMs / 60_000)
  const base = `${shown} of ${total} active in the last ${mins}m`
  return full
    ? base
    : `${base} — watching ${covMin < 1 ? 'under a minute' : covMin + 'm'} so far, so this cannot see the whole window yet`
}
