import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { defineComponent, h as hh } from 'vue'
import { mount, flushPromises } from '@vue/test-utils'
import { connectedToastWanted, hashPath, isChatPath } from './liveToast'

/**
 * V0653 (ak) (order gwo_8c69cc0fd1f3033a35f47969; the design's defect 14): the socket's "Connected" toast does not show
 * on a chat route, where the thread's live mark says it and the toast covered a phone's chat header (session-lead, the
 * sessions' room seq 685). BASE (V0652): the toast showed on every route.
 */
describe('which routes are the chat', () => {
  it("the console's OurChat, Pocket's and Pocket's permanent alias, list and thread", () => {
    for (const p of ['/ourchat', '/ourchat/room1', '/pocket/ourchat', '/pocket/ourchat/room1?approval=apr_1',
      '/pocket/ourstate', '/pocket/ourstate/room1']) expect(isChatPath(p)).toBe(true)
  })

  it('no other page, not even one whose name starts the same', () => {
    for (const p of ['/', '/dashboard', '/pocket', '/pocket/notifications', '/ourchatter', '/settings?tab=notifications',
      '/pocket/ourchats', '']) expect(isChatPath(p)).toBe(false)
  })

  it('reads the hash the console routes by', () => {
    expect(hashPath('#/ourchat/room1')).toBe('/ourchat/room1')
    expect(hashPath('')).toBe('/')
    expect(connectedToastWanted('#/ourchat/room1')).toBe(false)
    expect(connectedToastWanted('#/pocket/ourchat')).toBe(false)
    expect(connectedToastWanted('#/dashboard')).toBe(true)
    expect(connectedToastWanted('')).toBe(true)
  })
})

/* the composable itself, on a fake socket: the toast is raised on 'connected' unless the page is a chat route */
const t = vi.hoisted(() => ({ handlers: {} as Record<string, (...a: any[]) => void>, notify: vi.fn() }))
vi.mock('@/services/websocket', () => ({
  createWebSocketManager: () => ({
    on: (e: string, cb: (...a: any[]) => void) => { t.handlers[e] = cb },
    off: vi.fn(), connect: vi.fn().mockResolvedValue(undefined), disconnect: vi.fn(), send: vi.fn(), isConnected: false,
  }),
}))
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ token: 'dev-tok' }) }))
vi.mock('@/stores/ui', () => ({ useUIStore: () => ({ showNotification: t.notify }) }))
vi.mock('@/services/auth', () => ({ authService: { refreshAccessToken: vi.fn() } }))
vi.mock('@/services/accessToken', () => ({ readAccessToken: () => 'dev-tok' }))

import { useWebSocket } from '@/composables/useWebSocket'

async function connectOn(hash: string) {
  window.location.hash = hash
  let api: any = null
  const C = defineComponent({ setup() { api = useWebSocket({ autoConnect: false }); return () => hh('div') } })
  const w = mount(C)
  await api.connect()
  await flushPromises()
  t.handlers.connected?.()
  w.unmount()
}

describe("the socket's Connected toast", () => {
  beforeEach(() => { t.handlers = {}; t.notify.mockReset() })
  afterEach(() => { window.location.hash = '' })

  it('stays off on a chat thread', async () => {
    await connectOn('#/ourchat/room1')
    expect(t.notify).not.toHaveBeenCalled()
  })

  it('stays off on Pocket\'s chat list', async () => {
    await connectOn('#/pocket/ourchat')
    expect(t.notify).not.toHaveBeenCalled()
  })

  it('still shows on every other page', async () => {
    await connectOn('#/dashboard')
    expect(t.notify).toHaveBeenCalledTimes(1)
    expect(t.notify.mock.calls[0][0]).toMatchObject({ type: 'success', title: 'Connected' })
  })
})
