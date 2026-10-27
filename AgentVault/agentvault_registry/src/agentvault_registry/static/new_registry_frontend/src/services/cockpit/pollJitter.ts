/**
 * §COCKPITUP U5 (2026-09-01) — the desk's panes stop polling in lockstep.
 *
 * MEASURED BEFORE BUILDING: 19 panes each run their own `setInterval` in `onMounted` with
 * NO jitter anywhere, so every cohort fires as one burst, forever:
 *
 *     20s: 2   30s: 1   45s: 2   60s: 6  <-- worst   90s: 3   120s: 4   180s: 1
 *
 * The 60s cohort is six simultaneous requests, and two of the panes in those bursts
 * (`denials`, `book`) are grouped queries over large tables, not cheap reads. Opening a
 * saved 23-pane board therefore lands a synchronised wave on registry-a every minute for
 * as long as the tab is open.
 *
 * 🔴 THIS IS §BACKSTOPJITTER'S PHASE-LOCK, REPEATED CLIENT-SIDE. That batch fixed exactly
 * this on the server (`base × U(0.85, 1.15)` to break fleet-wide phase-lock among ~56
 * reactors per registry); the desk re-created it in the browser. Same defect, same cure.
 *
 * ⚠ THE SPREAD IS DRAWN ONCE PER PANE AT MOUNT, NOT PER TICK. A fresh random delay on
 * every tick is a different thing — it makes the interval unpredictable to the reader and
 * makes "is this pane still polling?" unanswerable. One draw per mount permanently offsets
 * a pane from its cohort, which is all that is needed.
 *
 * ⚠ THIS IS SPREAD, NOT BACKOFF. Backoff is for a failing dependency and belongs to the
 * caller; this only decides WHEN within a band a healthy poll lands. `jitterMs` never
 * returns 0 and never returns more than 1.15x, so a pane cannot silently stop polling.
 */

/** Nothing on this desk polls faster than this, jitter or not. */
export const MIN_POLL_MS = 5000

/** The proportional band, matching the server-side §BACKSTOPJITTER constant. */
export const JITTER_LO = 0.85
export const JITTER_HI = 1.15

/**
 * `base` milliseconds spread to `base × U(0.85, 1.15)`.
 *
 * @param baseMs the cohort interval. A non-finite or non-positive base returns the
 *        floor rather than NaN — `setInterval(fn, NaN)` fires as fast as the browser
 *        allows, which would turn a bad prop into a request storm.
 */
export function jitterMs(baseMs: number, rand: () => number = Math.random): number {
  const base = Number(baseMs)
  if (!Number.isFinite(base) || base <= 0) return MIN_POLL_MS
  const f = JITTER_LO + (JITTER_HI - JITTER_LO) * rand()
  return Math.max(MIN_POLL_MS, Math.round(base * f))
}

/**
 * `setInterval` with the cohort spread applied once, returning the same handle type the
 * panes already store and clear in `onUnmounted`. A drop-in for the 19 call sites.
 */
export function setJitteredInterval(
  fn: () => void,
  baseMs: number,
): ReturnType<typeof setInterval> {
  return setInterval(fn, jitterMs(baseMs))
}
