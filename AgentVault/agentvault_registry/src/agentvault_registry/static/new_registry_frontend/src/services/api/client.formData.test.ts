/**
 * V0658 (u): a FormData body goes through the API client as multipart, built by the browser with its own boundary.
 * The client's instance default ('Content-Type: application/json') made axios write any FormData out as JSON text, a
 * file in it as {}, so PUT /organizations/{id}/logo read no file and answered "field required" (the maintainer's report,
 * sessions' room seq 2174). The other FormData callers name multipart themselves and never met it.
 *
 * Driven through the real apiClient: its request interceptor and axios's own request transform run, then either an
 * adapter records what the transport is handed, or axios's browser adapter (xhr) runs against a recording
 * XMLHttpRequest, which shows what the browser itself is asked to send.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import type { AxiosRequestConfig } from 'axios'

let apiClient: any
let organizationService: any
let bundlesApi: any
let registryCardAdminApi: any
let authApi: any

beforeAll(async () => {
  const { setActivePinia, createPinia } = await import('pinia')
  setActivePinia(createPinia())
  ;({ apiClient } = await import('@/services/api/client'))
  ;({ organizationService } = await import('@/services/api/organizationService'))
  ;({ bundlesApi } = await import('@/services/api/bundles'))
  ;({ registryCardAdminApi } = await import('@/services/api/registryCardAdmin'))
  ;({ authApi } = await import('@/services/api/auth'))
  // V0662: the registry card's uploads are admin_platform routes, and the client's admin guard (services/api/adminGuard)
  // does not send them for a session without that flag; these tests are about the body, so the session is an admin
  const { useAuthStore } = await import('@/stores/auth')
  const auth: any = useAuthStore()
  auth.token = 'dev.jwt'
  auth.user = { id: 1, is_admin: true }
}, 30_000)

const undo: Array<() => void> = []
afterEach(() => {
  while (undo.length) undo.pop()!()
  vi.unstubAllGlobals()
})

/** a PNG's signature and a few bytes after it: what the settings page hands uploadLogo from its file input */
const PNG = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52])
const logoFile = () => new File([PNG], 'logo.png', { type: 'image/png' })

/** the Content-Type a request config carries (axios's headers object, or a plain one), whatever its case */
function contentTypeOf(headers: any): unknown {
  if (!headers) return undefined
  if (typeof headers.get === 'function') return headers.get('Content-Type')
  const k = Object.keys(headers).find((h) => h.toLowerCase() === 'content-type')
  return k ? headers[k] : undefined
}

/** what the transport is handed: the instance's adapter for one test (the services pass no adapter of their own) */
function recordTransport(answer: unknown = {}): AxiosRequestConfig[] {
  const sent: AxiosRequestConfig[] = []
  const saved = apiClient.defaults.adapter
  apiClient.defaults.adapter = async (cfg: AxiosRequestConfig) => {
    sent.push(cfg)
    return { data: answer, status: 200, statusText: 'OK', headers: {}, config: cfg }
  }
  undo.push(() => { apiClient.defaults.adapter = saved })
  return sent
}

interface BrowserSend { method: string; url: string; headers: Record<string, string>; body: unknown }

/** the browser's XMLHttpRequest, recording what axios's xhr adapter asks it to send; it answers 200 with `answer` */
function recordBrowser(answer: unknown = {}): BrowserSend[] {
  const sends: BrowserSend[] = []
  class RecordingXHR {
    readyState = 0
    status = 0
    statusText = ''
    responseText = ''
    response: unknown = null
    responseURL = ''
    timeout = 0
    withCredentials = false
    responseType = ''
    onloadend: null | ((ev?: unknown) => void) = null
    onreadystatechange: null | (() => void) = null
    onabort: null | (() => void) = null
    onerror: null | ((ev?: unknown) => void) = null
    ontimeout: null | (() => void) = null
    private rec: BrowserSend = { method: '', url: '', headers: {}, body: undefined }
    open(method: string, url: string) { this.rec.method = method; this.rec.url = url }
    setRequestHeader(name: string, value: string) { this.rec.headers[name.toLowerCase()] = value }
    getAllResponseHeaders() { return 'content-type: application/json\r\n' }
    addEventListener() { /* no progress listeners are asked for */ }
    abort() { /* never cancelled here */ }
    send(body: unknown) {
      this.rec.body = body
      sends.push(this.rec)
      setTimeout(() => {
        this.readyState = 4
        this.status = 200
        this.statusText = 'OK'
        this.responseText = JSON.stringify(answer)
        this.response = this.responseText
        this.onloadend?.()
      }, 0)
    }
  }
  vi.stubGlobal('XMLHttpRequest', RecordingXHR)
  return sends
}

/** the file a sent FormData carries under `name`, as name, type and bytes */
async function entry(form: unknown, name: string): Promise<{ name: string; type: string; bytes: number[] }> {
  expect(form, 'the body is a FormData').toBeInstanceOf(FormData)
  const v = (form as FormData).get(name) as File | null
  expect(v, `the FormData carries "${name}"`).toBeInstanceOf(Blob)
  return { name: (v as File).name, type: v!.type, bytes: Array.from(new Uint8Array(await v!.arrayBuffer())) }
}

describe('organizationService.uploadLogo through the real API client', () => {
  const answer = { org_id: 'o1', logo: '/api/v1/organizations/o1/logo?v=0123456789ab', size: PNG.length, content_type: 'image/png' }

  it('hands the transport the FormData itself, with the file under "file", and no JSON content type', async () => {
    const sent = recordTransport(answer)
    expect(await organizationService.uploadLogo('o1', logoFile())).toEqual(answer)
    expect(sent).toHaveLength(1)
    expect(sent[0].method).toBe('put')
    expect(sent[0].url).toBe('/organizations/o1/logo')
    expect(sent[0].data, 'the FormData, not a JSON text of it').toBeInstanceOf(FormData)
    expect(String(contentTypeOf(sent[0].headers) || ''), 'never application/json').not.toMatch(/json/i)
    expect(await entry(sent[0].data, 'file')).toEqual({ name: 'logo.png', type: 'image/png', bytes: Array.from(PNG) })
  })

  it('asks the browser to send that FormData with no Content-Type of axios\'s own, so the browser writes multipart with its boundary', async () => {
    const sends = recordBrowser(answer)
    expect(await organizationService.uploadLogo('o1', logoFile())).toEqual(answer)
    expect(sends).toHaveLength(1)
    expect(sends[0].method).toBe('PUT')
    expect(sends[0].url).toMatch(/\/organizations\/o1\/logo$/)
    expect(sends[0].body, 'the browser is handed the FormData itself').toBeInstanceOf(FormData)
    expect(sends[0].headers['content-type'], 'no Content-Type set: the browser sets multipart/form-data; boundary=...').toBeUndefined()
    expect(await entry(sends[0].body, 'file')).toEqual({ name: 'logo.png', type: 'image/png', bytes: Array.from(PNG) })
  })
})

describe('any FormData body through the client', () => {
  it.each(['post', 'put', 'patch'])('a FormData %s that names no type goes as that FormData, never as JSON text', async (method) => {
    const sent = recordTransport()
    const form = new FormData()
    form.append('file', logoFile())
    form.append('note', 'kept')
    await apiClient.request({ url: '/x', method, data: form })
    expect(sent[0].data, 'the very FormData the caller built').toBe(form)
    expect(String(contentTypeOf(sent[0].headers) || '')).not.toMatch(/json/i)
  })

  it('a JSON body is untouched by that rule: it still goes as application/json text', async () => {
    const sent = recordTransport()
    await apiClient.put('/x', { show: false })
    expect(sent[0].data).toBe('{"show":false}')
    expect(contentTypeOf(sent[0].headers)).toBe('application/json')
  })
})

describe('the other FormData callers, which name multipart themselves (they worked before; they keep working)', () => {
  it.each([
    ['bundles: restore from an uploaded file', () => bundlesApi.restoreFromUpload(logoFile(), { mode: 'merge' }), 'POST', /\/bundles\/restore-from-upload$/],
    ['the registry card: its icon', () => registryCardAdminApi.uploadIcon(logoFile()), 'POST', /\/admin\/registry-card\/icon$/],
    ['the registry card: its avatar', () => registryCardAdminApi.uploadAvatar(logoFile()), 'POST', /\/admin\/registry-card\/avatar$/],
  ])('%s: the browser is handed its FormData, with no Content-Type of axios\'s own', async (_label, call, method, url) => {
    const sends = recordBrowser({ ok: true })
    await call()
    expect(sends).toHaveLength(1)
    expect(sends[0].method).toBe(method)
    expect(sends[0].url).toMatch(url as RegExp)
    expect(sends[0].body).toBeInstanceOf(FormData)
    expect(sends[0].headers['content-type']).toBeUndefined()
    expect(await entry(sends[0].body, 'file')).toEqual({ name: 'logo.png', type: 'image/png', bytes: Array.from(PNG) })
  })

  it('the sign-in: its form fields as a FormData, its own X-Push-Login-Local header kept', async () => {
    const sends = recordBrowser({ access_token: 'a', token_type: 'bearer' })
    await authApi.login({ email: 'person@example.test', password: 'not-a-real-one' })
    expect(sends).toHaveLength(1)
    expect(sends[0].method).toBe('POST')
    expect(sends[0].url).toMatch(/\/auth\/login$/)
    expect(sends[0].body).toBeInstanceOf(FormData)
    expect((sends[0].body as FormData).get('username')).toBe('person@example.test')
    expect(sends[0].headers['content-type']).toBeUndefined()
    expect(sends[0].headers['x-push-login-local']).toBe('0')
  })
})
