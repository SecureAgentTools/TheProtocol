/**
 * useWebSocket Composable
 * Vue 3 composable for WebSocket management
 */

import { ref, computed, onMounted, onUnmounted, type Ref } from 'vue'
import { readAccessToken } from '@/services/accessToken'
import { useAuthStore } from '@/stores/auth'
import { useUIStore } from '@/stores/ui'
import { authService } from '@/services/auth'
import {
  WebSocketManager,
  createWebSocketManager,
  type WebSocketConfig,
  type WebSocketEvents
} from '@/services/websocket'
import { useLogger } from './useLogger'

const log = useLogger('useWebSocket')

export interface UseWebSocketOptions {
  autoConnect?: boolean
  reconnect?: boolean
  heartbeatInterval?: number
  enabled?: boolean  // New flag to enable/disable WebSocket
}

export interface UseWebSocketReturn {
  // State
  isConnected: Ref<boolean>
  isReconnecting: Ref<boolean>
  reconnectAttempts: Ref<number>
  lastError: Ref<Error | null>
  
  // Methods
  connect: () => Promise<void>
  disconnect: () => void
  send: (type: string, data: any) => void
  on: <K extends keyof WebSocketEvents>(event: K, handler: WebSocketEvents[K]) => void
  off: <K extends keyof WebSocketEvents>(event: K, handler: WebSocketEvents[K]) => void
}

/**
 * Vue composable for WebSocket management
 */
export function useWebSocket(options: UseWebSocketOptions = {}): UseWebSocketReturn {
  // Stores
  const authStore = useAuthStore()
  const uiStore = useUIStore()
  
  // WebSocket manager instance
  let manager: WebSocketManager | null = null

  /* §S6 — SUBSCRIBING BEFORE `connect()` USED TO SILENTLY DO NOTHING.
     `manager` is created inside `connect()`, and `on()` began with
     `if (!manager) { log.warn('Cannot subscribe: not initialized'); return }`.
     Every consumer that registers its handlers at setup and connects
     afterwards — which is the natural order, and the order `useChatStream`
     uses — had its handlers dropped on the floor with a console warning and no
     other symptom: the socket connects, the view looks alive, and no event
     ever reaches a handler.
     The registry below is the source of truth. Handlers are recorded whether
     or not a manager exists yet and are (re)attached every time one is
     created, so a `disconnect()` / `connect()` cycle restores them too. */
  const handlerRegistry: Array<[string, any]> = []
  
  // Reactive state
  const isConnected = ref(false)
  const isReconnecting = ref(false)
  const reconnectAttempts = ref(0)
  const lastError = ref<Error | null>(null)
  
  /**
  * Build the WebSocket URL. §RELEASEHARDEN D2 (2026-09-14): the URL carries NO token any more. The
  * token is handed to the manager as `getToken`, read at every connect and offered as a subprotocol,
  * so it is neither written to an access log nor frozen at page load (the D3 self-logout).
  */
function buildWebSocketUrl(): string {
  // Check if custom WebSocket URL is configured
  const customWsUrl = import.meta.env.VITE_WS_URL
  if (customWsUrl) {
    const url = new URL(customWsUrl)
    log.info('Using custom WebSocket URL:', url.toString())
    return url.toString()
  }

  // Default: build from current location
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.host
  const url = new URL(`${protocol}//${host}/api/v1/ws`)
  log.info('Built WebSocket URL:', url.toString())
  return url.toString()
}

/** The token the manager offers on EVERY connect (the store first, the legacy storage key second). */
function currentToken(): string | null {
  return authStore.token || readAccessToken()
}

/** Asked by the manager once per refused (1008) connection: refresh through the auth service, mirror
 *  the new access token into the store (the response interceptor does the same on a 401), or null. */
async function refreshTokenForSocket(): Promise<string | null> {
  try {
    const tokens = await authService.refreshAccessToken()
    if (tokens?.access_token) {
      authStore.token = tokens.access_token
      return tokens.access_token
    }
  } catch (err) {
    log.warn('socket token refresh failed', err)
  }
  return null
}
  
  /**
   * Connect to WebSocket server
   */
  async function connect(): Promise<void> {
    try {
      // Check if WebSocket is enabled
      if (options.enabled === false) {
        log.info('WebSocket is disabled')
        return
      }
      
      // Don't connect if already connected
      if (manager?.isConnected) {
        return
      }
      
      // Check if we have a token
      const token = currentToken()
      if (!token) {
        log.warn('Skipping WebSocket connection - no authentication token')
        return
      }

      // Create WebSocket manager if not exists
      if (!manager) {
        const config: WebSocketConfig = {
          url: buildWebSocketUrl(),
          reconnect: options.reconnect ?? true,
          heartbeatInterval: options.heartbeatInterval ?? 30000,
          getToken: currentToken,
          refreshToken: refreshTokenForSocket,
        }
        
        manager = createWebSocketManager(config)
        
        // Set up event handlers
        setupEventHandlers()

        // Attach everything that subscribed before this manager existed.
        for (const [event, handler] of handlerRegistry) {
          manager.on(event as any, handler)
        }
      }
      
      // Connect
      await manager.connect()
      
    } catch (error) {
      console.error('[useWebSocket] Connection failed:', error)
      lastError.value = error as Error
      
      // Only show notification if WebSocket is expected to work
      if (options.enabled !== false) {
        uiStore.showNotification({
          type: 'error',
          title: 'Connection Failed',
          message: 'Failed to establish WebSocket connection'
        })
      }
      throw error
    }
  }
  
  /**
   * Disconnect from WebSocket server
   */
  function disconnect(): void {
    if (manager) {
      manager.disconnect()
      manager = null
    }
    
    isConnected.value = false
    isReconnecting.value = false
    reconnectAttempts.value = 0
  }
  
  /**
   * Send message through WebSocket
   */
  function send(type: string, data: any): void {
    if (!manager) {
      log.warn('Cannot send message: not connected')
      return
    }
    
    manager.send(type, data)
  }
  
  /**
   * Subscribe to WebSocket events
   */
  function on<K extends keyof WebSocketEvents>(
    event: K, 
    handler: WebSocketEvents[K]
  ): void {
    // Record first: a handler must survive being registered before connect,
    // and must be re-attached if the manager is ever rebuilt.
    handlerRegistry.push([event as string, handler])
    manager?.on(event, handler)
  }
  
  /**
   * Unsubscribe from WebSocket events
   */
  function off<K extends keyof WebSocketEvents>(
    event: K, 
    handler: WebSocketEvents[K]
  ): void {
    const i = handlerRegistry.findIndex(([e, h]) => e === (event as string) && h === handler)
    if (i >= 0) handlerRegistry.splice(i, 1)
    manager?.off(event, handler)
  }
  
  /**
   * Set up WebSocket event handlers
   */
  function setupEventHandlers(): void {
    if (!manager) return
    
    // Connection events
    manager.on('connected', () => {
      isConnected.value = true
      isReconnecting.value = false
      reconnectAttempts.value = 0
      lastError.value = null
      
      uiStore.showNotification({
        type: 'success',
        title: 'Connected',
        message: 'Real-time connection established'
      })
    })
    
    manager.on('disconnected', () => {
      isConnected.value = false
    })
    
    manager.on('reconnecting', (attempt: number) => {
      isReconnecting.value = true
      reconnectAttempts.value = attempt
    })
    
    manager.on('error', (error: Error) => {
      lastError.value = error
      
      // Only show error notification if not reconnecting
      if (!isReconnecting.value) {
        uiStore.showNotification({
          type: 'error',
          title: 'Connection Error',
          message: error.message
        })
      }
    })
    
    // Handle notifications
    manager.on('notification', (data: any) => {
      uiStore.showNotification({
        type: data.type || 'info',
        title: data.title,
        message: data.message
      })
    })
  }
  
  // Auto-connect on mount if enabled and authenticated
  onMounted(async () => {
    if (options.autoConnect && authStore.isAuthenticated) {
      try {
        await connect()
      } catch (error) {
        // Error already handled in connect()
      }
    }
  })
  
  // Clean up on unmount
  onUnmounted(() => {
    disconnect()
  })
  
  return {
    // State
    isConnected: computed(() => isConnected.value),
    isReconnecting: computed(() => isReconnecting.value),
    reconnectAttempts: computed(() => reconnectAttempts.value),
    lastError: computed(() => lastError.value),
    
    // Methods
    connect,
    disconnect,
    send,
    on,
    off
  }
}

/**
 * Global WebSocket composable with auto-connect
 */
export function useGlobalWebSocket(): UseWebSocketReturn {
  return useWebSocket({
    autoConnect: true,
    reconnect: true,
    enabled: true  // ENABLED - backend WebSocket is implemented!
  })
}
