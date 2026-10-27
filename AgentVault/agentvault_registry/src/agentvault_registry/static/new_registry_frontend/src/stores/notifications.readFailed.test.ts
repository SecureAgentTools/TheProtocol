/**
 * §FESUITE (2026-10-05): the bell said "All clear." when its reads failed (a 502 answered nothing; a network error was
 * only logged). The store says which half failed now; a feed that is off or absent (404) is an answer, not a failure.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => 'tok' } }))

import { useNotificationStore } from './notifications'

function serve(unread: () => Response, feed: () => Response) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    if (url.startsWith('/api/v1/notifications/feed?')) return feed()
    if (url === '/api/v1/notifications/unread') return unread()
    return new Response(JSON.stringify({ ok: true }))
  }))
}
const badGateway = () => new Response('<html>502 Bad Gateway</html>', { status: 502 })

describe('notification store: a failed read is not "All clear."', () => {
  beforeEach(() => { setActivePinia(createPinia()); localStorage.clear() })
  afterEach(() => { vi.unstubAllGlobals() })

  it('a 502 on both halves is two failed reads, and no list changes', async () => {
    serve(badGateway, badGateway)
    const s = useNotificationStore()
    await s.fetchUnread()
    await s.fetchFeed()
    expect(s.unreadFailed).toBe(true)
    expect(s.feedFailed).toBe(true)
    expect(s.items).toEqual([])
  })

  it('a network error is a failed read', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => { throw new TypeError('Failed to fetch') }))
    const s = useNotificationStore()
    await s.fetchUnread()
    await s.fetchFeed()
    expect(s.unreadFailed).toBe(true)
    expect(s.feedFailed).toBe(true)
  })

  it('an absent feed (404) is an answer, and answers clear the flags', async () => {
    serve(() => new Response('[]'), () => new Response('not here', { status: 404 }))
    const s = useNotificationStore()
    await s.fetchUnread()
    await s.fetchFeed()
    expect(s.unreadFailed).toBe(false)
    expect(s.feedFailed).toBe(false)
  })

  it('a failed refresh keeps the broadcasts that were read', async () => {
    const b = { id: 5, title: 't', message: 'm', broadcast_type: 'info', created_at: '2026-10-05T00:00:00Z' }
    serve(() => new Response(JSON.stringify([b])), () => new Response(JSON.stringify({ available: true, entries: [] })))
    const s = useNotificationStore()
    await s.fetchUnread()
    expect(s.items.map((i) => i.id)).toEqual([5])
    serve(badGateway, badGateway)
    await s.fetchUnread()
    expect(s.unreadFailed).toBe(true)
    expect(s.items.map((i) => i.id)).toEqual([5])
  })
})
