/**
 * V0664 (his report, room seq 4032, order gwo_a29c2690f3f0f098eb0134c4): the bell's Mentions group can be cleared. "Mark all read" moves the
 * read mark of every room that holds a mention to that room's newest mention shown (the thread's own read route, one call per room), then reads
 * the group again, and goes on while the registry still has more (the group shows 20 at a time), at most six rounds.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

vi.mock('@/services/auth', () => ({ authService: { getAccessToken: () => 'tok' } }))
import { useNotificationStore } from './notifications'

const fetchMock = vi.fn()
const m = (id: string, room: string, seq: number) => ({ id, conversation_id: room, seq, kind: 'org', title: 'Sessions', sender: 'Mira', preview: 'hi @Commander', created_at: null })
const json = (body: any, status = 200) => new Response(JSON.stringify(body), { status })

describe('markMentionsRead', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
    vi.spyOn(console, 'warn').mockImplementation(() => {})
  })
  afterEach(() => { vi.unstubAllGlobals() })

  it('marks each room read at its newest mention, once per room, then reads the group again', async () => {
    const s = useNotificationStore()
    s.mentionItems = [m('a', 'r1', 3), m('b', 'r1', 9), m('c', 'r2', 4)] as any
    fetchMock.mockImplementation((url: string) => (String(url).includes('/chat/mentions') ? Promise.resolve(json({ available: true, mentions: [], total: 0 })) : Promise.resolve(json({ ok: true }))))
    await s.markMentionsRead()
    const reads = fetchMock.mock.calls.filter(([u]) => String(u).includes('/read')).map(([u, o]) => `${o.method} ${u} ${o.body}`).sort()
    expect(reads).toEqual(['POST /api/v1/chat/conversations/r1/read {"seq":9}', 'POST /api/v1/chat/conversations/r2/read {"seq":4}'])
    expect(s.mentionItems).toEqual([])
    expect(s.mentionTotal).toBe(0)
    expect(s.mentionsMarkFailed).toBe(false)
  })

  it('goes on while the registry still has mentions (it shows 20 at a time), and stops at six rounds', async () => {
    const s = useNotificationStore()
    s.mentionItems = [m('a', 'r1', 5)] as any
    let page = 0
    fetchMock.mockImplementation((url: string) => {
      if (String(url).includes('/chat/mentions')) { page++; return Promise.resolve(json({ available: true, mentions: page < 3 ? [m('n' + page, 'r' + (page + 1), 7)] : [], total: 0 })) }
      return Promise.resolve(json({ ok: true }))
    })
    await s.markMentionsRead()
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/read'))).toHaveLength(3)      // r1, r2, r3
    expect(s.mentionItems).toEqual([])
    // a registry that never empties does not loop for ever
    fetchMock.mockReset(); s.mentionItems = [m('a', 'r1', 5)] as any
    fetchMock.mockImplementation((url: string) => (String(url).includes('/chat/mentions') ? Promise.resolve(json({ available: true, mentions: [m('x', 'r1', 5)], total: 1 })) : Promise.resolve(json({ ok: true }))))
    await s.markMentionsRead()
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/read'))).toHaveLength(6)
  })

  it('says so when a read mark could not be moved, keeps what the registry still holds, and can be pressed again', async () => {
    const s = useNotificationStore()
    s.mentionItems = [m('a', 'r1', 5)] as any
    fetchMock.mockImplementation((url: string) => (String(url).includes('/chat/mentions')
      ? Promise.resolve(json({ available: true, mentions: [m('a', 'r1', 5)], total: 1 })) : Promise.resolve(json({ detail: 'busy' }, 503))))
    await s.markMentionsRead()
    expect(s.mentionsMarkFailed).toBe(true)
    expect(s.mentionItems).toHaveLength(1)
    expect(s.mentionsMarking).toBe(false)
  })

  it('does nothing with no mentions, and a second press while one runs is ignored', async () => {
    const s = useNotificationStore()
    await s.markMentionsRead()
    expect(fetchMock).not.toHaveBeenCalled()
    s.mentionItems = [m('a', 'r1', 5)] as any
    let release: (r: Response) => void = () => {}
    fetchMock.mockImplementation((url: string) => (String(url).includes('/chat/mentions') ? Promise.resolve(json({ available: true, mentions: [], total: 0 })) : new Promise<Response>((r) => { release = r })))
    const first = s.markMentionsRead()
    await Promise.resolve()
    void s.markMentionsRead()
    release(json({ ok: true })); await first
    expect(fetchMock.mock.calls.filter(([u]) => String(u).includes('/read'))).toHaveLength(1)
  })
})
