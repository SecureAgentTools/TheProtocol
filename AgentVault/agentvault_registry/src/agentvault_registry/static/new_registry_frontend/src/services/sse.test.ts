// @vitest-environment node
/**
 * services/sse.test.ts — §RELEASEHARDEN D2 (2026-09-14): the fetch-based SSE reader.
 *
 * The parser is pinned against the wire format the registry's streams emit (`event:` + `data:` +
 * `id:` blocks, comments, CRLF, chunks cut mid-line); the reader is pinned on the one property this
 * change exists for — the JWT goes out as an Authorization HEADER and never in the URL — plus its
 * open/error/close contract.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import { SseParser, openSse } from './sse'

describe('SseParser', () => {
  it('dispatches an event/data/id block on the blank line', () => {
    const p = new SseParser()
    expect(p.feed('event: log\ndata: hello\n\n')).toEqual([{ event: 'log', data: 'hello', id: '' }])
  })

  it('reassembles chunks cut mid-line and mid-block', () => {
    const p = new SseParser()
    expect(p.feed('event: sta')).toEqual([])
    expect(p.feed('tus\ndata: comp')).toEqual([])
    expect(p.feed('leted\n\nevent: done\ndata: ok\n')).toEqual([{ event: 'status', data: 'completed', id: '' }])
    expect(p.feed('\n')).toEqual([{ event: 'done', data: 'ok', id: '' }])
  })

  it('joins multi-line data with a newline and defaults the event name to message', () => {
    const p = new SseParser()
    expect(p.feed('data: a\ndata: b\n\n')).toEqual([{ event: 'message', data: 'a\nb', id: '' }])
  })

  it('a block without data dispatches nothing, comments and CRLF are handled', () => {
    const p = new SseParser()
    expect(p.feed('event: x\n\n')).toEqual([])
    expect(p.feed(': keep-alive\r\nevent: e\r\ndata: 1\r\n\r\n')).toEqual([{ event: 'e', data: '1', id: '' }])
  })

  it('carries the id field, which the multi-frame stream uses as the frame label', () => {
    const p = new SseParser()
    expect(p.feed('id: B\nevent: event\ndata: {"t":1}\n\n')).toEqual([{ event: 'event', data: '{"t":1}', id: 'B' }])
    expect(p.lastEventId).toBe('B')
  })

  it('strips exactly one leading space of a value and keeps the rest', () => {
    const p = new SseParser()
    expect(p.feed('data:  two spaces\n\n')).toEqual([{ event: 'message', data: ' two spaces', id: '' }])
    expect(p.feed('data:nospace\n\n')).toEqual([{ event: 'message', data: 'nospace', id: '' }])
  })
})

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const c of chunks) controller.enqueue(enc.encode(c))
      controller.close()
    },
  })
}

describe('openSse', () => {
  afterEach(() => { vi.unstubAllGlobals() })

  it('sends the JWT as an Authorization header, never in the URL, and delivers the events', async () => {
    const seen: any[] = []
    const fetchMock = vi.fn(async (_url: string, _init: RequestInit) =>
      new Response(streamOf(['event: connected\ndata: ok\n\n', 'event: event\nid: A\ndata: {"n":1}\n\n']), { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)
    const events: any[] = []
    let opened = 0
    let closed = 0
    openSse('/api/v1/admin/mcp-tester/event-stream', {
      headers: { Authorization: 'Bearer eyJ.a.b' },
      onOpen: () => { opened++ },
      onEvent: (ev) => events.push(ev),
      onClose: () => { closed++ },
      onError: (e) => seen.push(e),
    })
    await vi.waitFor(() => expect(closed).toBe(1))
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/admin/mcp-tester/event-stream')
    expect(url).not.toContain('token')
    expect((init.headers as Record<string, string>).Authorization).toBe('Bearer eyJ.a.b')
    expect((init.headers as Record<string, string>).Accept).toBe('text/event-stream')
    expect(opened).toBe(1)
    expect(events).toEqual([
      { event: 'connected', data: 'ok', id: '' },
      { event: 'event', data: '{"n":1}', id: 'A' },
    ])
    expect(seen).toEqual([])
  })

  it('a refused stream reports onError with the status and never onOpen', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => new Response('nope', { status: 401, statusText: 'Unauthorized' })))
    const errors: any[] = []
    let opened = 0
    openSse('/x', { onOpen: () => { opened++ }, onEvent: () => {}, onError: (e) => errors.push(e) })
    await vi.waitFor(() => expect(errors.length).toBe(1))
    expect(String(errors[0])).toContain('401')
    expect(opened).toBe(0)
  })

  it('close() aborts the request without reporting an error', async () => {
    let abortSignal: AbortSignal | undefined
    vi.stubGlobal('fetch', vi.fn((_url: string, init: RequestInit) => {
      abortSignal = init.signal as AbortSignal
      return new Promise<Response>((_resolve, reject) => {
        abortSignal!.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
      })
    }))
    const errors: any[] = []
    const h = openSse('/x', { onEvent: () => {}, onError: (e) => errors.push(e), onClose: () => errors.push('closed') })
    expect(h.closed).toBe(false)
    h.close()
    expect(h.closed).toBe(true)
    expect(abortSignal?.aborted).toBe(true)
    await new Promise((r) => setTimeout(r, 5))
    expect(errors).toEqual([])
  })
})
