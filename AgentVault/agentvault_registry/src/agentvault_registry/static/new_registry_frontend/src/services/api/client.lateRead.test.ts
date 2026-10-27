/**
 * §FESUITE (2026-10-09; agentvault2-b2 named it 2026-10-05): a read whose page is gone does not speak on the next page.
 * The API client raises the global error toast ("Server Error", "Connection Error") for any failed call, so a read a
 * page started and the person left before it failed put its toast over a page that had asked nothing. The page that
 * asked is the one whose notices say its read failed; a write always reports, wherever the person is now. Driven through
 * the real apiClient: its interceptors run, an adapter answers, and the page changes while the call is in flight.
 */
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { AxiosError, type AxiosRequestConfig } from 'axios'

let apiClient: any
let failedOnALeftPage: (m: string | undefined, a: string | undefined, n: string) => boolean
let errorHandler: any

beforeAll(async () => {
  const { setActivePinia, createPinia } = await import('pinia')
  setActivePinia(createPinia())
  ;({ apiClient, failedOnALeftPage } = await import('@/services/api/client'))
  ;({ errorHandler } = await import('@/utils/errorHandler'))
}, 30_000)

let handled: ReturnType<typeof vi.spyOn>
beforeEach(() => {
  vi.useFakeTimers()
  window.location.hash = '#/agora'
  handled = vi.spyOn(errorHandler, 'handleError').mockImplementation(() => {})
})
afterEach(() => { handled.mockRestore(); vi.useRealTimers() })

/** answers 502 after the page moved to `movesTo` (or stays, when null) while the call was in flight */
function failingAfter(movesTo: string | null) {
  return async (cfg: AxiosRequestConfig) => {
    if (movesTo) window.location.hash = `#${movesTo}`
    const response = { data: { detail: 'bad gateway' }, status: 502, statusText: '', headers: {}, config: cfg }
    throw new AxiosError('Request failed with status code 502', 'ERR_BAD_RESPONSE', cfg as any, {}, response as any)
  }
}

async function settle(p: Promise<unknown>) {
  const done = p.then(() => 'resolved', (e) => e)
  await vi.advanceTimersByTimeAsync(2_500)   // the client asks a failed read once more, 2 s later
  return done
}

describe('the rule', () => {
  it('only a read, only when the page it was asked on is no longer the one shown', () => {
    expect(failedOnALeftPage('get', '/agora', '/api-keys')).toBe(true)
    expect(failedOnALeftPage('GET', '/agora', '/agora')).toBe(false)
    expect(failedOnALeftPage('post', '/agora', '/api-keys')).toBe(false)
    expect(failedOnALeftPage('delete', '/agora', '/api-keys')).toBe(false)
    expect(failedOnALeftPage('get', undefined, '/api-keys')).toBe(false)
    expect(failedOnALeftPage('get', '', '/api-keys')).toBe(false)
  })
})

describe('the wiring', () => {
  it('a read that fails after its page is gone raises no toast on the next page', async () => {
    const out: any = await settle(apiClient.request({ url: '/agora/listings', method: 'get', adapter: failingAfter('/api-keys') }))
    expect(out?.response?.status, 'the caller still hears the failure').toBe(502)
    expect(handled, 'a toast over a page that asked nothing').not.toHaveBeenCalled()
  })

  it('a read that fails on the page that asked still raises its toast', async () => {
    const out: any = await settle(apiClient.request({ url: '/agora/listings', method: 'get', adapter: failingAfter(null) }))
    expect(out?.response?.status).toBe(502)
    expect(handled).toHaveBeenCalled()
  })

  it('a write that fails after the person moved on still reports', async () => {
    const out: any = await settle(apiClient.request({ url: '/exchange/orders', method: 'post', data: {}, adapter: failingAfter('/api-keys') }))
    expect(out?.response?.status).toBe(502)
    expect(handled).toHaveBeenCalled()
  })

  it('the balances batch (a POST that only reads) that fails after its page is gone raises no toast', async () => {
    const out: any = await settle(apiClient.request({ url: '/developers/me/agents/balances', method: 'post',
      data: { agent_dids: ['did:theprotocol:x'] }, adapter: failingAfter('/api-keys') }))
    expect(out?.response?.status).toBe(502)
    expect(handled, 'a toast over a page that asked nothing').not.toHaveBeenCalled()
  })

  it('a query change on the same page is the same page', async () => {
    const out: any = await settle(apiClient.request({ url: '/agora/listings', method: 'get', adapter: failingAfter('/agora?tab=book') }))
    expect(out?.response?.status).toBe(502)
    expect(handled).toHaveBeenCalled()
  })
})
