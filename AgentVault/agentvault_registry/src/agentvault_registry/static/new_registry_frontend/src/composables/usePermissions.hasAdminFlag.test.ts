import { describe, expect, it, vi } from 'vitest'

// The rule itself, without the composable's store and mainframe probe: security.require_admin_flag's mirror.
vi.mock('@/stores/auth', () => ({ useAuthStore: () => ({ user: null }) }))
vi.mock('./useMainframe', () => ({ useMainframe: () => ({ isMainframe: { value: false } }) }))

import { hasAdminFlag } from './usePermissions'

describe('hasAdminFlag', () => {
  it('refuses a missing user', () => {
    expect(hasAdminFlag(null, 'federation')).toBe(false)
    expect(hasAdminFlag(undefined, 'federation')).toBe(false)
  })

  it('lets a legacy is_admin pass every flag', () => {
    for (const a of ['treasury', 'support', 'enforcement', 'federation', 'platform'] as const) {
      expect(hasAdminFlag({ is_admin: true }, a)).toBe(true)
    }
  })

  it('reads the named admin_<area> flag and no other', () => {
    const u = { is_admin: false, admin_federation: true }
    expect(hasAdminFlag(u, 'federation')).toBe(true)
    expect(hasAdminFlag(u, 'platform')).toBe(false)
    expect(hasAdminFlag({ is_admin: false, admin_platform: true }, 'federation')).toBe(false)
  })

  it('does not take a truthy is_admin that is not true', () => {
    expect(hasAdminFlag({ is_admin: 'yes' }, 'federation')).toBe(false)
  })
})
