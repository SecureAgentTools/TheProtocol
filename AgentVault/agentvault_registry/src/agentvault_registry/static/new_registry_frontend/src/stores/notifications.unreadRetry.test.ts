/**
 * §FESUITE (2026-10-09): the unread broadcasts were read on the layout's mount, a socket reconnect or a press only, so a
 * console opened while the registry could not answer kept "BROADCASTS COULD NOT BE READ // PRESS TO TRY AGAIN" for the
 * rest of the session after the registry was back (sweeps/recovery on V0587: every member page, against a fresh load's
 * "No new broadcasts"). A read that got no answer, or a 5xx, is read again on its own, backing off, until one answers; a
 * refusal is never retried. The store, the registry answered per test through fetch.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => 'tok' } }))

import { useNotificationStore } from './notifications'

const answer = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
const fetchMock = vi.fn()
const unreadCalls = () => fetchMock.mock.calls.filter(([u]) => String(u).startsWith('/api/v1/notifications/unread')).length
/** the unread read answers what the test says next; the feed half answers an empty feed */
let next: Array<() => Promise<Response>> = []

describe('the unread broadcasts after a read that got no answer', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    localStorage.clear()
    next = []
    fetchMock.mockReset()
    fetchMock.mockImplementation((url: string) => {
      if (String(url).startsWith('/api/v1/notifications/feed')) return answer(200, { entries: [] })
      const f = next.shift()
      return f ? f() : answer(200, [])
    })
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('reads again on its own until one answers (it said "could not be read" for the rest of the session)', async () => {
    next = [() => Promise.reject(new TypeError('Failed to fetch')), () => answer(502, {}), () => answer(200, [])]
    const s = useNotificationStore()
    await s.fetchUnread()
    expect(s.unreadFailed, 'no answer: the read failed').toBe(true)
    await vi.advanceTimersByTimeAsync(5_000)
    expect(unreadCalls(), 'read again after the first step').toBe(2)
    expect(s.unreadFailed, 'a 502 (the registry restarting) is still a failure').toBe(true)
    await vi.advanceTimersByTimeAsync(10_000)
    expect(unreadCalls(), 'read again after the second step').toBe(3)
    expect(s.unreadFailed, 'the registry answered: the strip can say what it read').toBe(false)
    expect(s.lastReadAt).toBeGreaterThan(0)
    await vi.advanceTimersByTimeAsync(120_000)
    expect(unreadCalls(), 'an answer stops the retry').toBe(3)
  })

  it('never retries a refusal (it answers the same way every time)', async () => {
    next = [() => answer(401, { detail: 'Not authenticated' })]
    const s = useNotificationStore()
    await s.fetchUnread()
    expect(s.unreadFailed).toBe(true)
    await vi.advanceTimersByTimeAsync(120_000)
    expect(unreadCalls()).toBe(1)
  })

  it('a reset (sign-out) stops a pending retry', async () => {
    next = [() => Promise.reject(new TypeError('Failed to fetch'))]
    const s = useNotificationStore()
    await s.fetchUnread()
    s.$reset()
    await vi.advanceTimersByTimeAsync(120_000)
    expect(unreadCalls()).toBe(1)
  })
})
