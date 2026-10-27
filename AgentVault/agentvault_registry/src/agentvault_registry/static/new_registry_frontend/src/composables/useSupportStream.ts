/**
 * §S6 — the support desk's realtime plane, client half.
 *
 * `SupportView` mounted, called `loadTickets()` once, and then never learned
 * anything again: a reply from the other side sat invisible until somebody
 * reloaded the page by hand.
 *
 * ── Why this does NOT open its own socket ──────────────────────────────────
 * `useChatStream` calls `useWebSocket()` directly, and that is correct THERE
 * because Pocket runs outside `DashboardLayout` and owns the only socket in
 * its context. `SupportView` renders INSIDE `DashboardLayout`, which already
 * holds a connection and hands it to the realtime store.
 *
 * A second socket would not merely be wasteful, it would be destructive: the
 * server keys its registry by user, `active_connections[user_id] = websocket`
 * (`websocket.py:284`), so a second connection for the same developer REPLACES
 * the first. Opening the support view would silently orphan the dashboard's
 * socket — still open in the browser, no longer addressable by the server —
 * and closing the view would then delete the entry entirely, leaving that tab
 * with no realtime at all until a reload. So we subscribe through the socket
 * that already exists.
 *
 * ── The poll is the floor, the socket is the accelerator ───────────────────
 * `DashboardLayout` sets the store's socket inside an async block, so a view
 * that subscribes during its own setup can lose that race. The store now HOLDS
 * a handler registered before the instance exists and attaches it on arrival
 * (§S6, `stores/realtime.ts`) — but the view still polls on a slow
 * visibility-aware timer, because correctness should not depend on a socket at
 * all. A queue that is at most POLL_MS stale is a working queue; a queue that
 * depends on a race is one that is right on your machine and wrong on somebody
 * else's.
 *
 * ⚠ MEASURED, and it is why the store fix exists: with the old store the cue
 * arrived on the socket (proven by reading the frames off the wire) and the
 * handler never ran, so the poll was silently doing all the work and the view
 * looked live. An accelerator that has quietly stopped accelerating is
 * indistinguishable from one that never worked — unless you measure latency,
 * which is what `scratchpad/probe_support_ws_latency.mjs` is for.
 */
import { onUnmounted } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'

export interface SupportTicketCue {
  ticket_id: number
  event: 'created' | 'reply' | 'status' | 'triage'
  status: string
  priority: string
  category: string
  developer_id: number
}

export interface SupportStreamHandlers {
  /** Fired at most once per COALESCE_MS, however many cues arrived. */
  onChange?: (last: SupportTicketCue | null) => void
  /** Fired by the poll floor and when the tab is brought back to the front. */
  onPoll?: () => void
}

const COALESCE_MS = 400
const POLL_MS = 20000

export function useSupportStream(handlers: SupportStreamHandlers) {
  const realtime = useRealtimeStore()

  let coalesce: ReturnType<typeof setTimeout> | null = null
  let pending: SupportTicketCue | null = null
  let poll: ReturnType<typeof setInterval> | null = null

  function flush() {
    coalesce = null
    const cue = pending
    pending = null
    try { handlers.onChange?.(cue) } catch { /* handler's problem */ }
  }

  /* ⚠ Two cues can describe one event: on a single-operator registry the
     ticket owner IS the desk, so the server's `user_<id>` and `admin_support`
     broadcasts both land on this socket. Refreshing twice is harmless, but two
     refreshes racing each other are not — hence the trailing coalesce here,
     and the sequence guard in the view. */
  const onCue = (data: any) => {
    pending = (data || null) as SupportTicketCue | null
    if (coalesce) return
    coalesce = setTimeout(flush, COALESCE_MS)
  }

  /* One registration, no retry. The previous version looped "until registered",
     where registered meant `realtime.on()` did not throw — and it never throws.
     That is a check that cannot fail, and it reported success on the first
     attempt while nothing was attached. The store now queues instead. */
  realtime.on('support.ticket' as any, onCue as any)

  const onVisible = () => {
    if (!document.hidden) { try { handlers.onPoll?.() } catch { /* handler's problem */ } }
  }
  document.addEventListener('visibilitychange', onVisible)

  poll = setInterval(() => {
    // A background tab is not being read; it can catch up when it comes back.
    if (document.hidden) return
    try { handlers.onPoll?.() } catch { /* handler's problem */ }
  }, POLL_MS)

  onUnmounted(() => {
    if (coalesce) { clearTimeout(coalesce); coalesce = null }
    if (poll) { clearInterval(poll); poll = null }
    document.removeEventListener('visibilitychange', onVisible)
    try { realtime.off('support.ticket' as any, onCue as any) } catch { /* nothing to detach */ }
  })

  return { isConnected: () => realtime.isConnected }
}
