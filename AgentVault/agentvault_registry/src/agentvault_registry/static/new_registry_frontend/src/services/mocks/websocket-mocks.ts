/**
 * WebSocket mock for unit tests.
 * Provides a MockWebSocket class that simulates browser WebSocket behaviour.
 */

import { vi } from 'vitest'

export class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  readyState: number = MockWebSocket.OPEN
  url: string
  protocols: string | string[]

  onopen: ((event: any) => void) | null = null
  onmessage: ((event: any) => void) | null = null
  onerror: ((event: any) => void) | null = null
  onclose: ((event: any) => void) | null = null

  send = vi.fn()
  close = vi.fn()

  constructor(url: string, protocols?: string | string[]) {
    this.url = url
    this.protocols = protocols || []

    // Simulate async open
    setTimeout(() => {
      if (this.onopen) {
        this.onopen({ type: 'open', target: this })
      }
    }, 0)
  }

  /** Helper: fire a message event with the given type and data payload */
  simulateMessage(type: string, data: any) {
    if (this.onmessage) {
      this.onmessage({
        type: 'message',
        data: JSON.stringify({ type, data, timestamp: new Date().toISOString(), id: Math.random().toString(36).slice(2) }),
        target: this
      })
    }
  }

  /** Helper: simulate a server-initiated close */
  simulateClose(code = 1006, reason = 'Simulated close') {
    this.readyState = MockWebSocket.CLOSED
    if (this.onclose) {
      this.onclose({ type: 'close', code, reason, wasClean: false, target: this })
    }
  }

  /** Helper: simulate an error */
  simulateError(message = 'Simulated error') {
    if (this.onerror) {
      this.onerror({ type: 'error', message, target: this })
    }
  }
}
