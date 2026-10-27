import { appLocale } from '@/services/appLocale'
/**
 * §COCKPITTILES T0 — ONE number formatter for the cockpit desk.
 *
 * 🔴 WHY THIS EXISTS. `Number.prototype.toLocaleString(appLocale())` called with no locale (or with
 * `undefined`) formats in the OPERATING SYSTEM's locale, never the app's. Measured on the
 * Commander's screenshots 2026-08-31: an English UI on a German OS rendered `22,1 Mio.`,
 * `101,06 AVT`, `515.473,61` and — the sharpest case — DENIALS printing 3,330 refusals as
 * `3.330`, which an English reader reads as three point three. Server-rendered strings sat
 * beside them in plain English (`2000.00 AVT`), so the same pane disagreed with itself.
 *
 * `formatNumber()` in `@/i18n` has always resolved `getLocale()` — the locale the UI is
 * actually rendering in — and no cockpit component called it. This module is the door.
 *
 * ⚠ Never reach for `toLocaleString` in `components/cockpit/`; the build gate
 * (`scratchpad/cockpit/verify_tiles_rega.py`) asserts zero occurrences there.
 */
import { formatNumber, getLocale } from '@/i18n'

/** What a value that is not a number renders as. Never `0` — see the §RAT rule. */
export const NO_VALUE = '—'

/** Coerce anything the API hands us. Scientific notation ("1E+3") parses; junk does not. */
export function toNum(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const n = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(n) ? n : null
}

function safe(n: number, options: Intl.NumberFormatOptions): string {
  try {
    return formatNumber(n, options)
  } catch {
    // A broken locale must not blank a money pane.
    return new Intl.NumberFormat('en', options).format(n)
  }
}

/** Exact, grouped, app-locale. The figure you can read back to an accountant. */
export function fmt(value: unknown, dp = 2, minDp = 0): string {
  const n = toNum(value)
  if (n === null) return NO_VALUE
  return safe(n, { maximumFractionDigits: dp, minimumFractionDigits: Math.min(minDp, dp) })
}

/** A whole count. Grouped, never fractional. */
export function fmtCount(value: unknown): string {
  const n = toNum(value)
  if (n === null) return NO_VALUE
  return safe(n, { maximumFractionDigits: 0 })
}

/** Compact headline: 135M / 22.1M. Announces its own rounding, unlike a truncation. */
export function fmtCompact(value: unknown, dp = 1): string {
  const n = toNum(value)
  if (n === null) return NO_VALUE
  return safe(n, { notation: 'compact', maximumFractionDigits: dp })
}

/** Would `fmtAuto` compact this? Panes ask so they can print the exact figure beside it. */
export function isCompacted(value: unknown, compactFrom = 1_000_000): boolean {
  const n = toNum(value)
  return n !== null && Math.abs(n) >= compactFrom
}

/** The same defect wearing a date: a bare `toLocaleString()` on a Date is the OS locale
 *  too. One site (the candle readout) needs a full timestamp; everything else in the
 *  cockpit renders relative ages, which carry no locale. */
export function fmtDateTime(value: Date | string | number): string {
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return NO_VALUE
  try {
    return new Intl.DateTimeFormat(getLocale(), {
      dateStyle: 'medium', timeStyle: 'short',
    }).format(d)
  } catch {
    return d.toISOString().replace('T', ' ').slice(0, 16)
  }
}

/** Compact above the threshold, exact below — the pattern every money pane already used. */
export function fmtAuto(value: unknown, dp = 2, compactFrom = 1_000_000): string {
  const n = toNum(value)
  if (n === null) return NO_VALUE
  return isCompacted(n, compactFrom) ? fmtCompact(n) : fmt(n, dp)
}
