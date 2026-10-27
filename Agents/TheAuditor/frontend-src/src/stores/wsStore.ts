import { defineStore } from 'pinia'
import { ref } from 'vue'
import { useAuditorStore } from './auditorStore'

export const useWsStore = defineStore('ws', () => {
  const connected = ref(false)
  const reconnectAttempts = ref(0)
  let ws: WebSocket | null = null
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null
  let pingTimer: ReturnType<typeof setInterval> | null = null

  function getWsUrl(): string {
    const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${proto}//${window.location.host}/ws`
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
      return
    }

    const url = getWsUrl()
    ws = new WebSocket(url)

    ws.onopen = () => {
      connected.value = true
      reconnectAttempts.value = 0
      pingTimer = setInterval(() => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send('ping')
        }
      }, 30000)
    }

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        const auditorStore = useAuditorStore()

        switch (msg.type) {
          case 'connected':
            // Multi-frame welcome: msg.latest is { "frame-a": {...}, "frame-b": {...} }
            // The WS streams BOTH environments over one connection; keep the
            // store's frame list scoped to the mode the user is viewing, else the
            // welcome overwrites the mode-filtered fetchFrames() result with all
            // frames (prod + sandbox) → the dashboard renders 5 frames in a 3-frame
            // sandbox view. setMode()/fetchFrames re-scope on toggle.
            if (Array.isArray(msg.frames)) {
              auditorStore.frames = msg.frames.filter(
                (f: any) => !f.mode || f.mode === auditorStore.mode,
              )
            }
            if (msg.latest && typeof msg.latest === 'object') {
              auditorStore.handleWsLatestBatch(msg.latest)
            }
            if (msg.maintenance) {
              auditorStore.setMaintenance(msg.maintenance)
            }
            break
          case 'audit_result':
            if (msg.data) {
              auditorStore.handleWsAudit(msg.data, msg.frame || msg.data.frame || 'frame-a')
            }
            break
          case 'maintenance':
            if (msg.data) {
              auditorStore.setMaintenance(msg.data)
            }
            break
          case 'reset':
            // Open breaches were resolved server-side — refresh the derived views.
            auditorStore.fetchBreaches()
            auditorStore.fetchStats()
            break
          case 'pong':
            break
          default:
            break
        }
      } catch {
        // ignore parse errors
      }
    }

    ws.onclose = () => {
      connected.value = false
      cleanup()
      scheduleReconnect()
    }

    ws.onerror = () => {
      connected.value = false
    }
  }

  function cleanup() {
    if (pingTimer) {
      clearInterval(pingTimer)
      pingTimer = null
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    reconnectAttempts.value++
    const delay = Math.min(1000 * Math.pow(2, reconnectAttempts.value - 1), 30000)
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      connect()
    }, delay)
  }

  function disconnect() {
    cleanup()
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    connected.value = false
  }

  return { connected, reconnectAttempts, connect, disconnect }
})
