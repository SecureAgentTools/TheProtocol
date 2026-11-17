/**
 * V0662 (OurChat lane): how tall the composer is.
 *
 * It used to be one line with a fixed 120 px ceiling, so a long message was written through a slot. Now it GROWS with
 * what is typed up to about 40% of the pane (the plan's number), can be DRAGGED taller by its handle, and can be taken
 * FULL: a full-height editor for a long text. The browser measures (the text's height, the pane's height, the pointer);
 * these rules decide, so they are tested without one.
 *
 * Pure: no DOM, no storage handle (the caller reads and writes the stored height).
 */

/** One line: the textarea's own minimum. */
export const MIN_PX = 44
/** The composer grows to about this share of the pane, and then scrolls inside itself. */
export const GROW_FRACTION = 0.4
/** The tallest a hand can drag it: enough pane left above to read what the writing answers. */
export const DRAG_MAX_FRACTION = 0.7
/** The full-height editor's share of the pane. */
export const FULL_FRACTION = 0.85
/** A pane not measured yet (before the first layout, or in a test) is taken as this tall, never as zero: zero would pin
 *  the composer to one line for a moment on open. */
export const FALLBACK_PANE_PX = 600
/** The step of an arrow key on the handle. */
export const NUDGE_PX = 24
/** The stored height must be a plausible one, or it is ignored. */
export const STORED_MAX_PX = 4000

export type SizeMode = 'auto' | 'manual' | 'full'

export interface SizeIn {
  /** The text's own height with nothing capping it (the textarea's scrollHeight). */
  contentPx: number
  /** The pane the composer sits in; 0 or less means not measured yet. */
  panePx: number
  mode: SizeMode
  /** The height a hand dragged it to, when there is one. */
  manualPx?: number | null
}

export interface SizeOut {
  heightPx: number
  /** The text is taller than the box: the box scrolls inside itself. */
  scrolls: boolean
}

const pane = (panePx: number): number => (Number.isFinite(panePx) && panePx > 0 ? panePx : FALLBACK_PANE_PX)
const cap = (panePx: number, fraction: number): number => Math.max(MIN_PX, Math.floor(pane(panePx) * fraction))
const clamp = (n: number, lo: number, hi: number): number => Math.min(hi, Math.max(lo, n))

/** The composer's height now, and whether it scrolls. */
export function composerSize(i: SizeIn): SizeOut {
  const content = Math.max(MIN_PX, Math.ceil(Number.isFinite(i.contentPx) ? i.contentPx : 0))
  let heightPx: number
  if (i.mode === 'full') heightPx = cap(i.panePx, FULL_FRACTION)
  else if (i.mode === 'manual' && i.manualPx != null && Number.isFinite(i.manualPx)) {
    heightPx = clamp(Math.round(i.manualPx), MIN_PX, cap(i.panePx, DRAG_MAX_FRACTION))
  } else heightPx = Math.min(content, cap(i.panePx, GROW_FRACTION))
  return { heightPx, scrolls: content > heightPx }
}

/**
 * The height while the handle is dragged: the pointer moving UP makes it taller. `startPx` is the height when the drag
 * began, `startY` and `nowY` the pointer's vertical positions (client coordinates).
 */
export function dragHeight(startPx: number, startY: number, nowY: number, panePx: number): number {
  return clamp(Math.round(startPx + (startY - nowY)), MIN_PX, cap(panePx, DRAG_MAX_FRACTION))
}

/** One arrow-key step on the handle: up grows, down shrinks. */
export function nudgeHeight(currentPx: number, direction: 'up' | 'down', panePx: number): number {
  const delta = direction === 'up' ? NUDGE_PX : -NUDGE_PX
  return clamp(Math.round(currentPx) + delta, MIN_PX, cap(panePx, DRAG_MAX_FRACTION))
}

/** A height read back from storage: a whole, plausible number of pixels, else nothing (a damaged value must not pin
 *  the composer to a strange size for good). */
export function parseStoredHeight(raw: string | null | undefined): number | null {
  if (raw == null || !/^\d+$/.test(String(raw).trim())) return null
  const n = Number(String(raw).trim())
  return n >= MIN_PX && n <= STORED_MAX_PX ? n : null
}
