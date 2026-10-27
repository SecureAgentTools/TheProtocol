import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-04) — AdminFx and ForexDesk tell "unread" from "off" by this contract: publicRate and publicRates
 * answer null ONLY when their read failed; a frame without FX answers an object with available: false. Both desks said
 * "FX DISABLED" / "corridor off here" / "This frame settles in a single currency." with every read failed. If these ever
 * answer null for a frame that is off, the desks would show "could not be read" where "off" is the truth: change both.
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { get: http.get } }))
vi.mock('./peer', () => ({ peerGet: vi.fn() }))

import { fxService } from './fx'

const answered = (status: number) => Object.assign(new Error(`Request failed with status code ${status}`), { response: { status } })

describe('the public FX rate reads: null is a failed read, never "off"', () => {
  beforeEach(() => http.get.mockReset())

  it('a frame without FX is an answer (available: false), not null', async () => {
    http.get.mockResolvedValueOnce({ data: { available: false } })
    await expect(fxService.publicRate()).resolves.toEqual({ available: false })
    http.get.mockResolvedValueOnce({ data: { available: false, pairs: [] } })
    await expect(fxService.publicRates()).resolves.toEqual({ available: false, pairs: [] })
  })

  it('a failed read is null', async () => {
    http.get.mockRejectedValueOnce(answered(502))
    await expect(fxService.publicRate()).resolves.toBeNull()
    http.get.mockRejectedValueOnce(new Error('Network Error'))
    await expect(fxService.publicRates()).resolves.toBeNull()
  })
})
