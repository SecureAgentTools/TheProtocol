/**
 * V0652 (ag) (order gwo_647f50fd40c19f6f685d0c8e): the thread's catch-up, wired to the page. The tab coming back, the
 * window's focus and the socket coming back each catch the thread up from its last seq (one run at a time); while the
 * socket is down the thread keeps itself current with the long-poll (GET /chat/sync?wait=25, V0650 (g)) instead of
 * going quiet, and stops when the socket is back. The marker's state (live, catching up, offline) comes with it.
 * Must be called in a component setup().
 */
import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from 'vue'
import { catchUpCause, liveState, pollRetry } from '@/services/chat/catchUp'

/** How long a socket may take to come up before the long-poll starts (a page load connects in well under this). */
export const POLL_GRACE_MS = 3000
/** The least time between two long-poll calls when one answered at once (nothing waited). */
export const POLL_FLOOR_MS = 3000

export function useThreadCatchUp(o: {
  connected: Ref<boolean>
  /** Fetch what this thread missed and merge it (the thread's own read). */
  catchUp: () => Promise<void>
  /** One long-poll call: resolves when the server answered (something new, or nothing at its bound). */
  longPollOnce: () => Promise<void>
}) {
  const catching = ref(false)
  let inflight: Promise<void> | null = null
  let polling = false
  let alive = true
  let grace: ReturnType<typeof setTimeout> | null = null

  function catchUpNow(): Promise<void> {
    if (inflight) return inflight
    catching.value = true
    inflight = o.catchUp().catch(() => { /* the next cause tries again; the marker says offline if it stays down */ })
      .finally(() => { catching.value = false; inflight = null })
    return inflight
  }

  function onEvent(ev: Event) {
    if (catchUpCause({ type: ev.type, visibilityState: document.visibilityState })) void catchUpNow()
  }

  async function pollLoop() {
    if (polling) return
    polling = true
    let attempt = 0
    try {
      while (alive && !o.connected.value) {
        const t0 = Date.now()
        try {
          await o.longPollOnce()
          attempt = 0
        } catch (e: any) {
          // 401/403 end the loop (signing in is the app's); 429/503 wait their Retry-After; the rest back off
          const next = pollRetry(e, attempt++)
          if (next.stop) break
          await new Promise((r) => setTimeout(r, next.delayMs))
          continue
        }
        // a floor between calls: a registry before V0650 ignores `wait` and answers at once, and nothing may spin
        if (Date.now() - t0 < POLL_FLOOR_MS) await new Promise((r) => setTimeout(r, POLL_FLOOR_MS))
      }
    } finally { polling = false }
  }

  function pollSoon() {
    if (grace) clearTimeout(grace)
    grace = setTimeout(() => { grace = null; if (alive && !o.connected.value) void pollLoop() }, POLL_GRACE_MS)
  }

  watch(o.connected, (now, before) => {
    if (now && before === false) void catchUpNow()
    if (!now) pollSoon()
  })
  onMounted(() => {
    document.addEventListener('visibilitychange', onEvent)
    window.addEventListener('focus', onEvent)
    if (!o.connected.value) pollSoon()
  })
  onBeforeUnmount(() => {
    alive = false
    if (grace) clearTimeout(grace)
    document.removeEventListener('visibilitychange', onEvent)
    window.removeEventListener('focus', onEvent)
  })

  const state = computed(() => liveState({ connected: o.connected.value, catching: catching.value }))
  return { state, catchUpNow }
}
