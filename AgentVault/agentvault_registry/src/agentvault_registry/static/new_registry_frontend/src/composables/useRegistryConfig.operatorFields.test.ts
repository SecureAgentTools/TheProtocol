import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-10, the operator batch) — a registry says what it runs (liability mandates, the contract template
 * library, the sandbox proxy), and a registry that says nothing (older) reads as before. registryConfigWithin is the
 * service modules' reader: it joins the one shared read and never holds a call past its bound. Fresh module per test.
 */
type Mod = typeof import('./useRegistryConfig')
const fetchMock = vi.fn()
const answer = (status: number, body: unknown = {}) => Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body })

async function fresh(): Promise<Mod> {
  vi.resetModules()
  return import('./useRegistryConfig')
}

describe('a registry says what it runs: the operator fields', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('a registry that runs none of them says so', async () => {
    const m = await fresh()
    fetchMock.mockReturnValueOnce(answer(200, { liability_mode: 'off', contract_templates_enabled: false, sandbox_proxy: [] }))
    const c = m.useRegistryConfig()
    await vi.advanceTimersByTimeAsync(0)
    expect(c.liabilityOn.value).toBe(false)
    expect(c.contractTemplatesOn.value).toBe(false)
    expect(c.sandboxProxy.value).toEqual([])
  })

  it('an older registry (no field) reads as before: on, and the proxy unknown', async () => {
    const m = await fresh()
    fetchMock.mockReturnValueOnce(answer(200, { registry_name: 'older' }))
    const c = m.useRegistryConfig()
    await vi.advanceTimersByTimeAsync(0)
    expect(c.liabilityOn.value).toBe(true)
    expect(c.contractTemplatesOn.value).toBe(true)
    expect(c.sandboxProxy.value).toBeUndefined()
  })

  it('registryConfigWithin joins the read, and never holds a caller past its bound', async () => {
    let m = await fresh()
    fetchMock.mockReturnValueOnce(answer(200, { liability_mode: 'enforce', sandbox_proxy: ['a', 'b'] }))
    await expect(m.registryConfigWithin(1000)).resolves.toMatchObject({ liability_mode: 'enforce', sandbox_proxy: ['a', 'b'] })
    m = await fresh()
    fetchMock.mockReturnValueOnce(new Promise(() => {}))   // a read that never answers
    const late = m.registryConfigWithin(1000)
    await vi.advanceTimersByTimeAsync(1000)
    await expect(late).resolves.toEqual({})
  })
})
