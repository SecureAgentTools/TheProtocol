/**
 * §FEFRAME W4 residue (V0521): a read gives up after a minute, a write keeps the long wait, and a caller's own timeout
 * always wins. Driven through the real apiClient (its request interceptor runs, then an adapter answers with the
 * timeout the request left with), so the wiring is measured, not only the rule.
 */
import { describe, it, expect, beforeAll } from 'vitest'
import type { AxiosRequestConfig } from 'axios'

let apiClient: any, effectiveTimeout: any, READ_TIMEOUT_MS: number
const echo = async (cfg: AxiosRequestConfig) => ({ data: cfg.timeout, status: 200, statusText: 'OK', headers: {}, config: cfg })

beforeAll(async () => {
  const { setActivePinia, createPinia } = await import('pinia')
  setActivePinia(createPinia())
  ;({ apiClient, effectiveTimeout, READ_TIMEOUT_MS } = await import('@/services/api/client'))
}, 30_000)

describe('the API client timeout', () => {
  it('the rule: reads a minute, writes the long default, a caller\'s own value wins', () => {
    expect(READ_TIMEOUT_MS).toBe(60_000)
    expect(effectiveTimeout('get', 0)).toBe(60_000)
    expect(effectiveTimeout('HEAD', undefined)).toBe(60_000)
    expect(effectiveTimeout('post', 0)).toBe(300_000)
    expect(effectiveTimeout('delete', undefined)).toBe(300_000)
    expect(effectiveTimeout('get', 600_000)).toBe(600_000)
    expect(effectiveTimeout('post', 15_000)).toBe(15_000)
  })

  it('the wiring: what a request leaves the interceptor with', async () => {
    expect((await apiClient.get('/x', { adapter: echo })).data).toBe(60_000)
    expect((await apiClient.post('/x', {}, { adapter: echo })).data).toBe(300_000)
    expect((await apiClient.get('/x', { adapter: echo, timeout: 15_000 })).data).toBe(15_000)
    expect((await apiClient.put('/x', {}, { adapter: echo, timeout: 95_000 })).data).toBe(95_000)
  })
})
