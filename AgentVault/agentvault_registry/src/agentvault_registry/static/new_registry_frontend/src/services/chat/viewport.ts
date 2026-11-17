/**
 * V0662 (OurChat lane): a thread on a phone stays pinned above the keyboard.
 *
 * The maintainer's report (the sessions' room, seq 3212): "the chat window where I type in isn't pinned, it can just move up
 * ... Also / list in pocket our chat reaches out of top screen unscrollable". On a phone the keyboard shrinks the VISUAL
 * viewport but not the layout viewport (100dvh stays whole), so a thread sized by 100dvh keeps its composer behind the keyboard
 * and the browser scrolls the whole page to bring the caret into view: the header goes, the composer moves. The thread is
 * sized to the visible part instead, only while a keyboard is open; with none, the size is exactly what it was.
 */

/** A visual viewport this much shorter than the layout viewport is a keyboard (a collapsing address bar is far less). */
export const KEYBOARD_MIN_PX = 120

export interface ViewportFacts { innerH: number; vvH: number | null; vvTop: number | null; topPx: number; bottomPx: number }
export interface PinnedBounds {
  /** a keyboard is open */
  keyboard: boolean
  /** the bottom edge of the visible area in page coordinates, when a keyboard is open; else null (use the layout's 100dvh) */
  visibleBottomPx: number | null
  /** what to take off that height: the shell's top, and (no keyboard only) the bottom space the page keeps for its bar */
  offsetPx: number
}

/** Pixels the keyboard hides at the bottom of the layout viewport (0 when the facts are missing or odd). */
export function keyboardInset(innerH: number, vvH: number | null, vvTop: number | null): number {
  if (!Number.isFinite(innerH) || vvH == null || !Number.isFinite(vvH)) return 0
  const top = vvTop != null && Number.isFinite(vvTop) ? vvTop : 0
  return Math.max(0, Math.round(innerH - vvH - top))
}

/** How to bound a thread: by the keyboard-aware visible area while a keyboard is open, else as before. */
export function pinnedBounds(f: ViewportFacts): PinnedBounds {
  const inset = keyboardInset(f.innerH, f.vvH, f.vvTop)
  if (inset >= KEYBOARD_MIN_PX && f.vvH != null) {
    // the tab bar sits behind the keyboard, so its space is not kept; the visible bottom is the keyboard's top edge
    return { keyboard: true, visibleBottomPx: Math.round(f.vvH + (f.vvTop || 0)), offsetPx: Math.max(0, Math.round(f.topPx)) }
  }
  return { keyboard: false, visibleBottomPx: null, offsetPx: Math.max(0, Math.round(f.topPx + f.bottomPx)) }
}
