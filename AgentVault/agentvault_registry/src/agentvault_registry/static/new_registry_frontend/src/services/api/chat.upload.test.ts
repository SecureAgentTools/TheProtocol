import { describe, it, expect, vi, afterEach } from 'vitest'
import { chatApi } from './chat'

/** V0662 (OurChat lane): the console can upload a file to a thread. BASE (f569f6a6e): `call()` stamped a JSON content type
 *  and stringified every body, and there was no upload method, so a document could not leave the composer. A multipart
 *  body must go out as the FormData it is, with NO content type of ours: the boundary lives in the browser's header. */
afterEach(() => { vi.unstubAllGlobals() })

interface Seen { url: string; init: any }
function capture(answer: any = { id: 'att_1', card: { type: 'media' } }) {
  const seen: Seen[] = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, init: any) => {
    seen.push({ url, init })
    return { ok: true, status: 201, json: async () => answer }
  }))
  return seen
}

describe('chatApi.uploadAttachment', () => {
  it('posts the file as multipart to the thread\'s attachments, with the token and no content type of its own', async () => {
    const seen = capture()
    const file = new File(['# Plan'], 'message-20261113-143055.md', { type: 'text/markdown' })
    const r = await chatApi.uploadAttachment('tok', 'conv-1', file)
    expect(seen).toHaveLength(1)
    expect(seen[0].url).toBe('/api/v1/chat/conversations/conv-1/attachments')
    expect(seen[0].init.method).toBe('POST')
    expect(seen[0].init.headers.Authorization).toBe('Bearer tok')
    expect('Content-Type' in seen[0].init.headers).toBe(false)
    expect(seen[0].init.body).toBeInstanceOf(FormData)
    const sent = seen[0].init.body.get('file') as File
    expect(sent.name).toBe('message-20261113-143055.md')
    expect(await sent.text()).toBe('# Plan')
    expect(r.id).toBe('att_1')
    expect(r.card).toEqual({ type: 'media' })
  })

  it('names the file when the caller does, whatever the blob was called', async () => {
    const seen = capture()
    await chatApi.uploadAttachment('tok', 'c', new Blob(['x'], { type: 'text/plain' }), 'notes.txt')
    expect((seen[0].init.body.get('file') as File).name).toBe('notes.txt')
  })

  it('a refusal reaches the caller with the registry\'s own words and its status', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({
      ok: false, status: 413, headers: { get: () => null },
      json: async () => ({ detail: 'files are limited to 5 MB' }),
    })))
    await expect(chatApi.uploadAttachment('tok', 'c', new Blob(['x']), 'big.md'))
      .rejects.toMatchObject({ status: 413, detail: 'files are limited to 5 MB' })
  })
})

describe('the JSON calls are unchanged', () => {
  it('a message still goes out as stringified JSON with a JSON content type', async () => {
    const seen = capture({ message: { seq: 1 } })
    await chatApi.postMessage('tok', 'conv-1', { kind: 'text', body: 'hi', client_ref: 'ref-12345678' })
    expect(seen[0].init.headers['Content-Type']).toBe('application/json')
    expect(typeof seen[0].init.body).toBe('string')
    expect(JSON.parse(seen[0].init.body)).toEqual({ kind: 'text', body: 'hi', client_ref: 'ref-12345678' })
  })

  it('a bodiless call sends no body and no content type', async () => {
    const seen = capture({ messages: [] })
    await chatApi.getMessages('tok', 'conv-1')
    expect(seen[0].init.body).toBeUndefined()
    expect('Content-Type' in seen[0].init.headers).toBe(false)
  })
})
