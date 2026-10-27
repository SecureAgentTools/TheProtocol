import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (the swallow census, 2026-10-04) — fxService.deadLetters answered [] for EVERY failure, and AdminFx drew []
 * as "No parked routes — nothing is waiting on recovery.": an all-clear on a money page with its read failed. Mocked at
 * the HTTP layer, where a failure actually arrives (a store-level mock would carry the assumption under test).
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { get: http.get } }))
vi.mock('./peer', () => ({ peerGet: vi.fn() }))

import { fxService } from './fx'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the parked-routes read tells a failed read from "none"', () => {
  beforeEach(() => http.get.mockReset())

  it('a 5xx or a read with no answer rejects; it is never an empty queue', async () => {
    http.get.mockRejectedValueOnce(answered(502))
    await expect(fxService.deadLetters('pending', 50)).rejects.toThrow('502')
    http.get.mockRejectedValueOnce(answered(500))
    await expect(fxService.deadLetters('all', 50)).rejects.toThrow('500')
    http.get.mockRejectedValueOnce(new Error('Network Error'))
    await expect(fxService.deadLetters()).rejects.toThrow('Network Error')
  })

  it('a 404 (a registry without the route) is the server\'s own "none"', async () => {
    http.get.mockRejectedValueOnce(answered(404))
    await expect(fxService.deadLetters()).resolves.toEqual([])
  })

  it('an answer is its rows, asked with the filter', async () => {
    http.get.mockResolvedValueOnce({ data: { rows: [{ id: 'r1', amount: '66.65' }] } })
    await expect(fxService.deadLetters('pending', 50)).resolves.toEqual([{ id: 'r1', amount: '66.65' }])
    expect(http.get).toHaveBeenCalledWith('/teg/fx/dead-letters', { params: { status: 'pending', limit: 50 } })
    http.get.mockResolvedValueOnce({ data: {} })
    await expect(fxService.deadLetters('all', 50)).resolves.toEqual([])
  })
})
