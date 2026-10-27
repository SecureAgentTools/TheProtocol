/**
 * composables/useWatchAlerts.ts — §POCKETBRIDGE4 WS-P: ONE watchlist + price-alert
 * brain for every surface (PocketTrade, StockDiscovery, ExchangeDesk).
 *
 * Extracted verbatim-in-behavior from PocketTrade's batch-3 implementation so
 * phone and desktop stay ONE mechanism over the same synced prefs
 * (pocket.watchlist / pocket.price_alerts — mig 0152). Entry shapes stay
 * byte-compatible: `venue: null` means THIS venue (the server watcher's
 * contract); a venue NAME means a federation venue, session-watched only.
 *
 * State is per-composable-call (each view owns its copy); the SERVER is the
 * meeting point, so a change on one surface reaches the others on their next
 * load — same as it reaches another device.
 */
import { ref, computed } from 'vue'
import {
  getPref,
  putPref,
  type WatchEntry,
  type WatchlistValue,
  type PriceAlertRule,
  type PriceAlertsValue,
} from '@/services/api/pocketPrefs'
import { makeRule, sweepRules, isExpired } from '@/services/priceAlerts'

export function useWatchAlerts() {
  /* ── watchlist ── */
  const starred = ref<WatchEntry[]>([])
  const watchSyncNote = ref('')
  const watchKey = (w: WatchEntry) => `${w.symbol}::${w.venue || ''}`
  const isStarred = (sym: string, venue?: string | null) =>
    starred.value.some((w) => w.symbol === sym && (w.venue || null) === (venue || null))

  // A slow in-flight GET must never clobber a FRESHER local mutation: the
  // load captures the mutation seq before awaiting and applies only if no
  // toggle landed meanwhile (measured live: star → strip vanished when the
  // mount-time GET resolved after the click with the pre-click value).
  let watchSeq = 0
  async function loadWatch() {
    const seq = watchSeq
    const { value } = await getPref<WatchlistValue>('pocket.watchlist')
    if (seq === watchSeq && value?.starred) starred.value = value.starred
  }

  async function toggleStar(sym: string, venue?: string | null) {
    watchSeq++
    const key = `${sym}::${venue || ''}`
    const had = starred.value.some((w) => watchKey(w) === key)
    starred.value = had
      ? starred.value.filter((w) => watchKey(w) !== key)
      : [...starred.value, { symbol: sym, venue: venue || null }]
    const ok = await putPref('pocket.watchlist', { starred: starred.value })
    watchSyncNote.value = ok ? '' : 'saved on this device only — sync failed'
  }

  /* ── price alerts ── */
  const alertRules = ref<PriceAlertRule[]>([])
  const alertNote = ref('')
  const firedDismissed = new Set<string>()
  const firedBanner = computed(() => alertRules.value.filter((r) => r.fired_at && !firedDismissed.has(r.id)))

  let alertSeq = 0
  async function loadAlerts() {
    const seq = alertSeq
    const { value } = await getPref<PriceAlertsValue>('pocket.price_alerts')
    if (seq === alertSeq && value?.rules) alertRules.value = value.rules
  }

  async function persistAlerts(): Promise<boolean> {
    alertSeq++
    const ok = await putPref('pocket.price_alerts', { rules: alertRules.value })
    alertNote.value = ok
      ? 'watched in-app now; when the app is closed the registry watches the LOCAL market and can push (enable "price alert" push in notification settings, off by default)'
      : 'saved on this device only — sync failed, so the server watcher will not see this rule'
    return ok
  }

  async function addAlertRule(sym: string, pct: number, baseline: number, venue?: string | null) {
    alertRules.value = [...alertRules.value.filter((r) => !isExpired(r)), makeRule(sym, pct || 5, baseline, venue)]
    await persistAlerts()
  }

  async function removeAlertRule(a: PriceAlertRule) {
    alertRules.value = alertRules.value.filter((r) => r.id !== a.id)
    await persistAlerts()
  }

  function dismissFired() {
    for (const f of firedBanner.value) firedDismissed.add(f.id)
    alertRules.value = [...alertRules.value]
  }

  /** Sweep armed rules against a price lookup; fired rules banner + persist. */
  function sweep(lastFor: (symbol: string, venue?: string | null) => number | null): PriceAlertRule[] {
    const fired = sweepRules(alertRules.value, lastFor)
    if (fired.length) {
      alertRules.value = [...alertRules.value]
      void persistAlerts()
    }
    return fired
  }

  return {
    starred, watchSyncNote, isStarred, loadWatch, toggleStar, watchKey,
    alertRules, alertNote, firedBanner, loadAlerts, addAlertRule, removeAlertRule, dismissFired, sweep,
  }
}
