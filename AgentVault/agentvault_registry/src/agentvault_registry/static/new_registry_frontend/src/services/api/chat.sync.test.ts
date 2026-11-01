import { describe, it, expect, vi, afterEach } from 'vitest'
import { chatApi } from './chat'

/** V0652 (ag): the long-poll's own call. The object held two `sync` methods (the catch-up's, with a cursor and a wait,
 *  and an older one taking a since string), and in an object literal the later one wins: the long-poll's options went
 *  out as `?since=[object Object]`, so a thread with its socket down never caught up. One method now, and the URL it
 *  builds is read here. BASE (b8056a117): the older method answers, and the URL carries the object. */
afterEach(() => { vi.unstubAllGlobals() })
function capture() {
  const urls: string[] = []
  vi.stubGlobal('fetch', vi.fn(async (u: string) => { urls.push(u); return { ok: true, status: 200, json: async () => ({ messages: [] }) } }))
  return urls
}

describe('chatApi.sync', () => {
  it('a cursor and a wait go out as they are, the wait bounded at 25 s', async () => {
    const urls = capture()
    await chatApi.sync('tok', { cursor: 'c-41', wait: 25 })
    await chatApi.sync('tok', { since: '2026-11-01T00:00:00Z', wait: 99 })
    expect(urls).toEqual(['/api/v1/chat/sync?cursor=c-41&wait=25', '/api/v1/chat/sync?since=2026-11-01T00%3A00%3A00Z&wait=25'])
  })
  it('the older shape (a since string) still works', async () => {
    const urls = capture()
    await chatApi.sync('tok', '2026-11-01T00:00:00Z')
    await chatApi.sync('tok')
    expect(urls).toEqual(['/api/v1/chat/sync?since=2026-11-01T00%3A00%3A00Z', '/api/v1/chat/sync'])
  })
})
