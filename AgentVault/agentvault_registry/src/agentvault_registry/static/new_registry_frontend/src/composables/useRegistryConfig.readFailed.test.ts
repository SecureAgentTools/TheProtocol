import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-04) — a failed registry-config read is not the registry's answer. useRegistryConfig cached a failed
 * read as `{}` and marked itself loaded for the session, so a console that booted while the API failed hid those
 * features and said "switched off" until a reload (agreed with agentvault2-81: flags stay false while unread, `config`
 * stays one reactive ref, registry_name stays absent on a failure, readOk / readFailed name the state). The module keeps
 * its state at module scope: every test imports a fresh copy. fetch is the HTTP layer here.
 */
type Mod = typeof import('./useRegistryConfig')
const fetchMock = vi.fn()
const answer = (status: number, body: unknown = {}) => Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body })
const flush = () => vi.advanceTimersByTimeAsync(0)

async function fresh(): Promise<Mod> {
  vi.resetModules()
  return import('./useRegistryConfig')
}

describe('the shared registry config tells a failed read from the answer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('a failed read is closed (every flag false, no name) but says it failed', async () => {
    const m = await fresh()
    fetchMock.mockReturnValueOnce(answer(502))
    const c = m.useRegistryConfig()
    await flush()
    expect(c.loaded.value).toBe(true)
    expect(c.readOk.value).toBe(false)
    expect(c.readFailed.value).toBe(true)
    expect(c.cockpitDeskEnabled.value).toBe(false)
    expect(c.config.value.registry_name).toBeUndefined()
  })

  it('a caller inside the gap does not read again; after it a caller does, and the answer lands in place', async () => {
    const m = await fresh()
    fetchMock.mockReturnValueOnce(answer(502))
    const first = m.useRegistryConfig()
    await flush()
    vi.advanceTimersByTime(m.RETRY_GAP_MS - 500)
    m.useRegistryConfig()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    vi.advanceTimersByTime(600)
    fetchMock.mockReturnValueOnce(answer(200, { registry_name: 'Sandbox Beta', cockpit_desk_enabled: true }))
    m.useRegistryConfig()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    // the computeds a view took BEFORE the second read follow it: one reactive config
    expect(first.readOk.value).toBe(true)
    expect(first.readFailed.value).toBe(false)
    expect(first.cockpitDeskEnabled.value).toBe(true)
    expect(first.config.value.registry_name).toBe('Sandbox Beta')
  })

  it('with nobody asking it reads again on its own, backing off, and stops once a read answers', async () => {
    const m = await fresh()
    fetchMock.mockReturnValue(answer(502))
    m.useRegistryConfig()
    await flush()
    expect(fetchMock).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(m.BACKOFF_MS[0])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    await vi.advanceTimersByTimeAsync(m.BACKOFF_MS[1] - 1)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    fetchMock.mockReturnValue(answer(200, { registry_name: 'Sandbox Beta' }))
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(m.useRegistryConfig().readOk.value).toBe(true)
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(fetchMock).toHaveBeenCalledTimes(3)
  })

  it('a 404 is an answer (a registry without the route): every field at its default, no retry', async () => {
    const m = await fresh()
    fetchMock.mockReturnValueOnce(answer(404))
    const c = m.useRegistryConfig()
    await flush()
    expect(c.readOk.value).toBe(true)
    expect(c.readFailed.value).toBe(false)
    expect(c.simulationEnabled.value).toBe(true)
    await vi.advanceTimersByTimeAsync(10 * 60_000)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it("a person's Try again reads now, whatever the gap; a re-read that fails keeps the answer it had", async () => {
    const m = await fresh()
    fetchMock.mockReturnValueOnce(answer(502))
    const c = m.useRegistryConfig()
    await flush()
    fetchMock.mockReturnValueOnce(answer(200, { registry_name: 'Sandbox Beta', fx_enabled: true }))
    await c.reload()
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(c.readOk.value).toBe(true)
    fetchMock.mockReturnValueOnce(answer(502))
    await c.reload()
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(c.readOk.value).toBe(true)
    expect(c.config.value.registry_name).toBe('Sandbox Beta')
  })

  it('a module that cannot watch a ref hears every read that answered, and no failed one', async () => {
    const m = await fresh()
    const heard: string[] = []
    m.onRegistryConfigRead((c) => heard.push(c.registry_name || '(none)'))
    fetchMock.mockReturnValueOnce(answer(502))
    await m.loadRegistryConfig()
    expect(heard).toEqual([])
    fetchMock.mockReturnValueOnce(answer(200, { registry_name: 'Sandbox Beta' }))
    await m.loadRegistryConfig(true)
    expect(heard).toEqual(['Sandbox Beta'])
    m.onRegistryConfigRead((c) => heard.push(`late ${c.registry_name}`))
    expect(heard).toEqual(['Sandbox Beta', 'late Sandbox Beta'])
  })
})
