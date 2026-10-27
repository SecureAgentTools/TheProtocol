import { describe, it, expect, vi, beforeEach } from 'vitest'

const get = vi.fn()
vi.mock('./api/client', () => ({ apiClient: { get: (...a: unknown[]) => get(...a) } }))

import { authApi } from './api/auth'

/**
 * Quick onboarding (2026-10-09): whether the developer has confirmed their email reaches the store.
 *
 * GET /developers/me answers `is_verified` (schemas.DeveloperRead), and the registry refuses a bootstrap token, so an
 * agent, to a developer who has not ("Only verified developers can request bootstrap tokens"). verify() maps the
 * profile field by field and dropped it, so no page could say so before the refusal. An older registry that sends no
 * such field reads as unknown (undefined), never as "unverified".
 */
beforeEach(() => { get.mockReset() })

describe('authApi.verify carries is_verified', () => {
  it('false and true arrive as the registry said them', async () => {
    get.mockResolvedValueOnce({ data: { id: 7, email: 'dev@example.test', is_admin: false, is_verified: false } })
    expect((await authApi.verify()).user.is_verified).toBe(false)
    get.mockResolvedValueOnce({ data: { id: 7, email: 'dev@example.test', is_admin: false, is_verified: true } })
    expect((await authApi.verify()).user.is_verified).toBe(true)
  })

  it('control: a profile without the field is unknown, not unverified', async () => {
    get.mockResolvedValueOnce({ data: { id: 7, email: 'dev@example.test', is_admin: false } })
    expect((await authApi.verify()).user.is_verified).toBeUndefined()
  })
})
