/**
 * V0663 (his suggestion 3): the bell marks a whole kind read. The entries leave the feed at once and the registry is told for each
 * one, with the call one entry's press makes; a failed call is logged and does not stop the rest; an empty list calls nothing.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => 'tok' } }))

import { useNotificationStore } from './notifications'

const fetchMock = vi.fn()
const entry = (id: number, category = 'chat') => ({ id, type_key: `${category}.x`, category, severity: 'info', title: 't', body: 'b', click: null, created_at: null, read: false })

describe('markFeedReadMany', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock.mockReset()
    fetchMock.mockResolvedValue(new Response('{"ok":true}', { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('drops those entries now, tells the registry for each, and leaves the others', async () => {
    const s = useNotificationStore()
    s.feed = [entry(1), entry(2), entry(3, 'money')] as any
    const done = s.markFeedReadMany([1, 2])
    expect(s.feed.map((e) => e.id)).toEqual([3])             // before the registry has answered
    await done
    const urls = fetchMock.mock.calls.map(([u, o]) => `${o.method} ${u}`).sort()
    expect(urls).toEqual(['POST /api/v1/notifications/feed/1/read', 'POST /api/v1/notifications/feed/2/read'])
  })

  it('a failed call does not stop the rest, and an empty list calls nothing', async () => {
    const s = useNotificationStore()
    s.feed = [entry(1), entry(2)] as any
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
    await s.markFeedReadMany([1, 2])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    fetchMock.mockClear()
    await s.markFeedReadMany([])
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
