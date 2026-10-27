import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (the failing-reads census, 2026-10-04) — the disputes service answered [] (and zero stats) for EVERY failure,
 * so the store could not tell a failed read from an empty list: the page said "No disputes filed yet" and drew 0s with
 * every read failed. The store test (stores/readFailed.test.ts) mocks this service and passed over that: a fixture
 * built on the assumption it tests. This one mocks the HTTP layer instead, where the failure actually arrives.
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { get: http.get } }))

import { disputesApi } from './disputes'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the disputes service tells a failed read from "none"', () => {
  beforeEach(() => http.get.mockReset())

  it('a 5xx or a read with no answer rejects; it is never an empty list', async () => {
    http.get.mockRejectedValueOnce(answered(502))
    await expect(disputesApi.getDisputes()).rejects.toThrow('502')
    http.get.mockRejectedValueOnce(new Error('Network Error'))
    await expect(disputesApi.getDisputes()).rejects.toThrow('Network Error')
  })

  it('a 404 is the server\'s own "none"', async () => {
    http.get.mockRejectedValueOnce(answered(404))
    await expect(disputesApi.getDisputes()).resolves.toEqual([])
  })

  it('the stats come from a read that answered, and a failed one rejects instead of drawing zeros', async () => {
    http.get.mockRejectedValueOnce(answered(502))
    await expect(disputesApi.getStats()).rejects.toThrow('502')
    http.get.mockResolvedValueOnce({ data: [] })
    await expect(disputesApi.getStats()).resolves.toMatchObject({ total_disputes: 0 })
  })
})
