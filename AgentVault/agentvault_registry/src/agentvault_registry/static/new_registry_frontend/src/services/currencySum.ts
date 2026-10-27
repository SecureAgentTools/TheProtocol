import { appLocale } from '@/services/appLocale'
/**
 * services/currencySum.ts — §SUMSPLIT (§ORGMARKET W, 2026-08-30).
 *
 * THE one formatter for aggregates that can span settlement currencies.
 * The law it encodes (§FOREIGNACT's open residue, now closed): NEVER label a
 * mixed sum with one unit. A cross-currency total is not a number, it is a
 * LIST of numbers — "1,204 AVT + 310 JDAY + 12 BVT" — and a single-currency
 * fleet keeps its single line, so nothing changes for the common case.
 *
 * Deliberately dumb: no FX conversion (a converted "total" would be a price
 * claim, not an accounting fact), no rounding policy of its own (callers pass
 * their view's formatter), no locale word order (the joiner is ' + ').
 */

export interface CurrencyAmount {
  amount: number | string | null | undefined
  currency: string | null | undefined
}

export interface CurrencyTotal {
  currency: string
  total: number
}

/** Sum entries per currency. Non-numeric amounts are DROPPED (never coerced to
 *  0 silently — a NaN in, say, a federation row is a missing fact, and a
 *  missing fact must not flatten a real total). Entries with no currency ride
 *  under `fallbackCurrency` when given, else they are dropped too. Order:
 *  `localCurrency` first (the viewer's own frame anchors the line), then by
 *  descending total — deterministic, biggest foreign holdings next. */
export function sumPerCurrency(
  entries: CurrencyAmount[],
  opts: { localCurrency?: string; fallbackCurrency?: string } = {},
): CurrencyTotal[] {
  const by = new Map<string, number>()
  for (const e of entries || []) {
    const cur = (e?.currency || opts.fallbackCurrency || '').toString().trim()
    if (!cur) continue
    const n = typeof e.amount === 'number' ? e.amount : parseFloat(String(e.amount ?? ''))
    if (!Number.isFinite(n)) continue
    by.set(cur, (by.get(cur) || 0) + n)
  }
  const out = Array.from(by.entries()).map(([currency, total]) => ({ currency, total }))
  const local = opts.localCurrency
  out.sort((a, b) => {
    if (local) {
      if (a.currency === local && b.currency !== local) return -1
      if (b.currency === local && a.currency !== local) return 1
    }
    return b.total - a.total || a.currency.localeCompare(b.currency)
  })
  return out
}

/** Render per-currency totals as one line. Single currency → "1,204 AVT"
 *  (the control case, byte-for-byte what a single-frame view showed before).
 *  Mixed → "1,204 AVT + 310 JDAY + 12 BVT". Empty → "" (the caller's
 *  empty-state guard owns that face). */
export function formatPerCurrency(
  entries: CurrencyAmount[],
  opts: {
    localCurrency?: string
    fallbackCurrency?: string
    fmt?: (n: number) => string
  } = {},
): string {
  const fmt = opts.fmt || ((n: number) => n.toLocaleString(appLocale()))
  return sumPerCurrency(entries, opts)
    .map(t => `${fmt(t.total)} ${t.currency}`)
    .join(' + ')
}
