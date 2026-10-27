/**
 * WebSocket Service
 * Handles real-time communication with the backend
 */

import type { Ref } from 'vue'

export interface WebSocketMessage {
  type: string
  data: any
  timestamp: string
  id: string
}

export interface WebSocketConfig {
  url: string
  reconnect?: boolean
  reconnectInterval?: number
  maxReconnectAttempts?: number
  heartbeatInterval?: number
  /** §RELEASEHARDEN D2/D3 (2026-09-14) — read at EVERY connect, so a reconnect never carries the
   *  token the page loaded with. The manager used to open `new WebSocket(this.config.url)` with a URL
   *  built once at page load, token inside: after the access token's 90 minutes any registry restart
   *  reconnected with an expired token, the server answered 1008, and the dashboard logged the whole
   *  session out with no 401 anywhere (his session, twice, on 2026-09-14). */
  getToken?: () => string | null
  /** Asked ONCE per auth-refused close (1008) before giving up: resolve the fresh token, or null. */
  refreshToken?: () => Promise<string | null>
}

/** §RELEASEHARDEN D2 — the JWT rides the subprotocol list (`theprotocol.v1`, `theprotocol.bearer.<jwt>`),
 *  never the query string, which uvicorn writes into the container log. The server selects `theprotocol.v1`. */
export const WS_SUBPROTOCOL = 'theprotocol.v1'
export const WS_BEARER_PREFIX = 'theprotocol.bearer.'

export function wsProtocolsFor(token: string | null | undefined): string[] | undefined {
  return token ? [WS_SUBPROTOCOL, WS_BEARER_PREFIX + token] : undefined
}

export interface WebSocketEvents {
  'agent.update': (data: any) => void
  'agent.status': (data: any) => void
  'transaction.update': (data: any) => void
  'proposal.update': (data: any) => void
  'staking.reward': (data: any) => void
  'federation.sync': (data: any) => void
  'notification': (data: any) => void
  // §bc1 T1.4 — server-side broadcast lifecycle
  'broadcast.retracted': (data: { broadcast_id: number }) => void
  'broadcast.updated': (data: {
    broadcast_id: number
    title?: string
    body?: string
    broadcast_type?: string
  }) => void
  // §bc3 T3.8 — cross-device read sync (this dev marked X read elsewhere)
  'developer.notification_read': (data: {
    broadcast_id: number
    developer_id: number
    read_at: string | null
  }) => void
  // §bc4 T4.2 — this dev's org membership changed; client should re-fetch org_ids
  'developer.orgs.updated': (data: { developer_id: number }) => void
  /* §S6 — a support ticket moved. Sent to the OWNER (`user_<id>`) and to the
     DESK (`admin_support`), cross-worker through Redis. Deliberately NOT a
     'notification': it carries no words for a human, so it must not be gated
     by notification prefs or quiet hours, and must not raise a toast. It is a
     cue to re-read a list, nothing else. */
  'support.ticket': (data: {
    ticket_id: number
    event: 'created' | 'reply' | 'status' | 'triage'
    status: string
    priority: string
    category: string
    developer_id: number
  }) => void
  /* §COCKPIT §SHOWN — the liability cues. Deliberately NOT 'notification', for the
     same reason `support.ticket` above is not: notification prefs and quiet hours
     filter that type, and a muted human must still learn that something is waiting
     on their signature. These carry no words for a human — they are instructions to
     re-read a list. */
  'liability.cue': (data: {
    challenge_id: string
    action_type: string
    action_ref?: string | null
    auto_stepped_up?: boolean
  }) => void
  'liability.resolved': (data: {
    challenge_id: string
    status: 'approved' | 'denied'
    method?: string | null
    reason?: string | null
  }) => void
  /* §PREFLIGHT (P8) — an agent announcing what it is ABOUT to ask for. The emitter
     lands with that phase; the type is declared here so the one bus is typed from
     the start rather than cast at the boundary. */
  'liability.intent': (data: { action_ref: string; action_type: string }) => void
  'metrics.update': (data: any) => void
  'error': (error: Error) => void
  'connected': () => void
  'disconnected': () => void
  'reconnecting': (attempt: number) => void
  // §bc1 T1.2 — client-emitted: fired after a successful reconnect AFTER a
  // disconnect (NOT on initial connect). Subscribers should re-fetch
  // anything they might have missed during the partition window.
  'reconnected': () => void
  // §bc1 T1.8 — client-emitted: fired when the WS close-code is 1008
  // (policy violation, used by backend for expired JWT). Subscribers should
  // show an auth-expired toast and route to /login.
  'auth_expired': (data: { code: number; reason: string }) => void
}

export class WebSocketManager {
  private ws: WebSocket | null = null
  private config: Required<Omit<WebSocketConfig, 'getToken' | 'refreshToken'>> & Pick<WebSocketConfig, 'getToken' | 'refreshToken'>
  private reconnectAttempts = 0
  /** one refresh per refused connection: reset when a socket opens, so a token that is refused twice in
   *  a row ends the session instead of looping refresh → 1008 → refresh */
  private authRefreshTried = false
  private reconnectTimer: NodeJS.Timeout | null = null
  private heartbeatTimer: NodeJS.Timeout | null = null
  private listeners: Map<string, Set<Function>> = new Map()
  private messageQueue: WebSocketMessage[] = []
  private isReconnecting = false

  constructor(config: WebSocketConfig) {
    this.config = {
      url: config.url,
      reconnect: config.reconnect ?? true,
      reconnectInterval: config.reconnectInterval ?? 1000,
      maxReconnectAttempts: config.maxReconnectAttempts ?? 5,
      heartbeatInterval: config.heartbeatInterval ?? 30000,
      getToken: config.getToken,
      refreshToken: config.refreshToken,
    }
  }

  /**
   * Connect to WebSocket server
   */
  connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      try {
        // §WSRECONNECT (2026-08-20) — cleanup(), NOT disconnect().
        //
        // `disconnect()` is the USER-INITIATED stop: its first line is
        // `this.config.reconnect = false`, which is correct when a human leaves
        // the page and wrong here. Every retry routes through connect(), so
        // using disconnect() to swap the socket meant the FIRST reconnect
        // permanently disarmed auto-reconnect for the life of the manager.
        //
        // Measured live on the canary before this change, bouncing the registry
        // twice with a real browser attached: drop #1 reconnected (socket #2),
        // drop #2 opened nothing at all — the page sat with NO websocket until
        // it was reloaded. It also made 'Max reconnection attempts reached'
        // unreachable, so it never even reported giving up.
        //
        // cleanup() tears the socket down (timer, close, null, queue,
        // isReconnecting) and deliberately does NOT touch config.reconnect.
        if (this.ws) {
          this.cleanup()
        }

        // Create new WebSocket connection. §RELEASEHARDEN D2/D3: the token is read NOW (not at page
        // load) and offered as a subprotocol (not in the URL); a public socket offers none.
        const protocols = wsProtocolsFor(this.config.getToken?.() ?? null)
        this.ws = protocols ? new WebSocket(this.config.url, protocols) : new WebSocket(this.config.url)

        // Set up event handlers
        this.ws.onopen = () => {
          import.meta.env.DEV && console.log('[WebSocket] Connected')
          // §bc1 T1.2 — distinguish initial connect from reconnect. Subscribers
          // that need to re-hydrate state (notifications, etc.) listen on
          // 'reconnected' so they don't double-fetch on first login.
          const wasReconnect = this.reconnectAttempts > 0
          this.reconnectAttempts = 0
          this.isReconnecting = false
          this.authRefreshTried = false
          this.startHeartbeat()
          this.flushMessageQueue()
          this.emit('connected')
          if (wasReconnect) {
            this.emit('reconnected')
          }
          resolve()
        }

        this.ws.onmessage = (event: MessageEvent) => {
          try {
            const message: WebSocketMessage = JSON.parse(event.data)
            this.handleMessage(message)
          } catch (error) {
            console.error('[WebSocket] Failed to parse message:', error)
            this.emit('error', new Error('Failed to parse WebSocket message'))
          }
        }

        this.ws.onerror = (event: Event) => {
          console.error('[WebSocket] Error:', event)
          this.emit('error', new Error('WebSocket connection error'))
          reject(new Error('WebSocket connection error'))
        }

        this.ws.onclose = (event: CloseEvent) => {
          import.meta.env.DEV && console.log('[WebSocket] Disconnected:', event.code, event.reason)
          this.stopHeartbeat()
          this.emit('disconnected')

          // §bc1 T1.8 — close-code 1008 (policy violation) is what the backend
          // sends when the JWT is expired/invalid. Don't silently retry into a
          // 1008-loop; emit a dedicated event so the UI can toast + redirect
          // and the reconnect machinery can stand down for this session.
          if (event.code === 1008) {
            // §RELEASEHARDEN D3 (2026-09-14) — a refused token is first REFRESHED, once. The token this
            // socket carried may simply be older than the one the store holds (a restart after the
            // 90th minute); only when no fresh token can be had is the session over.
            if (this.config.refreshToken && !this.authRefreshTried && this.config.reconnect) {
              this.authRefreshTried = true
              const giveUp = () => {
                this.emit('auth_expired', { code: event.code, reason: event.reason || 'auth expired' })
                this.config.reconnect = false
              }
              this.config.refreshToken()
                .then((fresh) => { if (fresh) this.handleReconnect(); else giveUp() })
                .catch(() => giveUp())
              return
            }
            this.emit('auth_expired', { code: event.code, reason: event.reason || 'auth expired' })
            this.config.reconnect = false
            return
          }

          // Handle reconnection
          if (this.config.reconnect && !this.isReconnecting) {
            this.handleReconnect()
          }
        }
      } catch (error) {
        reject(error)
      }
    })
  }

  /**
   * Disconnect from WebSocket server
   */
  disconnect(): void {
    this.config.reconnect = false // Prevent auto-reconnect
    this.cleanup()
  }

  /**
   * Send a message through WebSocket
   */
  send(type: string, data: any): void {
    const message: WebSocketMessage = {
      type,
      data,
      timestamp: new Date().toISOString(),
      id: this.generateId()
    }

    if (this.isConnected) {
      try {
        this.ws!.send(JSON.stringify(message))
      } catch (error) {
        console.error('[WebSocket] Failed to send message:', error)
        this.messageQueue.push(message)
      }
    } else {
      // Queue message for later
      this.messageQueue.push(message)
    }
  }

  /**
   * Subscribe to WebSocket events
   */
  on<K extends keyof WebSocketEvents>(event: K, handler: WebSocketEvents[K]): void {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set())
    }
    this.listeners.get(event)!.add(handler as Function)
  }

  /**
   * Unsubscribe from WebSocket events
   */
  off<K extends keyof WebSocketEvents>(event: K, handler: WebSocketEvents[K]): void {
    const handlers = this.listeners.get(event)
    if (handlers) {
      handlers.delete(handler as Function)
    }
  }

  /**
   * Check if WebSocket is connected
   */
  get isConnected(): boolean {
    return this.ws !== null && this.ws.readyState === WebSocket.OPEN
  }

  /**
   * Get current connection state
   */
  get readyState(): number {
    return this.ws?.readyState ?? WebSocket.CLOSED
  }

  /**
   * Get reconnect attempts
   */
  get attempts(): number {
    return this.reconnectAttempts
  }

  /**
   * Handle incoming messages
   */
  private handleMessage(message: WebSocketMessage): void {
    // Handle heartbeat/pong messages
    if (message.type === 'pong') {
      return
    }

    // Emit message to specific event listeners
    this.emit(message.type as keyof WebSocketEvents, message.data)
  }

  /**
   * Emit event to listeners
   */
  private emit<K extends keyof WebSocketEvents>(
    event: K,
    ...args: Parameters<WebSocketEvents[K]>
  ): void {
    const handlers = this.listeners.get(event)
    if (handlers) {
      handlers.forEach(handler => {
        try {
          handler(...args)
        } catch (error) {
          console.error(`[WebSocket] Error in ${event} handler:`, error)
        }
      })
    }
  }

  /**
   * Handle reconnection logic
   */
  private handleReconnect(): void {
    if (this.reconnectAttempts >= this.config.maxReconnectAttempts) {
      console.error('[WebSocket] Max reconnection attempts reached')
      this.emit('error', new Error('Max reconnection attempts reached'))
      return
    }

    this.isReconnecting = true
    this.reconnectAttempts++
    
    const delay = this.config.reconnectInterval * this.reconnectAttempts
    import.meta.env.DEV && console.log(`[WebSocket] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`)
    
    this.emit('reconnecting', this.reconnectAttempts)

    this.reconnectTimer = setTimeout(() => {
      this.connect().catch(error => {
        console.error('[WebSocket] Reconnection failed:', error)
      })
    }, delay)
  }

  /**
   * Start heartbeat to keep connection alive
   */
  private startHeartbeat(): void {
    this.heartbeatTimer = setInterval(() => {
      if (this.isConnected) {
        this.send('ping', { timestamp: Date.now() })
      }
    }, this.config.heartbeatInterval)
  }

  /**
   * Stop heartbeat
   */
  private stopHeartbeat(): void {
    if (this.heartbeatTimer) {
      clearInterval(this.heartbeatTimer)
      this.heartbeatTimer = null
    }
  }

  /**
   * Flush queued messages
   */
  private flushMessageQueue(): void {
    while (this.messageQueue.length > 0 && this.isConnected) {
      const message = this.messageQueue.shift()!
      try {
        this.ws!.send(JSON.stringify(message))
      } catch (error) {
        console.error('[WebSocket] Failed to send queued message:', error)
        this.messageQueue.unshift(message) // Put it back
        break
      }
    }
  }

  /**
   * Clean up resources
   */
  private cleanup(): void {
    this.stopHeartbeat()

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    if (this.ws) {
      this.ws.onopen = null
      this.ws.onmessage = null
      this.ws.onerror = null
      this.ws.onclose = null
      
      if (this.ws.readyState === WebSocket.OPEN) {
        this.ws.close()
      }
      
      this.ws = null
    }

    this.messageQueue = []
    this.isReconnecting = false
  }

  /**
   * Generate unique ID
   */
  private generateId(): string {
    return Math.random().toString(36).substr(2, 9)
  }
}

// Default WebSocket instance
let defaultManager: WebSocketManager | null = null

/**
 * Get or create default WebSocket manager
 */
export function getWebSocketManager(config?: WebSocketConfig): WebSocketManager {
  if (!defaultManager && config) {
    defaultManager = new WebSocketManager(config)
  }
  
  if (!defaultManager) {
    throw new Error('WebSocket manager not initialized. Please provide config.')
  }
  
  return defaultManager
}

/**
 * Create a new WebSocket manager instance
 */
export function createWebSocketManager(config: WebSocketConfig): WebSocketManager {
  return new WebSocketManager(config)
}

/**
 * Reset default WebSocket manager
 */
export function resetWebSocketManager(): void {
  if (defaultManager) {
    defaultManager.disconnect()
    defaultManager = null
  }
}
