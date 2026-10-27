/**
 * services/api/pocketPrefs.ts — §POCKETBRIDGE3: the synced developer prefs rail
 * (mig 0152, GET/PUT /developers/me/prefs/{key}).
 *
 * D3-2: the watchlist FOLLOWS THE ACCOUNT. localStorage is only a warm-start
 * cache + offline read; the server value wins whenever it answers, and every
 * write goes through (write-through, optimistic locally). A failed server
 * write is REPORTED by the caller, never swallowed as saved (S2).
 */
import apiClient from './client'
import { authService } from '@/services/auth'

export type PrefKey = 'pocket.watchlist' | 'pocket.price_alerts' | 'pocket.assistant'

const LS_PREFIX = 'tp_pref_'

function cacheRead<T>(key: PrefKey): T | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function cacheWrite(key: PrefKey, value: unknown): void {
  try {
    localStorage.setItem(LS_PREFIX + key, JSON.stringify(value))
  } catch {
    /* private mode etc. — the server copy is the durable one */
  }
}

export async function getPref<T>(key: PrefKey): Promise<{ value: T | null; fromCache: boolean }> {
  // §FESUITE: prefs belong to an account. A visitor on a public page (AGORA listings) has none, and asking anyway was
  // two refused calls on every visit; the device's own copy is the whole answer then.
  if (!authService.isAuthenticated()) return { value: cacheRead<T>(key), fromCache: true }
  try {
    const { data } = await apiClient.get(`/developers/me/prefs/${key}`)
    if (data && data.value != null) cacheWrite(key, data.value)
    return { value: (data?.value ?? null) as T | null, fromCache: false }
  } catch {
    return { value: cacheRead<T>(key), fromCache: true }
  }
}

/** Optimistic local write + server write-through. Resolves false when the
 * server did NOT take it (caller shows "saved on this device only"). */
export async function putPref(key: PrefKey, value: unknown): Promise<boolean> {
  cacheWrite(key, value)
  if (!authService.isAuthenticated()) return false
  try {
    await apiClient.put(`/developers/me/prefs/${key}`, { value })
    return true
  } catch {
    return false
  }
}

/* ── typed shapes the FE + the server-side watcher share ─────────────────── */

export interface WatchEntry {
  symbol: string
  /** null/absent = this venue; a name = a federation venue (display only server-side). */
  venue?: string | null
}

export interface WatchlistValue {
  starred: WatchEntry[]
}

export interface PriceAlertRule {
  id: string
  symbol: string
  venue?: string | null
  baseline: number
  pct: number
  created_at: string
  expires_at: string
  fired_at?: string | null
  fired_price?: string
  fired_direction?: 'up' | 'down'
}

export interface PriceAlertsValue {
  rules: PriceAlertRule[]
}
