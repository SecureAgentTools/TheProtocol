/**
 * services/sse.ts — Server-Sent Events over fetch, so the JWT rides the Authorization header.
 *
 * §RELEASEHARDEN D2 (2026-09-14): a browser EventSource cannot send a header, which is why the admin
 * MCP tester used to put the developer JWT into `?access_token=` — and uvicorn wrote that request line,
 * token and all, into the container log on every stream open. This reader opens the same streams with
 * `fetch` and parses the SSE wire format itself, so nothing secret is in the URL and the server can
 * refuse the query form (routers/mcp_tester.py).
 *
 * The consumer gets an EventSource-shaped surface: one callback per event with its name, data and
 * `id:` (the multi-frame stream labels frames as `id: A` / `id: B`), plus open/error/close. Reconnection
 * stays the caller's decision, exactly as it was with `es.onerror`.
 */

export interface SseEvent {
  event: string
  data: string
  id: string
}

export interface SseOptions {
  headers?: Record<string, string>
  onOpen?: () => void
  onEvent: (ev: SseEvent) => void
  onError?: (err: unknown) => void
  /** The stream ended without an error (server closed it). */
  onClose?: () => void
}

export interface SseHandle {
  close: () => void
  readonly closed: boolean
}

/**
 * Incremental SSE parser: feed it decoded text chunks in arrival order and it returns the events that
 * became complete. Handles `\r\n`, `\n` and `\r` line endings, comments (`:`), multi-line `data:`
 * (joined with `\n`, the trailing newline removed, per the spec) and `id:`. A block with no `data`
 * line dispatches nothing, per the spec.
 */
export class SseParser {
  private buffer = ''
  private event = ''
  private data: string[] = []
  private id = ''
  private lastId = ''

  feed(chunk: string): SseEvent[] {
    const out: SseEvent[] = []
    this.buffer += chunk
    // normalise line endings; a lone trailing `\r` may be the first half of `\r\n`, keep it buffered
    let text = this.buffer.replace(/\r\n/g, '\n').replace(/\r(?!$)/g, '\n')
    if (text.endsWith('\r')) text = text.slice(0, -1)
    const lastNl = text.lastIndexOf('\n')
    if (lastNl < 0) { this.buffer = text; return out }
    const complete = text.slice(0, lastNl + 1)
    this.buffer = text.slice(lastNl + 1)
    // `complete` ends with the newline that closed its last line; splitting it whole would add a
    // phantom empty string, which reads as a blank line and dispatches a pending event one chunk early
    for (const line of complete.slice(0, -1).split('\n')) {
      if (line === '') {
        const ev = this.dispatch()
        if (ev) out.push(ev)
        continue
      }
      if (line.startsWith(':')) continue
      const colon = line.indexOf(':')
      const field = colon < 0 ? line : line.slice(0, colon)
      let value = colon < 0 ? '' : line.slice(colon + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      if (field === 'event') this.event = value
      else if (field === 'data') this.data.push(value)
      else if (field === 'id' && !value.includes('\u0000')) this.id = value
      // `retry` and unknown fields are ignored on purpose: reconnection is the caller's
    }
    return out
  }

  private dispatch(): SseEvent | null {
    const hadData = this.data.length > 0
    const ev: SseEvent | null = hadData
      ? { event: this.event || 'message', data: this.data.join('\n'), id: this.id }
      : null
    if (hadData) this.lastId = this.id
    this.event = ''
    this.data = []
    return ev
  }

  get lastEventId(): string { return this.lastId }
}

/** Open an SSE stream with fetch. Returns a handle whose `close()` aborts the request. */
export function openSse(url: string, opts: SseOptions): SseHandle {
  const ctrl = new AbortController()
  let closed = false
  const handle: SseHandle = {
    close: () => { if (!closed) { closed = true; ctrl.abort() } },
    get closed() { return closed },
  }
  ;(async () => {
    try {
      const resp = await fetch(url, {
        method: 'GET',
        headers: { Accept: 'text/event-stream', ...(opts.headers || {}) },
        cache: 'no-store',
        credentials: 'same-origin',
        signal: ctrl.signal,
      })
      if (!resp.ok || !resp.body) {
        throw new Error(`SSE ${resp.status} ${resp.statusText || ''}`.trim())
      }
      opts.onOpen?.()
      const reader = resp.body.getReader()
      const decoder = new TextDecoder('utf-8')
      const parser = new SseParser()
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        for (const ev of parser.feed(decoder.decode(value, { stream: true }))) {
          if (closed) return
          opts.onEvent(ev)
        }
      }
      // flush a final block that ended without a blank line
      for (const ev of parser.feed('\n\n')) { if (!closed) opts.onEvent(ev) }
      if (!closed) { closed = true; opts.onClose?.() }
    } catch (err) {
      if (closed) return // our own abort
      closed = true
      opts.onError?.(err)
    }
  })()
  return handle
}
