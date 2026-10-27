/**
 * services/priceAlerts.ts — §POCKETBRIDGE3 (A4): the SESSION half of price
 * alerts, pure and unit-tested (S6). Mirrors the server watcher's evaluate
 * (background_tasks/price_alert_watcher.py) so the in-app banner and the push
 * agree about what "crossed the band" means.
 *
 * Honesty: a rule watches a ±pct band around the baseline captured AT CREATE
 * TIME, fires ONCE, and expires (default 24h). Venue-scoped rules are only
 * evaluated while the session holds that venue's board — the server watcher
 * covers the LOCAL venue only, and the UI says so.
 */
import type { PriceAlertRule } from './api/pocketPrefs'

export const ALERT_TTL_H = 24

export function makeRule(symbol: string, pct: number, baseline: number, venue?: string | null): PriceAlertRule {
  const now = new Date()
  return {
    id: (globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`),
    symbol: symbol.toUpperCase(),
    venue: venue || null,
    baseline,
    pct,
    created_at: now.toISOString(),
    expires_at: new Date(now.getTime() + ALERT_TTL_H * 3600_000).toISOString(),
    fired_at: null,
  }
}

/** 'up' | 'down' when the rule fires against `last`, else null. Skips fired,
 * expired and malformed rules — exactly like the server evaluator. */
export function evaluateRule(rule: PriceAlertRule, last: number | null | undefined, now?: Date): 'up' | 'down' | null {
  if (!rule || rule.fired_at) return null
  const t = (now ?? new Date()).getTime()
  const exp = Date.parse(rule.expires_at || '')
  if (Number.isFinite(exp) && t > exp) return null
  if (last == null || !Number.isFinite(last)) return null
  const baseline = Number(rule.baseline)
  const pct = Number(rule.pct)
  if (!(baseline > 0) || !(pct > 0)) return null
  if (last >= baseline * (1 + pct / 100)) return 'up'
  if (last <= baseline * (1 - pct / 100)) return 'down'
  return null
}

export function isExpired(rule: PriceAlertRule, now?: Date): boolean {
  const exp = Date.parse(rule.expires_at || '')
  return Number.isFinite(exp) && (now ?? new Date()).getTime() > exp
}

/** Evaluate every armed rule against a price lookup; returns the fired rules
 * WITH their fired_* fields set (caller persists + banners). Pure. */
export function sweepRules(
  rules: PriceAlertRule[],
  lastFor: (symbol: string, venue?: string | null) => number | null,
  now?: Date,
): PriceAlertRule[] {
  const fired: PriceAlertRule[] = []
  const at = (now ?? new Date()).toISOString()
  for (const r of rules) {
    const last = lastFor(r.symbol, r.venue)
    const dir = evaluateRule(r, last, now)
    if (dir) {
      r.fired_at = at
      r.fired_price = String(last)
      r.fired_direction = dir
      fired.push(r)
    }
  }
  return fired
}
