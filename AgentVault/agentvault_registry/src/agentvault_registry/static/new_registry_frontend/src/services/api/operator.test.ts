import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('./client', () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }))

import { getMyLifecycle } from './operator'

/**
 * §FESUITE (2026-10-03): /operators/me/lifecycle answers 404 for a developer who is not an operator, by design
 * (operator_lifecycle.py), and the operator portal reads that as "not an operator yet" and shows the apply path. The
 * request names the 404 as expected, so the client shows no global "Not Found" toast over a page that is working.
 */
function refused(status: number) {
  return Object.assign(new Error(`HTTP ${status}`), { response: { status, data: { detail: 'x' } } })
}

describe('getMyLifecycle', () => {
  beforeEach(() => get.mockReset())

  it('names the 404 as an expected answer and reads it as "not an operator"', async () => {
    get.mockRejectedValueOnce(refused(404))
    expect(await getMyLifecycle()).toBeNull()
    expect(get.mock.calls[0][0]).toBe('/operators/me/lifecycle')
    expect(get.mock.calls[0][1]?.expectedStatuses).toEqual([404])
  })

  it('control: any other failure still throws', async () => {
    get.mockRejectedValueOnce(refused(500))
    await expect(getMyLifecycle()).rejects.toThrow('HTTP 500')
  })
})
