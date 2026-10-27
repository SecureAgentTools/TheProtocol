/**
 * §FESUITE — the desktop bell counts and lists the per-developer in-app feed (GET /notifications/feed), not only admin
 * broadcasts. Measured without a browser because the sandbox runs NOTIFY_V2_MODE=shadow, where the server writes no
 * feed entry at all (the console lifecycle names that NOT MEASURED).
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'

vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => 'tok' } }))

import { useNotificationStore } from './notifications'

const entry = (id: number, read = false) => ({
  id, type_key: 'security.2fa_changed', category: 'security', severity: 'warning',
  title: `entry ${id}`, body: 'body', click: '/ui/#/settings', created_at: '2026-10-01T15:00:00Z', read,
})

describe('notification store: the in-app feed', () => {
  let calls: Array<{ url: string; method: string }>
  beforeEach(() => {
    setActivePinia(createPinia())
    calls = []
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method || 'GET' })
      if (url.startsWith('/api/v1/notifications/feed?')) {
        return new Response(JSON.stringify({ available: true, unread_count: 2, entries: [entry(7), entry(8), entry(9, true)] }))
      }
      if (url === '/api/v1/notifications/unread') return new Response('[]')
      return new Response(JSON.stringify({ ok: true }))
    }))
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('fetches the unread feed and counts it beside the broadcasts', async () => {
    const s = useNotificationStore()
    await s.fetchFeed()
    expect(s.feed.map((e) => e.id)).toEqual([7, 8])
    expect(s.unreadCount).toBe(2)
    expect(calls[0].url).toContain('unread_only=true')
  })

  it('marks one entry read on the server and drops it from the count', async () => {
    const s = useNotificationStore()
    await s.fetchFeed()
    await s.markFeedRead(7)
    expect(s.feed.map((e) => e.id)).toEqual([8])
    expect(s.unreadCount).toBe(1)
    expect(calls.some((c) => c.url === '/api/v1/notifications/feed/7/read' && c.method === 'POST')).toBe(true)
  })

  it('clear all reads the feed too', async () => {
    const s = useNotificationStore()
    await s.fetchFeed()
    await s.markAllRead()
    expect(s.unreadCount).toBe(0)
    expect(calls.some((c) => c.url === '/api/v1/notifications/feed/read-all' && c.method === 'POST')).toBe(true)
  })

  it('a node without the feed table answers available:false and the bell counts nothing from it', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ available: false, entries: [], unread_count: 0 }))))
    const s = useNotificationStore()
    await s.fetchFeed()
    expect(s.feed).toEqual([])
    expect(s.unreadCount).toBe(0)
  })
})
