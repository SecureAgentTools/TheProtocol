/**
 * §COCKPIT P1 (2026-08-31) — the desk's ONE subscription.
 *
 * 🔴 THE RULE THIS FILE EXISTS TO ENFORCE: the desk never opens a WebSocket.
 * It borrows the single connection `DashboardLayout` already builds and hands
 * to `stores/realtime`. Panes subscribe HERE; the bus holds exactly one handler
 * per event type against the store, no matter how many panes want it, and
 * removes it when the last one leaves.
 *
 * Why a bus rather than each pane calling `realtimeStore.on` itself: twelve
 * panes on one event would register twelve handlers on one socket, and Vue
 * gives you no way to notice that from the outside — the symptom is a pane
 * doing its work N times, which looks like a backend fan-out bug. The battery
 * asserts ONE socket; this asserts one handler.
 *
 * The store's `on()` records handlers registered before the socket exists and
 * attaches them when it arrives (§SUPPORTBATCH1), so mount order is not a race.
 */
import { onMounted, onUnmounted } from 'vue'
import { useRealtimeStore } from '@/stores/realtime'

export type CockpitEvent =
  | 'liability.cue'        // a decision was raised (minted) for this developer
  | 'liability.resolved'   // a decision was approved or denied
  | 'liability.intent'     // §PREFLIGHT: an agent announced what it is about to ask for

type Handler = (data: any) => void

const subs = new Map<CockpitEvent, Set<Handler>>()
const attached = new Map<CockpitEvent, Handler>()

function ensureAttached(evt: CockpitEvent) {
  if (attached.has(evt)) return
  const store = useRealtimeStore()
  const fanout: Handler = (data: any) => {
    for (const h of subs.get(evt) ?? []) {
      // One bad subscriber must not silence the others.
      try { h(data) } catch { /* a pane's handler is its own problem */ }
    }
  }
  attached.set(evt, fanout)
  store.on(evt as any, fanout as any)
}

function releaseIfEmpty(evt: CockpitEvent) {
  if ((subs.get(evt)?.size ?? 0) > 0) return
  const fanout = attached.get(evt)
  if (!fanout) return
  try { useRealtimeStore().off(evt as any, fanout as any) } catch { /* store may be torn down */ }
  attached.delete(evt)
}

/**
 * Subscribe for the lifetime of the calling component. Registration and
 * teardown are bound to mount/unmount, so a pane cannot leak a handler by
 * forgetting to clean up — the shape §BRIDGE R7-B's second-writer lesson asks for.
 */
export function useCockpitBus(handlers: Partial<Record<CockpitEvent, Handler>>) {
  const entries = Object.entries(handlers) as [CockpitEvent, Handler][]
  onMounted(() => {
    for (const [evt, h] of entries) {
      if (!subs.has(evt)) subs.set(evt, new Set())
      subs.get(evt)!.add(h)
      ensureAttached(evt)
    }
  })
  onUnmounted(() => {
    for (const [evt, h] of entries) {
      subs.get(evt)?.delete(h)
      releaseIfEmpty(evt)
    }
  })
}

/** Test/inspection hook — how many handlers has the bus put on the shared socket? */
export function _cockpitBusAttached(): number { return attached.size }
