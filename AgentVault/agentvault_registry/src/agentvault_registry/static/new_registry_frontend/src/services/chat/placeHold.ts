/**
 * V0665 (his report, room seq 4218: "When new messages come in on desktop. I get scrolled down to it always. So when I read
 * a message further up I lose it."): a thread holds the reader's place.
 *
 * The rule, in numbers so a test needs no layout:
 *   - a message from someone else takes the reader down ONLY when they were near the bottom BEFORE it arrived;
 *   - the reader's own message always takes them down;
 *   - otherwise the place holds and the message is counted for the "new below" pill, which remembers the first of them
 *     (the pill takes the reader there, not past it) and goes when the reader gets to the bottom or presses it.
 * A held NEW line (the unread anchor of V0654) keeps its own rule in the thread: this module only says what the position
 * says; the thread decides whether to act on `scroll` while that anchor holds.
 */

/** the same 80 px the thread has always called "near the bottom" (catchUpThread) */
export const NEAR_BOTTOM_PX = 80

export interface NewBelow { count: number; firstSeq: number | null }
export const NO_NEW_BELOW: NewBelow = { count: 0, firstSeq: null }

export interface ScrollBox { scrollHeight: number; scrollTop: number; clientHeight: number }

/** how far the reader is from the end of the thread, in px (0 at the bottom) */
export function distanceFromBottom(b: ScrollBox): number {
  return Math.max(0, b.scrollHeight - b.scrollTop - b.clientHeight)
}

/** Is the reader at the end? A thread that is not laid out yet (no box) counts as at the end, as it always did. */
export function nearBottomOf(b: ScrollBox | null | undefined): boolean {
  return !b || distanceFromBottom(b) < NEAR_BOTTOM_PX
}

export type Place = 'scroll' | 'hold'

/** Does an arriving message take the reader down? Own: always. Someone else's: only from near the bottom. */
export function placeFor(a: { wasNearBottom: boolean; mine: boolean }): Place {
  return a.mine || a.wasNearBottom ? 'scroll' : 'hold'
}

/**
 * A message arrived. `place` says whether it takes the reader down; when it holds, it is counted (a message of the
 * reader's own never counts: they wrote it, they know). A scroll clears the count: the reader is at the end.
 */
export function noteArrival(cur: NewBelow, a: { seq: number; wasNearBottom: boolean; mine: boolean }): { place: Place; below: NewBelow } {
  const place = placeFor(a)
  if (place === 'scroll') return { place, below: NO_NEW_BELOW }
  const seq = Number(a.seq)
  const first = cur.firstSeq == null ? seq : Math.min(cur.firstSeq, seq)
  return { place, below: { count: cur.count + 1, firstSeq: Number.isFinite(first) ? first : cur.firstSeq } }
}

/** The reader reached the end by hand (or any other way): nothing is below any more. */
export function atBottom(cur: NewBelow, near: boolean): NewBelow {
  return near && cur.count > 0 ? NO_NEW_BELOW : cur
}

/**
 * A picture (or any box) ABOVE the reader's view finished loading and grew the thread: where must the reader's scroll
 * position be so what they read stays where it was (the distance from the bottom stable)? `null` = leave it.
 * Browsers that anchor scrolling do this themselves (the distance is already right: nothing to do); the rest (Safari on a
 * phone) jump, and this puts them back. Only a reader away from the bottom is held; one at the end follows the end.
 */
export function holdDistance(a: { before: number; box: ScrollBox; nearBottom: boolean; aboveView: boolean; maxGrowth?: number }): number | null {
  if (a.nearBottom || !a.aboveView) return null
  const now = distanceFromBottom(a.box)
  if (Math.abs(now - a.before) < 1) return null
  // growth the picture cannot account for (a card opened, a message came in below) is not the picture's: leave it
  if (a.maxGrowth != null && now - a.before > a.maxGrowth + 1) return null
  return Math.max(0, a.box.scrollHeight - a.box.clientHeight - a.before)
}
