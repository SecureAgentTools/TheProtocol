/**
 * WebSocket Service Tests
 * Unit tests for the WebSocket implementation
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { WebSocketManager, createWebSocketManager } from '@/services/websocket'
import { MockWebSocket } from '../mocks/websocket-mocks'

// Mock WebSocket globally
global.WebSocket = MockWebSocket as any

describe('WebSocketManager', () => {
  let manager: WebSocketManager
  const testUrl = 'ws://localhost:8000/ws'
  
  beforeEach(() => {
    // 🔴 'should handle connection errors' REPLACES global.WebSocket with a
    // thrower and never puts it back, so every test declared after it built a
    // throwing socket and failed with "Connection failed" — 4 of them. The only
    // survivor was the one test that never calls connect(). Restore it here.
    global.WebSocket = MockWebSocket as any
    manager = createWebSocketManager({ url: testUrl })
  })
  
  afterEach(() => {
    vi.useRealTimers()
    manager.disconnect()
  })
  
  describe('Connection Management', () => {
    it('should connect to WebSocket server', async () => {
      await expect(manager.connect()).resolves.toBeUndefined()
      expect(manager.isConnected).toBe(true)
    })
    
    it('should disconnect from WebSocket server', async () => {
      await manager.connect()
      manager.disconnect()
      expect(manager.isConnected).toBe(false)
    })
    
    it('should emit connected event on successful connection', async () => {
      const connectedHandler = vi.fn()
      manager.on('connected', connectedHandler)
      
      await manager.connect()
      
      expect(connectedHandler).toHaveBeenCalled()
    })
    
    it('should handle connection errors', async () => {
      const errorHandler = vi.fn()
      manager.on('error', errorHandler)
      
      // Force connection error
      global.WebSocket = vi.fn(() => {
        throw new Error('Connection failed')
      }) as any
      
      await expect(manager.connect()).rejects.toThrow('Connection failed')
    })
  })
  
  describe('Message Handling', () => {
    it('should send messages when connected', async () => {
      await manager.connect()
      
      const type = 'test.message'
      const data = { foo: 'bar' }
      
      manager.send(type, data)
      
      // Check that WebSocket send was called
      const ws = (manager as any).ws as MockWebSocket
      expect(ws.send).toHaveBeenCalled()
      
      const sentMessage = JSON.parse(ws.send.mock.calls[0][0])
      expect(sentMessage.type).toBe(type)
      expect(sentMessage.data).toEqual(data)
    })
    
    it('should queue messages when disconnected', () => {
      const type = 'test.message'
      const data = { foo: 'bar' }
      
      manager.send(type, data)
      
      // Message should be queued
      expect((manager as any).messageQueue.length).toBe(1)
    })
    
    it('should handle incoming messages', async () => {
      const messageHandler = vi.fn()
      manager.on('agent.update', messageHandler)
      
      await manager.connect()
      
      const ws = (manager as any).ws as MockWebSocket
      ws.simulateMessage('agent.update', { agent_id: '123', status: 'active' })
      
      expect(messageHandler).toHaveBeenCalledWith({ agent_id: '123', status: 'active' })
    })
  })
  
  describe('Reconnection Logic', () => {
    it('should attempt to reconnect on disconnect', async () => {
      const reconnectingHandler = vi.fn()
      manager.on('reconnecting', reconnectingHandler)
      
      await manager.connect()
      const ws = (manager as any).ws as MockWebSocket
      
      // Simulate disconnect
      ws.simulateClose()
      
      // Wait for reconnection attempt
      await new Promise(resolve => setTimeout(resolve, 1100))
      
      expect(reconnectingHandler).toHaveBeenCalledWith(1)
    })
    
    it('should respect max reconnection attempts', async () => {
      // 🔴 This test could never reach its own condition. It closed the SAME
      // socket three times while MockWebSocket always reconnects SUCCESSFULLY,
      // and a successful open resets reconnectAttempts to 0 (index.ts). The
      // counter could not accumulate, so the error was unreachable — which is
      // also how it hid §WSRECONNECT (connect() calling disconnect(), disarming
      // config.reconnect after the first retry).
      //
      // To exercise a CAP on retries the retries have to FAIL. This socket
      // never opens and closes itself, so each attempt genuinely fails.
      class FailingWebSocket {
        static OPEN = 1
        static CLOSED = 3
        onopen: ((e: any) => void) | null = null
        onmessage: ((e: any) => void) | null = null
        onerror: ((e: any) => void) | null = null
        onclose: ((e: any) => void) | null = null
        readyState = 3
        send = vi.fn()
        close = vi.fn()
        constructor() {
          setTimeout(() => this.onclose?.({ code: 1006, reason: 'refused' }), 0)
        }
      }

      manager = createWebSocketManager({
        url: testUrl,
        maxReconnectAttempts: 2,
        reconnectInterval: 20
      })
      
      const errorHandler = vi.fn()
      manager.on('error', errorHandler)
      
      await manager.connect()
      const ws = (manager as any).ws as MockWebSocket
      
      // From here every reconnect attempt fails, so the counter can climb.
      global.WebSocket = FailingWebSocket as any
      ws.simulateClose()
      await new Promise(resolve => setTimeout(resolve, 500))
      
      expect(errorHandler).toHaveBeenCalledWith(
        expect.objectContaining({ message: 'Max reconnection attempts reached' })
      )
    })
  })
  
  describe('Event Handling', () => {
    it('should subscribe and unsubscribe to events', async () => {
      const handler = vi.fn()
      
      manager.on('notification', handler)
      await manager.connect()
      
      const ws = (manager as any).ws as MockWebSocket
      ws.simulateMessage('notification', { title: 'Test', message: 'Hello' })
      
      expect(handler).toHaveBeenCalledTimes(1)
      
      // Unsubscribe
      manager.off('notification', handler)
      ws.simulateMessage('notification', { title: 'Test 2', message: 'Hello 2' })
      
      expect(handler).toHaveBeenCalledTimes(1)
    })
  })
  
  describe('Heartbeat', () => {
    it('should send heartbeat messages', async () => {
      // 🔴 The original installed fake timers and THEN awaited connect().
      // MockWebSocket fires onopen from setTimeout(..., 0), which fake timers
      // freeze, so connect() never resolved and the test timed out at 5s.
      // Installing them AFTER connect is equally wrong in the mirror image:
      // startHeartbeat() runs inside onopen, so its setInterval would be a REAL
      // timer that advancing fake ones cannot reach. Fake from the start, then
      // advance to let onopen through.
      vi.useFakeTimers()
      
      manager = createWebSocketManager({
        url: testUrl,
        heartbeatInterval: 1000
      })
      
      const opening = manager.connect()
      await vi.advanceTimersByTimeAsync(1)      // let the mock's onopen fire
      await opening
      const ws = (manager as any).ws as MockWebSocket
      ws.send.mockClear()                        // ignore anything sent on open
      
      await vi.advanceTimersByTimeAsync(1100)
      
      expect(ws.send).toHaveBeenCalledWith(
        expect.stringContaining('"type":"ping"')
      )
      
      vi.useRealTimers()
    })
  })
})
