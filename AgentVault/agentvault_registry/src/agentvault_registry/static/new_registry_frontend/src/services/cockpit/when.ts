/**
 * §COCKPITDESK (2026-10-15) — how long ago, and how long until, in the desk's short form.
 *
 * The older panes each carry their own `ago()`; the panes added on 2026-10-15 share this one, and a deadline
 * that has passed says so instead of printing a negative duration.
 */

/** Seconds as the desk's short duration: 45s, 12m, 3h, 2d. */
export function shortSpan(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 90) return `${s}s`
  if (s < 5400) return `${Math.round(s / 60)}m`
  if (s < 172800) return `${Math.round(s / 3600)}h`
  return `${Math.round(s / 86400)}d`
}

function epoch(iso?: string | number | null): number | null {
  if (iso === null || iso === undefined || iso === '') return null
  const ms = typeof iso === 'number' ? iso : new Date(iso).getTime()
  return Number.isFinite(ms) ? ms : null
}

/** How long ago `iso` was ('' when there is no usable time). A time in the future reads as 0s. */
export function agoShort(iso?: string | number | null, now: number = Date.now()): string {
  const ms = epoch(iso)
  return ms === null ? '' : shortSpan((now - ms) / 1000)
}

/** How long until `iso`, and whether it has already passed (null when there is no usable time). */
export function untilShort(iso?: string | number | null, now: number = Date.now()): { span: string; past: boolean } | null {
  const ms = epoch(iso)
  if (ms === null) return null
  const d = (ms - now) / 1000
  return { span: shortSpan(Math.abs(d)), past: d <= 0 }
}
