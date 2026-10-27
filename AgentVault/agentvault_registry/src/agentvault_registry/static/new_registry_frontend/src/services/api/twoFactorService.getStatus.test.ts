import { beforeEach, describe, expect, it, vi } from 'vitest'

/**
 * §FESUITE (2026-10-05): getStatus answered { enabled: false } for every failure, so the store's own "failed" state
 * (stores/twoFactor.statusRead.test.ts) never fired and Settings drew "Disabled" over a status it never read. Only a
 * registry without the endpoint (404) answers "no two-factor here"; every other failure reaches the store.
 */
const http = vi.hoisted(() => ({ get: vi.fn() }))
vi.mock('./client', () => ({ apiClient: { get: http.get, post: vi.fn() } }))

import { twoFactorService } from './twoFactorService'

const failure = (status?: number) => Object.assign(new Error(status ? `Request failed with status code ${status}` : 'Network Error'),
  status ? { response: { status } } : {})

describe('the 2FA status read says when it failed', () => {
  beforeEach(() => { http.get.mockReset() })

  it('answers the status the registry gave', async () => {
    http.get.mockResolvedValueOnce({ data: { enabled: true, verified_at: '2026-10-01T00:00:00Z' } })
    await expect(twoFactorService.getStatus()).resolves.toEqual({ enabled: true, verified_at: '2026-10-01T00:00:00Z' })
  })

  it('a registry without the endpoint (404) has no two-factor: disabled', async () => {
    http.get.mockRejectedValueOnce(failure(404))
    await expect(twoFactorService.getStatus()).resolves.toEqual({ enabled: false })
  })

  it('a 502, a 503 or no answer at all is a failed read, never "disabled"', async () => {
    for (const e of [failure(502), failure(503), failure()]) {
      http.get.mockRejectedValueOnce(e)
      await expect(twoFactorService.getStatus()).rejects.toBe(e)
    }
  })
})
