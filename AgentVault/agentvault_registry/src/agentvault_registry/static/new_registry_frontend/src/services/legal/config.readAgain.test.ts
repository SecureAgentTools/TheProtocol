/**
 * §FESUITE (2026-10-09): the legal config was read once per session, so a console booted while the registry could not
 * answer kept the failure: the legal pages showed "[provider details unavailable]" and the re-consent notice said
 * "applies from ." after the registry was back (sweeps/recovery on V0587, 39 admin pages). A read that got no answer or
 * a 5xx is read again on its own (backing off) and on the next use; a refusal is not retried. The module keeps the
 * session's state, so each test imports it fresh.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const fetchMock = vi.fn()
const answer = (status: number, body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
const CONFIG = { mode: 'theprotocol', provider: null, provider_identified: false, operator_links: null, tos_version: '2.4',
  documents_version: '2.5', effective: '2026-11-03', effective_label: '3 November 2026', published: '2026-10-03' }
const reads = () => fetchMock.mock.calls.filter(([u]) => String(u).includes('/legal/config')).length

async function fresh() {
  vi.resetModules()
  return await import('./config')
}
const settle = async () => { for (let i = 0; i < 10; i++) await Promise.resolve() }

describe('the legal config after a read that got no answer', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers() })

  it('reads again on its own until one answers (it kept the failure for the session)', async () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
      .mockImplementationOnce(() => answer(502, {}))
      .mockImplementation(() => answer(200, CONFIG))
    const m = await fresh()
    const { config, state } = m.useLegalConfig()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    expect(state.value).toBe('failed')
    await vi.advanceTimersByTimeAsync(5_000)
    await settle()
    expect(reads(), 'read again after the first step').toBe(2)
    await vi.advanceTimersByTimeAsync(10_000)
    await settle()
    expect(state.value, 'the registry answered').toBe('loaded')
    expect(config.value?.effective_label).toBe('3 November 2026')
    await vi.advanceTimersByTimeAsync(120_000)
    expect(reads(), 'an answer stops the retry').toBe(3)
  })

  it('the next use reads again after a failure (a page opened once the registry is back)', async () => {
    fetchMock.mockImplementationOnce(() => Promise.reject(new TypeError('Failed to fetch')))
      .mockImplementation(() => answer(200, CONFIG))
    const m = await fresh()
    m.useLegalConfig()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    const { state } = m.useLegalConfig()
    await vi.advanceTimersByTimeAsync(0)
    await settle()
    expect(state.value).toBe('loaded')
  })

  it('a refusal is not retried on its own', async () => {
    fetchMock.mockImplementation(() => answer(404, { detail: 'Not Found' }))
    const m = await fresh()
    const { state } = m.useLegalConfig()
    await vi.advanceTimersByTimeAsync(120_000)
    await settle()
    expect(state.value).toBe('failed')
    expect(reads()).toBe(1)
  })
})
