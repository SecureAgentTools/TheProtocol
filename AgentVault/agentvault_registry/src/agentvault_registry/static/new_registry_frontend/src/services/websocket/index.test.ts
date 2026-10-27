// @vitest-environment node
/**
 * services/websocket/index.test.ts — §RELEASEHARDEN D2/D3 (2026-09-14).
 *
 * D3, the defect that logged him out twice: the manager opened every reconnect with the URL built at page
 * load, token inside; after the access token's 90 minutes a registry restart reconnected with an expired
 * token, got 1008, and DashboardLayout logged the session out with no 401 anywhere. The tests below drive
 * a fake WebSocket through exactly that sequence: the token changes between connects, the reconnect must
 * carry the CURRENT one; a 1008 asks for ONE refresh and reconnects with the fresh token; only a failed
 * refresh (or a second refusal) ends in `auth_expired`.
 * D2: the token is offered as the subprotocol pair, never in the URL.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { WebSocketManager, WS_SUBPROTOCOL, WS_BEARER_PREFIX, wsProtocolsFor } from './index'

class FakeWS {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3
  static instances: FakeWS[] = []
  readyState = 0
  onopen: null | (() => void) = null
  onmessage: null | ((e: any) => void) = null
  onerror: null | ((e: any) => void) = null
  onclose: null | ((e: { code: number; reason: string }) => void) = null
  constructor(public url: string, public protocols?: string[]) { FakeWS.instances.push(this) }
  send() {}
  close() { this.readyState = 3 }
  open() { this.readyState = 1; this.onopen?.() }
  serverClose(code: number, reason = '') { this.readyState = 3; this.onclose?.({ code, reason }) }
}

const URL_ = 'wss://frame.example/api/v1/ws'

beforeEach(() => {
  FakeWS.instances = []
  ;(globalThis as any).WebSocket = FakeWS
  vi.useFakeTimers()
})
afterEach(() => { vi.useRealTimers() })

const flush = async () => { await vi.advanceTimersByTimeAsync(0) }

describe('the token transport (D2)', () => {
  it('wsProtocolsFor offers the version and the bearer, or nothing for a public socket', () => {
    expect(wsProtocolsFor('t')).toEqual([WS_SUBPROTOCOL, WS_BEARER_PREFIX + 't'])
    expect(wsProtocolsFor(null)).toBeUndefined()
    expect(wsProtocolsFor('')).toBeUndefined()
  })

  it('offers the bearer subprotocol from getToken and leaves the URL clean', () => {
    const m = new WebSocketManager({ url: URL_, getToken: () => 'tok-1' })
    m.connect().catch(() => {})
    const ws = FakeWS.instances[0]
    expect(ws.url).toBe(URL_)
    expect(ws.url).not.toContain('token')
    expect(ws.protocols).toEqual([WS_SUBPROTOCOL, WS_BEARER_PREFIX + 'tok-1'])
  })

  it('a socket without getToken offers no subprotocol', () => {
    const m = new WebSocketManager({ url: URL_ })
    m.connect().catch(() => {})
    expect(FakeWS.instances[0].protocols).toBeUndefined()
  })
})

describe('the reconnect carries the CURRENT token (D3)', () => {
  it('reads getToken again on every reconnect, not the value captured at construction', async () => {
    let token = 'old-token'
    const m = new WebSocketManager({ url: URL_, getToken: () => token, reconnectInterval: 10 })
    m.connect().catch(() => {})
    const first = FakeWS.instances[0]
    first.open()
    expect(first.protocols![1]).toBe(WS_BEARER_PREFIX + 'old-token')
    token = 'refreshed-token' // the proactive refresh at minute 85 moved the store on
    first.serverClose(1006, '') // the registry restarted
    await vi.advanceTimersByTimeAsync(10)
    expect(FakeWS.instances.length).toBe(2)
    expect(FakeWS.instances[1].protocols![1]).toBe(WS_BEARER_PREFIX + 'refreshed-token')
  })
})

describe('a refused token is refreshed once before the session is given up (D3)', () => {
  it('1008 asks refreshToken once and reconnects with the fresh token, emitting no auth_expired', async () => {
    let token = 'stale'
    const refresh = vi.fn(async () => { token = 'fresh'; return 'fresh' })
    const m = new WebSocketManager({ url: URL_, getToken: () => token, refreshToken: refresh, reconnectInterval: 10 })
    const expired: any[] = []
    m.on('auth_expired', (d) => expired.push(d))
    m.connect().catch(() => {})
    const first = FakeWS.instances[0]
    first.open()
    first.serverClose(1008, 'invalid_token')
    await flush()
    expect(refresh).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(10)
    expect(FakeWS.instances.length).toBe(2)
    expect(FakeWS.instances[1].protocols![1]).toBe(WS_BEARER_PREFIX + 'fresh')
    expect(expired).toEqual([])
    // the session goes on: a later network drop still reconnects
    FakeWS.instances[1].open()
    FakeWS.instances[1].serverClose(1006, '')
    await vi.advanceTimersByTimeAsync(10)
    expect(FakeWS.instances.length).toBe(3)
  })

  it('1008 with no fresh token emits auth_expired and stops reconnecting', async () => {
    const refresh = vi.fn(async () => null)
    const m = new WebSocketManager({ url: URL_, getToken: () => 'stale', refreshToken: refresh, reconnectInterval: 10 })
    const expired: any[] = []
    m.on('auth_expired', (d) => expired.push(d))
    m.connect().catch(() => {})
    FakeWS.instances[0].open()
    FakeWS.instances[0].serverClose(1008, 'invalid_token')
    await flush()
    await vi.advanceTimersByTimeAsync(50)
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(expired).toEqual([{ code: 1008, reason: 'invalid_token' }])
    expect(FakeWS.instances.length).toBe(1)
  })

  it('a refresh that throws is the same as none', async () => {
    const refresh = vi.fn(async () => { throw new Error('refresh 401') })
    const m = new WebSocketManager({ url: URL_, getToken: () => 'stale', refreshToken: refresh, reconnectInterval: 10 })
    const expired: any[] = []
    m.on('auth_expired', (d) => expired.push(d))
    m.connect().catch(() => {})
    FakeWS.instances[0].open()
    FakeWS.instances[0].serverClose(1008, 'invalid_token')
    await flush()
    await vi.advanceTimersByTimeAsync(50)
    expect(expired.length).toBe(1)
    expect(FakeWS.instances.length).toBe(1)
  })

  it('a second 1008 before the refreshed socket opens gives up: one refresh per refused connection', async () => {
    const refresh = vi.fn(async () => 'fresh-but-refused')
    const m = new WebSocketManager({ url: URL_, getToken: () => 'x', refreshToken: refresh, reconnectInterval: 10 })
    const expired: any[] = []
    m.on('auth_expired', (d) => expired.push(d))
    m.connect().catch(() => {})
    FakeWS.instances[0].open()
    FakeWS.instances[0].serverClose(1008, 'invalid_token')
    await flush()
    await vi.advanceTimersByTimeAsync(10)
    expect(FakeWS.instances.length).toBe(2)
    FakeWS.instances[1].serverClose(1008, 'invalid_token') // refused again, never opened
    await flush()
    await vi.advanceTimersByTimeAsync(50)
    expect(refresh).toHaveBeenCalledTimes(1)
    expect(expired.length).toBe(1)
    expect(FakeWS.instances.length).toBe(2)
  })

  it('without a refreshToken hook, 1008 is auth_expired at once (the old contract)', async () => {
    const m = new WebSocketManager({ url: URL_, getToken: () => 'x', reconnectInterval: 10 })
    const expired: any[] = []
    m.on('auth_expired', (d) => expired.push(d))
    m.connect().catch(() => {})
    FakeWS.instances[0].open()
    FakeWS.instances[0].serverClose(1008, 'unauthorized')
    await vi.advanceTimersByTimeAsync(50)
    expect(expired).toEqual([{ code: 1008, reason: 'unauthorized' }])
    expect(FakeWS.instances.length).toBe(1)
  })
})
