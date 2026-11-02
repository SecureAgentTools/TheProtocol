/**
 * V0654 (session-lead, the sessions' room seq 937-949; check 140 of V0653's console proof): a thread opens at the first
 * message you have not read, under the NEW line (V0652 (ag), his report seq 313), but it scrolled there ONCE, right after
 * the first render. Anything that changes the layout after that one scroll re-wraps the messages above the line and moves
 * it out of view: the pane narrowing or widening as the list beside it folds or unfolds, fonts that finish loading, bodies
 * and cards that finish drawing, the approvals pinned above an org room's history after their own fetch. 140 saw read
 * messages on screen and the first unread below them, some of the time.
 *
 * For a short while after an open this re-runs the scroll whenever the scroll area or anything in it changes size, and
 * the reader's own first move in the thread (the wheel, a touch, a key, a press anywhere in it: the list, a message,
 * the composer, a button) ends it at once, so it never fights a person. While it holds, the thread does not take a
 * live message to the end of the list either (the reader has not reached it); the reader's own send is a move, so it
 * still goes to the end. Pure of the view: the thread hands its scroll area, its own scroll and its root.
 */

/** How long after an open the NEW line is kept in place. */
export const ANCHOR_MS = 2000

/** What a reader does to move a list on their own (a scroll the code makes raises none of these). */
const INTENT = ['wheel', 'touchstart', 'keydown', 'pointerdown'] as const

export interface Anchor {
  /** End it now (safe to call twice). */
  stop: () => void
  /** Still holding: not stopped, not timed out, the reader has not moved the list. */
  active: () => boolean
}

const NONE: Anchor = { stop: () => {}, active: () => false }

/**
 * Keep re-anchoring `scroller` with `reanchor` while it settles: on every size change of the scroll area or of what is
 * in it at the open, for `ms` milliseconds or until the reader moves (inside `intentRoot`, the scroll area itself when
 * none is given). Where the browser has no ResizeObserver it keeps nothing (an anchor that is never active).
 */
export function keepAnchored(scroller: HTMLElement, reanchor: () => void, ms: number = ANCHOR_MS,
                             intentRoot: HTMLElement = scroller): Anchor {
  if (typeof ResizeObserver === 'undefined') return NONE
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined
  const observer = new ResizeObserver(() => { if (!stopped) reanchor() })
  const stop = () => {
    if (stopped) return
    stopped = true
    observer.disconnect()
    for (const ev of INTENT) intentRoot.removeEventListener(ev, stop)
    if (timer !== undefined) clearTimeout(timer)
  }
  observer.observe(scroller)
  for (const el of Array.from(scroller.children)) observer.observe(el)
  for (const ev of INTENT) intentRoot.addEventListener(ev, stop, { passive: true })
  timer = setTimeout(stop, ms)
  return { stop, active: () => !stopped }
}
