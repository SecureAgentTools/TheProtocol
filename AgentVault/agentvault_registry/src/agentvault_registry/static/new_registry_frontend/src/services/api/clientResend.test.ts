/**
 * §FESUITE (2026-10-05): what the API client sends again on its own after a 5xx. A read is asked once more, 2 s later
 * (unchanged); a write never is, keyed or not: a 5xx on a write leaves its outcome unknown (the registry answers 503 when
 * its call to the TEG timed out after the TEG committed), and the second send of a transfer was a second transfer.
 * Driven through the real apiClient: its interceptors run, and an adapter answers each send in turn.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, type AxiosRequestConfig } from 'axios'

let apiClient: any, mayResendOnItsOwn: (m: string | undefined, url?: string) => boolean

beforeAll(async () => {
  const { setActivePinia, createPinia } = await import('pinia')
  setActivePinia(createPinia())
  ;({ apiClient, mayResendOnItsOwn } = await import('@/services/api/client'))
}, 30_000)

beforeEach(() => { vi.useFakeTimers() })
afterEach(() => { vi.useRealTimers() })

/** answers each send with the next status (the last one repeats); an error status is thrown as axios's adapters do */
function answering(...statuses: number[]) {
  const sends: AxiosRequestConfig[] = []
  const adapter = async (cfg: AxiosRequestConfig) => {
    const s = statuses[Math.min(sends.length, statuses.length - 1)]
    sends.push(cfg)
    const response = { data: { ok: s < 400 }, status: s, statusText: '', headers: {}, config: cfg }
    if (s >= 400) throw new AxiosError(`Request failed with status code ${s}`, 'ERR_BAD_RESPONSE', cfg as any, {}, response as any)
    return response
  }
  return { adapter, sends }
}

/** the outcome of a request once the client's own retry delay has passed: 'resolved', or the error it rejected with */
async function outcome(p: Promise<unknown>): Promise<unknown> {
  const settled = p.then(() => 'resolved', (e) => e)
  await vi.advanceTimersByTimeAsync(2_500)
  return settled
}

describe('the rule', () => {
  it('a read may be sent again on its own; a write may not', () => {
    for (const m of ['get', 'GET', 'head', 'options', undefined]) expect(mayResendOnItsOwn(m)).toBe(true)
    for (const m of ['post', 'POST', 'put', 'patch', 'delete']) expect(mayResendOnItsOwn(m)).toBe(false)
  })

  it('a POST that only reads is named one by one: the balances batch, nothing near it', () => {
    expect(mayResendOnItsOwn('post', '/developers/me/agents/balances')).toBe(true)
    expect(mayResendOnItsOwn('POST', 'https://sandbox-a.theprotocol.cloud/api/v1/developers/me/agents/balances')).toBe(true)
    expect(mayResendOnItsOwn('post', '/developers/me/agents')).toBe(false)               // creates an agent
    expect(mayResendOnItsOwn('post', '/developers/me/agents/balances-reset')).toBe(false)
    expect(mayResendOnItsOwn('put', '/developers/me/agents/balances')).toBe(false)
    expect(mayResendOnItsOwn('post', '/teg/transfer')).toBe(false)
  })
})

describe('the wiring', () => {
  it.each(['get', 'head'])('a read (%s) answered 502 is asked once more, 2 s later', async (method) => {
    const { adapter, sends } = answering(502, 200)
    expect(await outcome(apiClient.request({ url: '/x', method, adapter }))).toBe('resolved')
    expect(sends).toHaveLength(2)
  })

  it('the balances batch (a POST that only reads) answered 502 is asked once more, like any read', async () => {
    const { adapter, sends } = answering(502, 200)
    const out = await outcome(apiClient.post('/developers/me/agents/balances', { agent_dids: ['did:theprotocol:x'] }, { adapter }))
    expect(out).toBe('resolved')
    expect(sends).toHaveLength(2)
  })

  it.each(['post', 'put', 'patch', 'delete'])('a write (%s) answered 502 is sent once: its failure is reported', async (method) => {
    const { adapter, sends } = answering(502, 200)
    const out: any = await outcome(apiClient.request({ url: '/teg/transfer', method, data: { amount: '1' }, adapter }))
    expect(sends).toHaveLength(1)
    expect(out?.response?.status).toBe(502)
  })

  it('a write that carries an Idempotency-Key is not sent again on its own either', async () => {
    const { adapter, sends } = answering(503, 200)
    const out: any = await outcome(apiClient.post('/teg/transfer', { amount: '1' }, {
      adapter, headers: { 'Idempotency-Key': '6f1c2c1e-1111-4a4a-8b8b-000000000001' },
    }))
    expect(sends).toHaveLength(1)
    expect(out?.response?.status).toBe(503)
  })

  it('an error that is not a failed request reaches the caller as it was', async () => {
    const handlers = (apiClient.interceptors.response as any).handlers.filter(Boolean)
    const retry = handlers[handlers.length - 1]          // setupRetry registers last
    const boom = new Error('thrown before any request was made')
    await expect(retry.rejected(boom)).rejects.toBe(boom)
  })
})
