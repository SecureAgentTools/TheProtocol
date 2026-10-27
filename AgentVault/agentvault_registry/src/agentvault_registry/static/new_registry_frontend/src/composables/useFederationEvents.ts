/**
 * useFederationEvents — WebSocket subscription for federation state changes.
 *
 * 2026-05-06 audit T6 — replaces 60s polling latency with sub-second push updates.
 * Subscribes to the EventStore WebSocket gateway at `/ws/events` (same endpoint
 * MissionControl uses; verified canonical pattern). Filters incoming events to
 * the federation-relevant set, then triggers a debounced caller-supplied
 * refresh function (typically `loadTopology`).
 *
 * Design notes:
 *   - Raw WebSocket (not the WebSocketManager class) — matches MissionControl's
 *     proven pattern. The `/ws/events` endpoint accepts `{action:'subscribe',
 *     channel:'events:all'}` immediately on open and emits `{type:'event',
 *     data:{event_type, aggregate_id, ...}}` messages.
 *   - Exponential backoff reconnect (250ms → 8s, 1.5x).
 *   - Debounced refresh (500ms) so a burst of related events triggers ONE
 *     topology fetch, not N.
 *   - Composable lifecycle: connects on mount, disposes on unmount.
 *   - Pure additive — does NOT replace existing 60s polling. WS is faster
 *     when connected, polling is the safety net when WS is down.
 */
import { ref, onMounted, onUnmounted } from 'vue'
import { FRAMES } from '@/config/frames'

// Federation event types we care about. Drives topology refresh on push.
// §pass62.1 (2026-05-21) — exported so views can backfill via `GET /admin/events`
// on mount, keeping the LiveFederationFeed populated even when the live stream
// is quiet (steady-state federation may go hours between drift/quarantine events).
export const FEDERATION_EVENT_TYPES = new Set<string>([
  'FederationStateDriftDetected',
  'ComplianceDryRunDrift',
  'RegistryFederated',
  'RegistryQuarantined',
  'PeerRegistryDeactivated',
  'PeerRegistryReactivated',
  'PeerTopologyRefreshed',
  'FederationLicenseSuspended',
  'FederationLicenseRevoked',
  'FederationLicenseReinstated',
  'FederationLicenseGenerated',
  'FederationPolicyUpdated',
  'OperatorApplicationRevoked',
  'OperatorApplicationApproved',
  'OperatorApplicationActivated',
  'FrameFederationRevoked',
  'FrameInvitationCreated',
  'FrameInvitationApproved',
  'CrossRegistryBlockedBySuspension',
  // §pass-N (2026-05-21) — added for Federation Network edge-flash + live feed.
  'PeerRegistryUrlAutoCorrected',
])

export interface UseFederationEventsOptions {
  onRefresh: () => void | Promise<void>     // called (debounced) when a federation event arrives
  // Optional per-event callback. Receives event_type AND the full payload so
  // subscribers can target side-effects (e.g., edge-flash on a specific peer).
  onLiveEvent?: (eventType: string, payload?: any) => void
  debounceMs?: number                       // default 500
  enabled?: () => boolean                   // optional gate (e.g., () => authStore.isAdmin)
  // §FX Phase-3 (2026-06-02): explicit ES WS endpoint, so a view can stream a
  // SPECIFIC frame's EventStore (e.g. Frame C) instead of only the local one.
  // When omitted, falls back to the local-frame default (unchanged behavior).
  // NOTE: cross-frame/cross-origin ES WS reachability from one registry origin
  // is a backend/proxy concern (see backlog) — a stream that can't connect simply
  // stays disconnected + polling covers it; it never crashes the view.
  endpoint?: string
}

export interface UseFederationEventsReturn {
  isConnected: ReturnType<typeof ref<boolean>>
  lastEventAt: ReturnType<typeof ref<Date | null>>
  lastEventType: ReturnType<typeof ref<string>>
  eventCount: ReturnType<typeof ref<number>>
}

export function useFederationEvents(options: UseFederationEventsOptions): UseFederationEventsReturn {
  const debounceMs = options.debounceMs ?? 500
  const isConnected = ref(false)
  const lastEventAt = ref<Date | null>(null)
  const lastEventType = ref<string>('')
  const eventCount = ref(0)

  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let refreshTimer: ReturnType<typeof setTimeout> | null = null
  let reconnectDelay = 250
  let stopped = false

  function scheduleRefresh() {
    if (refreshTimer) clearTimeout(refreshTimer)
    refreshTimer = setTimeout(() => {
      Promise.resolve(options.onRefresh()).catch(() => { /* swallow */ })
      refreshTimer = null
    }, debounceMs)
  }

  function buildUrl(): string {
    // Explicit per-frame endpoint wins (Phase-3 multi-frame streaming).
    if (options.endpoint) return options.endpoint
    // §FEFRAME W2: this console's own frame's ledger from the frame manifest (FRAMES[0]; an operator: its parent's),
    // never the same-origin /ws/events, which on the apex was the retired Frame A store.
    const own = FRAMES[0]
    if (own?.es?.absoluteWsUrl) return own.es.absoluteWsUrl
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    // §2026-06-03 — always same-origin: a localhost branch hit ws://host:8200 directly
    // (ES port), which the browser CORS/connection-blocks from the registry origin.
    // The registry serves /ws/events same-origin (sandbox is reached via localhost too).
    return `${proto}//${window.location.host}/ws/events`
  }

  // §FINDFIX F3 — a handshake the server REFUSES (Starlette closes an unmatched
  // WS path with 403; the browser can only see "handshake failed") is terminal,
  // not transient: on origins with no /ws/events proxy (direct registry ports,
  // dev/probe contexts) the old backoff retried forever at ~1 err/s of console
  // noise. After N consecutive attempts that never reached onopen, PARK the
  // stream — the view's 60s polling is the designed safety net, and a remount
  // (navigation back to the view) tries again fresh. A connection that ever
  // opened resets the counter, so real outages keep the full retry behaviour.
  let neverOpenedStreak = 0
  const PARK_AFTER = 10

  function connect() {
    if (stopped) return
    if (options.enabled && !options.enabled()) return  // gate
    try {
      ws = new WebSocket(buildUrl())
    } catch {
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      isConnected.value = true
      reconnectDelay = 250
      neverOpenedStreak = 0
      try {
        ws?.send(JSON.stringify({ action: 'subscribe', channel: 'events:all' }))
      } catch { /* connection already torn down */ }
    }

    ws.onmessage = (msg: MessageEvent) => {
      let envelope: any
      try { envelope = JSON.parse(msg.data) } catch { return }
      if (envelope?.type !== 'event') return
      // EventStore emits {type:'event', event:{event_type, ...}} (verified live 2026-05-21).
      // Registry's own manager.broadcast emits {type:'event', data:{event_type, ...}}.
      // Accept both keys — `event` for ES, `data` for registry direct.
      const inner = envelope.event || envelope.data || envelope
      const evtType = inner.event_type || inner.type || (inner.data && inner.data.event_type)
      if (!evtType || typeof evtType !== 'string') return
      if (!FEDERATION_EVENT_TYPES.has(evtType)) return
      eventCount.value++
      lastEventAt.value = new Date()
      lastEventType.value = evtType
      // Pass payload (inner.data when nested, else inner) to subscribers — Pass 4
      // edge-flash needs peer_id to know which edge to highlight.
      const payload = (inner.data && typeof inner.data === 'object') ? inner.data : inner
      try { options.onLiveEvent?.(evtType, payload) } catch { /* swallow */ }
      scheduleRefresh()
    }

    ws.onclose = () => {
      const opened = isConnected.value
      isConnected.value = false
      ws = null
      if (stopped) return
      if (!opened) {
        neverOpenedStreak++
        if (neverOpenedStreak >= PARK_AFTER) {
          // eslint-disable-next-line no-console
          console.info('[federation-events] live stream unavailable on this origin — parked; polling continues')
          return
        }
      }
      scheduleReconnect()
    }

    ws.onerror = () => {
      // onclose will fire next; reconnect handled there
    }
  }

  function scheduleReconnect() {
    if (stopped) return
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 1.5, 8000)
      connect()
    }, reconnectDelay)
  }

  function disconnect() {
    stopped = true
    if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
    if (refreshTimer) { clearTimeout(refreshTimer); refreshTimer = null }
    try { ws?.close(1000, 'unmount') } catch { /* ignore */ }
    ws = null
    isConnected.value = false
  }

  onMounted(() => connect())
  onUnmounted(() => disconnect())

  return { isConnected, lastEventAt, lastEventType, eventCount }
}
