/**
 * Pan and zoom for the full-screen diagram view, as pure arithmetic.
 *
 * The canvas is transformed with `translate(x, y) scale(s)` and
 * `transform-origin: 0 0`, so a content point c sits on screen at x + c·s.
 * Zooming "at" a screen point keeps the content under that point where it was:
 * the only property that makes wheel and pinch zoom feel anchored.
 */

export interface PanZoom {
  scale: number
  x: number
  y: number
}

export const PZ_IDENTITY: PanZoom = { scale: 1, x: 0, y: 0 }
export const PZ_MIN = 0.5
export const PZ_MAX = 8

export function clampScale(s: number, min = PZ_MIN, max = PZ_MAX): number {
  if (!Number.isFinite(s)) return 1
  return Math.min(max, Math.max(min, s))
}

/** Zoom by `factor`, keeping the screen point (cx, cy) over the same content point. */
export function zoomAt(pz: PanZoom, factor: number, cx: number, cy: number, min = PZ_MIN, max = PZ_MAX): PanZoom {
  const scale = clampScale(pz.scale * factor, min, max)
  const k = scale / pz.scale
  return { scale, x: cx - (cx - pz.x) * k, y: cy - (cy - pz.y) * k }
}

export function panBy(pz: PanZoom, dx: number, dy: number): PanZoom {
  return { scale: pz.scale, x: pz.x + dx, y: pz.y + dy }
}

/**
 * One wheel event's zoom factor. deltaMode 1 (lines) is scaled to pixels the way
 * browsers do; the exponent keeps a trackpad's many small deltas and a mouse
 * wheel's few large ones on the same curve, and each step is capped so one
 * violent flick cannot jump from fit to maximum.
 */
export function wheelFactor(deltaY: number, deltaMode = 0): number {
  const px = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY
  const capped = Math.max(-240, Math.min(240, px))
  return Math.exp(-capped * 0.0025)
}

export function distance(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}

export function midpoint(a: { x: number; y: number }, b: { x: number; y: number }): { x: number; y: number } {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
}

export function transformCss(pz: PanZoom): string {
  return `translate(${pz.x.toFixed(1)}px, ${pz.y.toFixed(1)}px) scale(${pz.scale.toFixed(4)})`
}
