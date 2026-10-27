/**
 * EventStore WebSocket Service
 * Real-time event stream from the sandbox EventStore via WebSocket.
 * Connects to the sandbox event store via nginx proxy at /sandbox-ws/events.
 */

import { ref, type Ref } from 'vue'
import type { EventStoreEvent } from '../types/tutorial.types'

const MAX_EVENTS = 100
const RECONNECT_MAX = 5
const RECONNECT_BASE_MS = 2000
const PING_INTERVAL_MS = 30000

class EventStoreWebSocket {
  private ws: WebSocket | null = null
  private url: string
  private reconnectAttempts = 0
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private pingTimer: ReturnType<typeof setInterval> | null = null
  private listeners: Set<(event: EventStoreEvent) => void> = new Set()

  // Reactive state for Vue binding
  connected: Ref<boolean> = ref(false)
  events: Ref<EventStoreEvent[]> = ref([])
  connectionError: Ref<string | null> = ref(null)
  eventCount: Ref<number> = ref(0)

  constructor(url = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/sandbox-ws/events`) {
    this.url = url
  }

  connect(): void {
    if (this.ws && (this.ws.readyState === WebSocket.OPEN || this.ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    this.connectionError.value = null

    try {
      this.ws = new WebSocket(this.url)

      this.ws.onopen = () => {
        this.connected.value = true
        this.connectionError.value = null
        this.reconnectAttempts = 0
        // Subscribe to all events
        this.send({ action: 'subscribe', channel: 'events:all' })
        // Start keepalive
        this.startPing()
      }

      this.ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'event' && data.event) {
            const esEvent: EventStoreEvent = {
              id: data.event.id || '',
              event_type: data.event.event_type || 'unknown',
              aggregate_id: data.event.aggregate_id || '',
              data: data.event.data || {},
              timestamp: data.event.timestamp || '',
              version: data.event.version || 0,
              receivedAt: new Date().toISOString()
            }
            this.pushEvent(esEvent)
            this.listeners.forEach(fn => fn(esEvent))
          }
          // Silently ignore connected, subscription_confirmed, pong, stats
        } catch (e) {
          // Ignore unparseable messages
        }
      }

      this.ws.onclose = () => {
        this.connected.value = false
        this.stopPing()
        this.attemptReconnect()
      }

      this.ws.onerror = () => {
        this.connectionError.value = 'WebSocket connection failed'
        this.connected.value = false
      }
    } catch (e: any) {
      this.connectionError.value = e.message || 'Failed to create WebSocket'
      this.connected.value = false
    }
  }

  disconnect(): void {
    this.stopPing()
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.reconnectAttempts = RECONNECT_MAX // Prevent auto-reconnect
    if (this.ws) {
      this.ws.onclose = null // Prevent reconnect trigger
      this.ws.close()
      this.ws = null
    }
    this.connected.value = false
  }

  subscribe(channel: string): void {
    this.send({ action: 'subscribe', channel })
  }

  unsubscribe(channel: string): void {
    this.send({ action: 'unsubscribe', channel })
  }

  onEvent(callback: (event: EventStoreEvent) => void): () => void {
    this.listeners.add(callback)
    return () => this.listeners.delete(callback)
  }

  clearEvents(): void {
    this.events.value = []
    this.eventCount.value = 0
  }

  private send(data: Record<string, any>): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data))
    }
  }

  private pushEvent(event: EventStoreEvent): void {
    const list = this.events.value
    list.push(event)
    // Ring buffer — trim from front
    if (list.length > MAX_EVENTS) {
      list.splice(0, list.length - MAX_EVENTS)
    }
    this.eventCount.value++
  }

  private attemptReconnect(): void {
    if (this.reconnectAttempts >= RECONNECT_MAX) {
      this.connectionError.value = `Disconnected after ${RECONNECT_MAX} reconnect attempts`
      return
    }
    const delay = RECONNECT_BASE_MS * Math.pow(2, this.reconnectAttempts)
    this.reconnectAttempts++
    this.connectionError.value = `Reconnecting (${this.reconnectAttempts}/${RECONNECT_MAX})...`
    this.reconnectTimer = setTimeout(() => this.connect(), delay)
  }

  private startPing(): void {
    this.stopPing()
    this.pingTimer = setInterval(() => {
      this.send({ action: 'ping' })
    }, PING_INTERVAL_MS)
  }

  private stopPing(): void {
    if (this.pingTimer) {
      clearInterval(this.pingTimer)
      this.pingTimer = null
    }
  }
}

// Singleton instance
let _instance: EventStoreWebSocket | null = null

export function useEventStoreWebSocket(): EventStoreWebSocket {
  if (!_instance) {
    _instance = new EventStoreWebSocket()
  }
  return _instance
}

export function destroyEventStoreWebSocket(): void {
  if (_instance) {
    _instance.disconnect()
    _instance = null
  }
}
