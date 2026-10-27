/**
 * Notification Store — f034 Admin Broadcast Channel
 *
 * State:
 *   items      — unread broadcasts; hydrated from localStorage on store init
 *                so the bell shows the last-known state instantly across
 *                page reloads, then overwritten authoritatively by the
 *                server response when fetchUnread() resolves.
 *   toasts     — live WS arrivals shown as bottom-right toast popups
 *
 * Workflow:
 *   1. Store init: items hydrates from localStorage (last 50, dedupe by id,
 *      priority-aware trim — critical never evicted by info).
 *   2. On login: fetchUnread() → overwrites items with server-authoritative
 *      unread set + persists.
 *   3. WS message type=notification arrives → addLiveToast() + prepend to
 *      items + persist (subscribed via subscribeToWebSocket() — call once
 *      after WS is up).
 *   4. User clicks Dismiss → markRead(id) → removes from items + persists,
 *      calls API + broadcasts to other tabs via BroadcastChannel.
 *   5. Toast auto-dismisses after 8s or on click.
 *   6. On logout: $reset() (called via stores/globalReset) clears
 *      localStorage so user-A's notifications don't leak into user-B.
 *
 * §bc1 (2026-05-19) additions:
 *   - Priority-aware trim (T1.7): keep ALL unread critical first, then
 *     warning/maintenance, then info up to HISTORY_MAX. Fixes P2.2.
 *   - retract(id) (T1.4 frontend): hard-remove from items + toasts when
 *     `broadcast.retracted` WS event arrives. Cross-tab synced.
 *   - patchItem(payload) (T1.4 frontend): partial in-place update when
 *     `broadcast.updated` WS event arrives. Cross-tab synced.
 *   - BroadcastChannel cross-tab read sync (T1.3): markRead/retract on tab A
 *     reflect on tab B within <200ms. Falls back to 'storage' event for
 *     browsers without BroadcastChannel API.
 *
 * Persistence rationale (#8, 2026-05-08): without hydration, a live toast
 * that arrives just before a reload disappears from the bell during the
 * brief fetchUnread loading window. The localStorage cache (capped at 50)
 * provides instant-visible bell state across reloads. Server is still
 * source of truth — fetchUnread() always overwrites once it resolves.
 *
 * Backend wiring (P3.3 audit, 2026-05-08): the `notification` WS event type
 * is fired by `manager.broadcast_notification()` in routers/websocket.py.
 * To extend live alerts to event-driven cases (funding requests, disputes,
 * drift, supply breaches), a reactor in background_tasks/ must call
 * `broadcast_notification(...)` when its event lands. That's a backend
 * change — frontend already catches whatever flows through `notification`.
 */
import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { authService } from '@/services/auth'
import { createBackoffRetry } from '@/services/backoffRetry'
import { useLogger } from '@/composables/useLogger'

const log = useLogger('notifications')

const LOCAL_HISTORY_KEY = 'theprotocol:notifications:history'
const HISTORY_MAX = 50
const BROADCAST_CHANNEL_NAME = 'theprotocol:notifications'
const STORAGE_SYNC_KEY = 'theprotocol:notifications:sync'

export interface BroadcastItem {
  id: number
  title: string
  body: string
  broadcast_type: 'info' | 'warning' | 'maintenance' | 'critical'
  created_at: string
  // §bc2 — optional extensions (absent on legacy rows + on info ws envelopes)
  cta_url?: string | null
  cta_label?: string | null
  requires_ack?: boolean
  scheduled_for?: string | null
}

export interface ToastItem extends BroadcastItem {
  toast_id: string   // unique per-display id (not the broadcast id)
  expires_at: number // Date.now() + 8000 (∞ for critical/requires_ack — T1.5/T2.8 prep)
}

type CrossTabSyncMsg =
  | { kind: 'read'; broadcast_id: number }
  | { kind: 'retracted'; broadcast_id: number }
  | { kind: 'updated'; broadcast_id: number; patch: Partial<BroadcastItem> }

/**
 * §bc1 T1.7 — Priority-aware trim. Caps the persisted list at HISTORY_MAX
 * but never evicts unread CRITICAL by less-important INFO. Order within
 * each priority is preserved (newest first). Stable across calls.
 */
const PRIORITY_RANK: Record<BroadcastItem['broadcast_type'], number> = {
  critical: 0,
  warning: 1,
  maintenance: 2,
  info: 3,
}

function priorityTrim(list: BroadcastItem[], max: number): BroadcastItem[] {
  if (list.length <= max) return list
  // Stable sort by priority (lower rank = higher priority); keep
  // original index as tiebreaker so within-priority order is preserved.
  const indexed = list.map((item, idx) => ({ item, idx }))
  indexed.sort((a, b) => {
    const pa = PRIORITY_RANK[a.item.broadcast_type] ?? 99
    const pb = PRIORITY_RANK[b.item.broadcast_type] ?? 99
    if (pa !== pb) return pa - pb
    return a.idx - b.idx
  })
  return indexed.slice(0, max).map(e => e.item)
}

function loadPersistedHistory(): BroadcastItem[] {
  try {
    const raw = localStorage.getItem(LOCAL_HISTORY_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    if (!Array.isArray(parsed)) return []
    // Defensive shape check — ignore malformed entries rather than crashing.
    return parsed.filter(
      (e): e is BroadcastItem =>
        e &&
        typeof e.id === 'number' &&
        typeof e.title === 'string' &&
        typeof e.body === 'string' &&
        typeof e.broadcast_type === 'string' &&
        typeof e.created_at === 'string'
    )
  } catch (e) {
    log.warn('loadPersistedHistory failed', e)
    return []
  }
}

function persistHistory(list: BroadcastItem[]) {
  try {
    const trimmed = priorityTrim(list, HISTORY_MAX)
    localStorage.setItem(LOCAL_HISTORY_KEY, JSON.stringify(trimmed))
  } catch (e) {
    log.warn('persistHistory failed', e)
  }
}

function clearPersistedHistory() {
  try {
    localStorage.removeItem(LOCAL_HISTORY_KEY)
  } catch (e) {
    log.warn('clearPersistedHistory failed', e)
  }
}

// ── Cross-tab sync (T1.3) ──
let bcChannel: BroadcastChannel | null = null
let storageHandler: ((e: StorageEvent) => void) | null = null

function emitCrossTab(msg: CrossTabSyncMsg) {
  try {
    if (bcChannel) {
      bcChannel.postMessage(msg)
    } else {
      // Fallback: use localStorage `storage` event (only fires across tabs,
      // not same-tab — that's what we want).
      localStorage.setItem(STORAGE_SYNC_KEY, JSON.stringify({
        ...msg,
        _ts: Date.now(),
      }))
    }
  } catch (e) {
    log.warn('emitCrossTab failed', e)
  }
}

/**
 * §FESUITE — an entry of the per-developer in-app feed (GET /notifications/feed): the non-broadcast types a person
 * switches on for the in-app channel (2FA changed, a dispute filed against their agent, a support reply...). The
 * desktop bell showed admin broadcasts only, so these reached Pocket and nowhere on the desktop.
 */
export interface FeedItem {
  id: number
  type_key: string
  category: string
  severity: string
  title: string
  body: string
  click: string | null
  created_at: string | null
  read: boolean
}

export const useNotificationStore = defineStore('notifications', () => {
  const items = ref<BroadcastItem[]>(loadPersistedHistory())
  const feed = ref<FeedItem[]>([])
  const toasts = ref<ToastItem[]>([])
  const loading = ref(false)
  /** §FESUITE (2026-10-05): the last read of each half failed (no answer, or an answer that was not one). The bell said
   *  "All clear." over failed reads; it says they could not be read now. A failed read changes no list (a refresh that
   *  fails keeps what was shown), and a feed that is off or absent (404) is an answer, not a failure. */
  const unreadFailed = ref(false)
  /** §ALERTS header strip: when the unread list last came back answered (0 = not yet). The strips say "no new
   *  broadcasts" only after a read said so: the list hydrated from localStorage is the last answer, not this one. */
  const lastReadAt = ref(0)
  const feedFailed = ref(false)
  /** §FESUITE (2026-10-09): an unread read that got no answer (or a 5xx: a registry restarting) is read again on its own,
   *  backing off, until one answers. It was read only on the layout's mount, a socket reconnect or a press, so a console
   *  opened while the registry could not answer said "BROADCASTS COULD NOT BE READ // PRESS TO TRY AGAIN" for the rest
   *  of the session after the registry was back (sweeps/recovery on V0587, every member page). A refusal (401/403/4xx)
   *  answers the same way every time and is never retried. */
  const unreadRetry = createBackoffRetry(() => fetchUnread())

  /** Broadcasts AND unread feed entries: the bell counts what it lists. */
  const unreadCount = computed(() => items.value.length + feed.value.length)
  const criticalItems = computed(() =>
    items.value.filter(i => i.broadcast_type === 'critical')
  )

  async function fetchFeed() {
    const token = authService.getAccessToken()
    if (!token) return
    try {
      const res = await fetch('/api/v1/notifications/feed?unread_only=true&limit=50', {
        headers: { Authorization: `Bearer ${token}` },
      })
      if (!res.ok) { feedFailed.value = res.status !== 404; return }
      const body = await res.json()
      feedFailed.value = false
      if (body?.available === false) return
      feed.value = Array.isArray(body?.entries) ? body.entries.filter((e: FeedItem) => !e.read) : []
    } catch (e) {
      log.warn('fetchFeed failed', e)
      feedFailed.value = true
    }
  }

  async function markFeedRead(id: number) {
    feed.value = feed.value.filter(e => e.id !== id)
    const token = authService.getAccessToken()
    if (!token) return
    try {
      await fetch(`/api/v1/notifications/feed/${id}/read`, { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
    } catch (e) {
      log.warn('markFeedRead failed', e)
    }
  }

  async function markAllFeedRead() {
    if (!feed.value.length) return
    feed.value = []
    const token = authService.getAccessToken()
    if (!token) return
    try {
      await fetch('/api/v1/notifications/feed/read-all', { method: 'POST', headers: { Authorization: `Bearer ${token}` } })
    } catch (e) {
      log.warn('markAllFeedRead failed', e)
    }
  }

  async function fetchUnread() {
    const token = authService.getAccessToken()
    if (!token) return
    void fetchFeed()
    loading.value = true
    try {
      const res = await fetch('/api/v1/notifications/unread', {
        headers: { Authorization: `Bearer ${token}` },
      })
      unreadFailed.value = !res.ok
      if (res.ok) unreadRetry.cancel()
      else if (res.status >= 500) unreadRetry.schedule()
      if (res.ok) {
        lastReadAt.value = Date.now()
        const server: BroadcastItem[] = await res.json()
        // Server is authoritative for what's unread. Overwrite + dedupe by
        // id (defensive — server should already deduplicate).
        const seen = new Set<number>()
        items.value = server.filter(s => {
          if (seen.has(s.id)) return false
          seen.add(s.id)
          return true
        })
        persistHistory(items.value)
      }
    } catch (e) {
      log.warn('fetchUnread failed', e)
      unreadFailed.value = true
      unreadRetry.schedule()
    } finally {
      loading.value = false
    }
  }

  async function markRead(broadcastId: number, opts?: { skipCrossTab?: boolean }) {
    // Optimistic update
    items.value = items.value.filter(i => i.id !== broadcastId)
    persistHistory(items.value)
    dismissToastByBroadcastId(broadcastId)
    if (!opts?.skipCrossTab) emitCrossTab({ kind: 'read', broadcast_id: broadcastId })

    const token = authService.getAccessToken()
    if (!token) return
    try {
      await fetch(`/api/v1/notifications/${broadcastId}/read`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      })
    } catch (e) {
      log.warn('markRead failed', e)
    }
  }

  async function markAllRead() {
    void markAllFeedRead()
    const ids = items.value.map(i => i.id)
    items.value = []
    toasts.value = []
    persistHistory(items.value)
    for (const id of ids) {
      const token = authService.getAccessToken()
      if (!token) break
      try {
        await fetch(`/api/v1/notifications/${id}/read`, {
          method: 'POST',
          headers: { Authorization: `Bearer ${token}` },
        })
      } catch (e) {
        log.warn(`markAllRead failed for ${id}`, e)
      }
      emitCrossTab({ kind: 'read', broadcast_id: id })
    }
  }

  /**
   * Called when a WS message with type=notification arrives.
   * Adds to items (if not already there) and spawns a toast.
   */
  function addLiveNotification(data: {
    broadcast_id: number
    title: string
    message: string
    type: string
    // §bc2 — optional fields on the WS envelope
    cta_url?: string | null
    cta_label?: string | null
    requires_ack?: boolean
  }) {
    const item: BroadcastItem = {
      id: data.broadcast_id,
      title: data.title,
      body: data.message,
      broadcast_type: data.type as BroadcastItem['broadcast_type'],
      created_at: new Date().toISOString(),
      cta_url: data.cta_url ?? null,
      cta_label: data.cta_label ?? null,
      requires_ack: !!data.requires_ack,
    }
    // Prepend only if not already in list
    if (!items.value.find(i => i.id === item.id)) {
      items.value = priorityTrim([item, ...items.value], HISTORY_MAX)
      persistHistory(items.value)
    }
    // §bc2 T2.8 — sticky toast for critical OR requires_ack. Others auto-dismiss at 8s.
    const sticky = item.broadcast_type === 'critical' || item.requires_ack === true
    const toast: ToastItem = {
      ...item,
      toast_id: `toast_${Date.now()}_${item.id}`,
      expires_at: sticky ? Number.POSITIVE_INFINITY : Date.now() + 8000,
    }
    toasts.value = [toast, ...toasts.value]
    if (!sticky) setTimeout(() => dismissToast(toast.toast_id), 8000)
  }

  /**
   * §bc3 T3.8 — server-emitted developer.notification_read from another
   * device/tab of the SAME developer. Just update local state — no API,
   * no cross-tab re-broadcast (we'd loop). The source device already
   * called /read.
   */
  function applyRemoteRead(broadcastId: number) {
    items.value = items.value.filter(i => i.id !== broadcastId)
    toasts.value = toasts.value.filter(t => t.id !== broadcastId)
    persistHistory(items.value)
  }

  /**
   * §bc1 T1.4 — server emitted broadcast.retracted: hard-remove from items
   * AND toasts (the retraction may concern an item that's still in the
   * toast stack). Cross-tab synced.
   */
  function retract(broadcastId: number, opts?: { skipCrossTab?: boolean }) {
    items.value = items.value.filter(i => i.id !== broadcastId)
    toasts.value = toasts.value.filter(t => t.id !== broadcastId)
    persistHistory(items.value)
    if (!opts?.skipCrossTab) emitCrossTab({ kind: 'retracted', broadcast_id: broadcastId })
  }

  /**
   * §bc1 T1.4 — server emitted broadcast.updated: patch the matching item
   * (and any visible toast) in place. Cross-tab synced.
   */
  function patchItem(payload: {
    broadcast_id: number
    title?: string
    body?: string
    broadcast_type?: BroadcastItem['broadcast_type']
  }, opts?: { skipCrossTab?: boolean }) {
    const id = payload.broadcast_id
    const patch: Partial<BroadcastItem> = {}
    if (payload.title !== undefined) patch.title = payload.title
    if (payload.body !== undefined) patch.body = payload.body
    if (payload.broadcast_type !== undefined) patch.broadcast_type = payload.broadcast_type
    items.value = items.value.map(i => (i.id === id ? { ...i, ...patch } : i))
    toasts.value = toasts.value.map(t => (t.id === id ? { ...t, ...patch } : t))
    persistHistory(items.value)
    if (!opts?.skipCrossTab) emitCrossTab({ kind: 'updated', broadcast_id: id, patch })
  }

  function dismissToast(toastId: string) {
    toasts.value = toasts.value.filter(t => t.toast_id !== toastId)
  }

  function dismissToastByBroadcastId(broadcastId: number) {
    toasts.value = toasts.value.filter(t => t.id !== broadcastId)
  }

  /**
   * §bc1 T1.3 — start listening for cross-tab read/retract/update events.
   * Idempotent; calling twice does nothing. Call once after store init.
   */
  function startCrossTabSync() {
    if (bcChannel || storageHandler) return
    try {
      if (typeof BroadcastChannel !== 'undefined') {
        bcChannel = new BroadcastChannel(BROADCAST_CHANNEL_NAME)
        bcChannel.onmessage = (e) => {
          const msg = e.data as CrossTabSyncMsg
          applyRemote(msg)
        }
      } else {
        storageHandler = (e: StorageEvent) => {
          if (e.key !== STORAGE_SYNC_KEY || !e.newValue) return
          try {
            const msg = JSON.parse(e.newValue) as CrossTabSyncMsg
            applyRemote(msg)
          } catch (err) {
            log.warn('storage-sync parse failed', err)
          }
        }
        window.addEventListener('storage', storageHandler)
      }
    } catch (e) {
      log.warn('startCrossTabSync failed', e)
    }
  }

  function stopCrossTabSync() {
    if (bcChannel) {
      try { bcChannel.close() } catch (_) { /* ignore */ }
      bcChannel = null
    }
    if (storageHandler) {
      window.removeEventListener('storage', storageHandler)
      storageHandler = null
    }
  }

  function applyRemote(msg: CrossTabSyncMsg) {
    if (msg.kind === 'read') {
      markRead(msg.broadcast_id, { skipCrossTab: true })
    } else if (msg.kind === 'retracted') {
      retract(msg.broadcast_id, { skipCrossTab: true })
    } else if (msg.kind === 'updated') {
      patchItem({ broadcast_id: msg.broadcast_id, ...msg.patch }, { skipCrossTab: true })
    }
  }

  function $reset() {
    unreadRetry.cancel()
    items.value = []
    feed.value = []
    toasts.value = []
    loading.value = false
    unreadFailed.value = false
    feedFailed.value = false
    lastReadAt.value = 0
    clearPersistedHistory()
    stopCrossTabSync()
  }

  return {
    items,
    feed,
    fetchFeed,
    markFeedRead,
    markAllFeedRead,
    toasts,
    loading,
    unreadFailed,
    feedFailed,
    lastReadAt,
    unreadCount,
    criticalItems,
    fetchUnread,
    markRead,
    markAllRead,
    addLiveNotification,
    retract,
    patchItem,
    applyRemoteRead,
    dismissToast,
    startCrossTabSync,
    stopCrossTabSync,
    $reset,
  }
})
