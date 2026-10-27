import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

/**
 * §FESUITE (2026-10-05): a failed status read set isEnabled to false, so Settings drew "Disabled" and "Enable Two-Factor
 * Authentication" over an account whose 2FA may be on. The store says whether the status was read now: a failed first
 * read is "failed" (the panel says so), and a failed refresh keeps the status that was read.
 */
const svc = vi.hoisted(() => ({ getStatus: vi.fn() }))
vi.mock('@/services/api/twoFactorService', () => ({ twoFactorService: { getStatus: svc.getStatus } }))
vi.mock('./ui', () => ({ useUIStore: () => ({ showError: vi.fn(), showSuccess: vi.fn() }) }))
vi.mock('./auth', () => ({ useAuthStore: () => ({}) }))

import { useTwoFactorStore } from './twoFactor'

describe('the 2FA status is read, not assumed', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    svc.getStatus.mockReset()
  })

  it('a failed first read is "failed", never "disabled"', async () => {
    const s = useTwoFactorStore()
    expect(s.statusRead).toBe('idle')
    svc.getStatus.mockRejectedValueOnce(new Error('Request failed with status code 502'))
    await s.checkStatus()
    expect(s.statusRead).toBe('failed')
    svc.getStatus.mockResolvedValueOnce({ enabled: true, verified_at: null })
    await s.checkStatus()
    expect(s.statusRead).toBe('ok')
    expect(s.isEnabled).toBe(true)
  })

  it('a failed refresh keeps the status that was read', async () => {
    const s = useTwoFactorStore()
    svc.getStatus.mockResolvedValueOnce({ enabled: true, verified_at: '2026-10-01T00:00:00Z' })
    await s.checkStatus()
    svc.getStatus.mockRejectedValueOnce(new Error('Network Error'))
    await s.checkStatus()
    expect(s.statusRead).toBe('ok')
    expect(s.isEnabled).toBe(true)
    expect(s.verifiedAt).toBe('2026-10-01T00:00:00Z')
  })

  it('a sign-out forgets the read', async () => {
    const s = useTwoFactorStore()
    svc.getStatus.mockResolvedValueOnce({ enabled: false })
    await s.checkStatus()
    s.$reset()
    expect(s.statusRead).toBe('idle')
  })
})
