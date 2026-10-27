/**
 * historyRing.ts — §BRIDGE R11 #4/#8
 *
 * ONE history mechanism, asked by BOTH live panels (the fleet log and the live
 * ledger). §FANOUTFIX: two panels that answer the same question with two
 * different implementations will disagree, and the disagreement will be silent.
 *
 * The Commander's ask, in his words: *"it has no history. if you could implement
 * history without hitting the performance too much ... for both live ledger and
 * fleet log"* and *"'fleet log' also pausable please"*.
 *
 * Two hard constraints, both learned the expensive way:
 *
 *  1. **The DOM stays bounded no matter how big the history gets.** §BRIDGE P2
 *     measured 866 live `.blg-row` nodes against a cap of 14 because a
 *     TransitionGroup leave transition never fired. History here is memory, not
 *     nodes: the ring holds up to `cap` entries, the caller renders a WINDOW.
 *
 *  2. **Pause freezes the VIEW, never the intake.** The old ledger pause
 *     `return`ed at the top of its subscriber, so a paused panel was a panel
 *     that was throwing your history away — the opposite of what pause is for.
 *     Here, `push()` always lands in the ring; only `view()` is frozen.
 *
 * The ring is honest about its own bounds: `dropped` counts what has aged out,
 * so a panel can say "2,000 kept, 341 older discarded" instead of implying it
 * remembers the whole session.
 */

export interface HistoryRing<T> {
  /** Newest-first snapshot of the whole ring (a copy; safe to slice). */
  all(): T[]
  /** Newest-first window of `n` entries starting at `offset`. */
  window(n: number, offset?: number): T[]
  push(items: T[]): void
  /** Entries currently held. */
  size(): number
  /** Entries that aged out of the ring since it was created or last cleared. */
  dropped(): number
  clear(): void
  readonly cap: number
}

/** 2,000 is ~10 minutes of the busiest measured frame and a few MB of refs. */
export const DEFAULT_RING_CAP = 2000

export function createHistoryRing<T>(cap: number = DEFAULT_RING_CAP): HistoryRing<T> {
  if (!Number.isFinite(cap) || cap < 1) cap = DEFAULT_RING_CAP
  // Newest-first. Panels read the head far more often than the tail, and every
  // consumer wants "the latest N", so unshift-and-truncate is the natural shape.
  let buf: T[] = []
  let lost = 0

  return {
    cap,
    all: () => buf.slice(),
    window(n, offset = 0) {
      if (n <= 0) return []
      const from = Math.max(0, offset)
      return buf.slice(from, from + n)
    },
    push(items) {
      if (!items || items.length === 0) return
      // Batches arrive OLDEST-first (that is the order the wire delivers them),
      // so unshifting forward leaves the newest at index 0. Unshifting backwards
      // reverses each batch against the ring — caught by the order test, which
      // is the only reason this comment can be trusted.
      for (let i = 0; i < items.length; i++) buf.unshift(items[i])
      if (buf.length > cap) {
        lost += buf.length - cap
        buf.length = cap
      }
    },
    size: () => buf.length,
    dropped: () => lost,
    clear() { buf = []; lost = 0 },
  }
}
