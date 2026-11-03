/**
 * V0655 (az) (order gwo_16a6212cd90dbe18baa3537c): only a visible page counts as present. The registry holds a notice
 * back while you are "in the app" (presence:ws); a hidden tab or a phone in a pocket kept that presence alive with its
 * heartbeat, so the notices of the sessions' asks never came. The heartbeat now says whether its page is visible, and a
 * page that is shown or hidden says so at once. The console and Pocket share this socket (useWebSocket).
 * BASE (V0654): the heartbeat carries no visible field and a change of visibility sends nothing.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { WebSocketManager, pageVisible } from './index'

class FakeWS {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWS[] = []
  readyState = 0
  sent: any[] = []
  onopen: null | (() => void) = null
  onmessage: null | ((e: any) => void) = null
  onerror: null | ((e: any) => void) = null
  onclose: null | ((e: { code: number; reason: string }) => void) = null
  constructor(public url: string, public protocols?: string[]) { FakeWS.instances.push(this) }
  send(raw: string) { this.sent.push(JSON.parse(raw)) }
  close() { this.readyState = 3 }
  open() { this.readyState = 1; this.onopen?.() }
}

let state: 'visible' | 'hidden' = 'visible'
const pings = (ws: FakeWS) => ws.sent.filter((m) => m.type === 'ping').map((m) => m.data)

beforeEach(() => {
  FakeWS.instances = []
  ;(globalThis as any).WebSocket = FakeWS
  state = 'visible'
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state })
  vi.useFakeTimers()
})
afterEach(() => { vi.useRealTimers() })

async function connected() {
  const m = new WebSocketManager({ url: 'wss://frame.example/api/v1/ws', getToken: () => 'tok', heartbeatInterval: 30000 })
  const p = m.connect().catch(() => {})
  FakeWS.instances[0].open()
  await p
  return { m, ws: FakeWS.instances[0] }
}

describe('the heartbeat says whether its page is visible', () => {
  it('a visible page says so with each heartbeat', async () => {
    const { m, ws } = await connected()
    await vi.advanceTimersByTimeAsync(30000)
    expect(pings(ws)).toHaveLength(1)
    expect(pings(ws)[0]).toMatchObject({ visible: true })
    expect(typeof pings(ws)[0].timestamp).toBe('number')
    m.disconnect()
  })

  it('a hidden page says it is hidden, at once and with every heartbeat after', async () => {
    const { m, ws } = await connected()
    state = 'hidden'
    document.dispatchEvent(new Event('visibilitychange'))
    expect(pings(ws)).toEqual([expect.objectContaining({ visible: false })])     // at once, not at the next beat
    await vi.advanceTimersByTimeAsync(30000)
    expect(pings(ws).map((p) => p.visible)).toEqual([false, false])
    state = 'visible'
    document.dispatchEvent(new Event('visibilitychange'))                       // shown again: present again at once
    expect(pings(ws).map((p) => p.visible)).toEqual([false, false, true])
    m.disconnect()
  })

  it('a closed socket stops listening for the page\'s visibility', async () => {
    const { m, ws } = await connected()
    m.disconnect()
    const before = ws.sent.length
    state = 'hidden'
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(60000)
    expect(ws.sent.length).toBe(before)
  })

  it('pageVisible: hidden is the only state that is not visible', () => {
    state = 'hidden'
    expect(pageVisible()).toBe(false)
    state = 'visible'
    expect(pageVisible()).toBe(true)
  })
})
