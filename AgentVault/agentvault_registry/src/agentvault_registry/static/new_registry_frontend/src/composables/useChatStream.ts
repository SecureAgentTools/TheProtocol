/**
 * §OURSTATE-1 — the OurState realtime plane, client half.
 *
 * Rides the EXISTING WebSocket manager (`useWebSocket` → services/websocket),
 * never a second raw socket: the server subscribes every authenticated `/ws`
 * connection to its own `chat:dev:{id}` topic at connect, so the only client
 * work is registering handlers for the two envelope types and re-syncing after
 * a reconnect (delivery is at-most-once over a dropped socket; `/sync` is the
 * honest catch-up, and the `reconnected` event is exactly the hook §bc1 built
 * for re-hydration).
 *
 * Pocket runs OUTSIDE DashboardLayout, so this composable is the first (and
 * only) socket in the Pocket context. Must be called in a component setup()
 * (useWebSocket registers lifecycle hooks).
 */
import { useWebSocket } from '@/composables/useWebSocket'

export interface ChatEnvelope {
  conversation_id: string
  kind: string
  message: Record<string, any>
  sender_name?: string
}

export interface ChatStreamHandlers {
  onMessage?: (env: ChatEnvelope) => void
  onPing?: (env: ChatEnvelope) => void
  /** Fired after a RECONNECT — pull /sync; the socket has no memory. */
  onResync?: () => void
}

export function useChatStream(handlers: ChatStreamHandlers) {
  const ws = useWebSocket({ autoConnect: false, reconnect: true, enabled: true })

  const onMsg = (data: any) => { try { handlers.onMessage?.(data as ChatEnvelope) } catch { /* handler's problem */ } }
  const onPing = (data: any) => { try { handlers.onPing?.(data as ChatEnvelope) } catch { /* handler's problem */ } }
  const onReconnected = () => { try { handlers.onResync?.() } catch { /* handler's problem */ } }

  ws.on('chat.message' as any, onMsg)
  ws.on('chat.ping' as any, onPing)
  ws.on('reconnected' as any, onReconnected)

  // Best-effort: a failed connect degrades to polling via /sync — the views
  // never depend on the socket for correctness, only for immediacy.
  ws.connect().catch(() => { /* offline banner + /sync cover this */ })

  return {
    isConnected: ws.isConnected,
    disconnect: ws.disconnect,
  }
}
