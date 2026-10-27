/**
 * globalReset — invoke `$reset()` on every active Pinia store on logout.
 *
 * Wired from `auth.logout()` so user-A's data doesn't leak into user-B's
 * view on a same-browser handover. Solves audit finding #9 (P2.2,
 * 2026-05-08) — 18 stores either had no reset or weren't called from
 * logout.
 *
 * Mechanism:
 * - Iterates `getActivePinia()._s` (Map of all active stores).
 * - For each store, calls `store.$reset()` if it's a function. Pinia
 *   *option stores* (state: () => ({...})) have $reset built-in. *Setup
 *   stores* don't — they each need an explicit `function $reset()`
 *   exposed in the return.
 * - SKIPPED stores (intentionally not reset on logout):
 *     - 'ui'        — theme + sidebar mode are per-user-prefs, persist
 *     - 'auth'      — auth.logout() is its own teardown path; resetting
 *                     mid-flight would clobber user.value cleanup
 *     - 'websocket' — connection-level, has its own teardown
 *
 * Safe to call from anywhere; idempotent. Errors per-store are caught so
 * one bad reset doesn't block the others.
 */

import { getActivePinia } from 'pinia'
import { useLogger } from '@/composables/useLogger'

const SKIP_STORES = new Set(['ui', 'auth', 'websocket'])

export function globalReset(): void {
  const log = useLogger('globalReset')
  const pinia = getActivePinia()
  if (!pinia) {
    log.warn('no active pinia — nothing to reset')
    return
  }

  // Pinia's internal `_s` is a Map<storeId, store>. Documented as
  // semi-private but stable across Pinia v2.x; the alternative
  // (re-creating pinia from scratch) requires re-binding all
  // useXxxStore() composables which is impractical mid-session.
  const internalStores = (pinia as unknown as { _s: Map<string, { $reset?: () => void; $id?: string }> })._s

  let resetCount = 0
  let skipCount = 0
  let errorCount = 0

  internalStores.forEach((store, storeId) => {
    if (SKIP_STORES.has(storeId)) {
      skipCount++
      return
    }
    if (typeof store.$reset !== 'function') {
      // Setup store without an explicit $reset — silently skip; not a fatal
      // condition. Add `$reset` to the store's return object to opt in.
      skipCount++
      return
    }
    try {
      store.$reset()
      resetCount++
    } catch (err) {
      errorCount++
      log.warn(`failed to reset store '${storeId}'`, err)
    }
  })

  log.info(`reset ${resetCount} stores, skipped ${skipCount}, ${errorCount} errors`)
}
