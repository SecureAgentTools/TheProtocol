import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-04, agentvault2-09's find) — getStakingHistory answered an empty history for EVERY failure, a false
 * "none" waiting for a reader (the store's fetchStakingHistory already sets its error and rethrows). Mocked at the HTTP
 * layer: the service is constructed with its own client.
 */
import { StakingApi } from './staking'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the staking history tells a failed read from "none"', () => {
  const get = vi.fn()
  const api = new StakingApi({ get } as any)
  beforeEach(() => get.mockReset())

  it('a 5xx or no answer rejects; it is never an empty history', async () => {
    get.mockRejectedValueOnce(answered(502))
    await expect(api.getStakingHistory()).rejects.toThrow('502')
    get.mockRejectedValueOnce(new Error('Network Error'))
    await expect(api.getStakingHistory({ page: 2, limit: 10 })).rejects.toThrow('Network Error')
  })

  it('a 404 is the server\'s own "none"; an answer is its rows, asked by page', async () => {
    get.mockRejectedValueOnce(answered(404))
    await expect(api.getStakingHistory()).resolves.toMatchObject({ history: [], total: 0 })
    get.mockResolvedValueOnce({ data: { history: [{ id: 'h1', type: 'stake', amount: '5', timestamp: 't', txHash: 'x', status: 'ok' }], total: 1 } })
    await expect(api.getStakingHistory({ page: 2, limit: 10 })).resolves.toMatchObject({ total: 1, page: 2, limit: 10 })
    expect(get).toHaveBeenLastCalledWith('/staking/history', { params: { limit: 10, offset: 10 } })
  })
})
