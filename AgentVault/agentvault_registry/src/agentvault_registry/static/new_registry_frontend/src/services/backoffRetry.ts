/**
 * A retry that backs off and stops (§FESUITE, 2026-10-04). After a read or a sign-in fails for want of an answer, the
 * console tries again on its own: once per step of `steps`, the last step repeating, until `cancel()` (an answer came,
 * the person chose otherwise, or signed out). One timer at a time: `schedule()` while one is pending does nothing, so a
 * failure reported twice cannot double the pace; `cancel()` also resets the steps, so the next outage starts at the first.
 */
export interface BackoffRetry {
  /** arms the next try; false when one is already pending */
  schedule(): boolean
  cancel(): void
  readonly pending: boolean
  /** tries armed since the last cancel */
  readonly attempts: number
}

export const BACKOFF_STEPS_MS = [5_000, 10_000, 20_000, 40_000, 60_000]

export function createBackoffRetry(run: () => unknown, steps: number[] = BACKOFF_STEPS_MS): BackoffRetry {
  let timer: ReturnType<typeof setTimeout> | null = null
  let attempts = 0
  return {
    schedule() {
      if (timer) return false
      const ms = steps[Math.min(attempts, steps.length - 1)]
      attempts += 1
      timer = setTimeout(() => {
        timer = null
        try {
          const r = run() as { catch?: (f: () => void) => unknown } | undefined
          // the run reports its own failure (and schedules again when it wants to)
          if (r && typeof r.catch === 'function') r.catch(() => {})
        } catch { /* as above */ }
      }, ms)
      return true
    },
    cancel() {
      if (timer) { clearTimeout(timer); timer = null }
      attempts = 0
    },
    get pending() { return timer !== null },
    get attempts() { return attempts },
  }
}
