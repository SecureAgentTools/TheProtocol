/**
 * usePermissions — sub-flag-aware admin gating (2026-05-08).
 *
 * Backend ships 5 admin sub-flags via /developers/me (DeveloperRead schema):
 *   admin_treasury, admin_support, admin_enforcement, admin_federation, admin_platform
 * `is_admin === true` is a super-flag that passes every check.
 *
 * Frontend used to only check `is_admin`. This composable surfaces the
 * sub-flags so sidebar items, route gates, and view-local checks can be
 * precise per-area.
 *
 * Usage:
 *   const { canTreasury, canSupport, can, isAdmin } = usePermissions()
 *   if (canTreasury.value) { ... }
 *   if (can('enforcement')) { ... }
 *
 * Backwards compat:
 *   - Existing `auth.isAdmin` checks still work; this composable adds new
 *     checks without changing the legacy paths.
 *   - For users with `is_admin=true`, every canX / sub-flag computed returns
 *     true. Commander operators see no behaviour change.
 *   - Server enforces all permissions independently — these computeds are
 *     for UX/visibility only (don't show buttons that would 403).
 *
 * If user data is missing (anonymous) — every check returns false.
 */

import { computed, type ComputedRef } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useMainframe } from './useMainframe'

export type AdminAction =
  | 'treasury'
  | 'support'
  | 'enforcement'
  | 'federation'
  | 'platform'

/** The rule every check below uses, mirroring security.require_admin_flag: a legacy `is_admin` passes every flag,
 *  otherwise the named `admin_<area>` flag decides. Pure, so a component on a public page can ask it without the
 *  composable's mainframe probe (the registry card modal, §TRUSTWIRE's trust row). */
export function hasAdminFlag(user: unknown, action: AdminAction): boolean {
  const u = user as Record<string, unknown> | null | undefined
  if (!u) return false
  if (u.is_admin === true) return true
  return Boolean(u[`admin_${action}`])
}

export interface UsePermissionsReturn {
  /** True when the developer record has `is_admin: true` (super-flag). */
  isAdmin: ComputedRef<boolean>
  /** Per-area sub-flag computeds. Each is true when `is_admin` OR the
   *  matching `admin_<area>` flag is set on the user. */
  canTreasury: ComputedRef<boolean>
  canSupport: ComputedRef<boolean>
  canEnforcement: ComputedRef<boolean>
  canFederation: ComputedRef<boolean>
  canPlatform: ComputedRef<boolean>
  /** True when the user has ANY admin sub-flag (or is_admin). Useful for
   *  showing the entire Administration section header in the sidebar. */
  hasAnyAdminFlag: ComputedRef<boolean>
  /** Generic helper: `can('treasury')` ⇔ `canTreasury.value`. Useful for
   *  data-driven nav items where the action is a string. */
  can: (action: AdminAction) => boolean

  /** §pass66 — true iff this frontend is running on a sovereign mainframe.
   *  Mirrors backend `core.mainframe_gate.is_mainframe()`. Read from the
   *  local registry card (/.well-known/registry-card.json identity.tier). */
  isMainframe: ComputedRef<boolean>
  /** §pass66 — mainframe-only feature gates. Each is `isMainframe.value`.
   *  ADDING a new gate is ONE LINE in this composable + ONE LINE in the
   *  consumer view. */
  canMintAvt: ComputedRef<boolean>
  canManageFrames: ComputedRef<boolean>
  canProvisionOperators: ComputedRef<boolean>
  canIssueLicenses: ComputedRef<boolean>
}

export function usePermissions(): UsePermissionsReturn {
  const auth = useAuthStore()

  const flags = (action: AdminAction): boolean => hasAdminFlag(auth.user, action)

  const isAdmin       = computed(() => Boolean((auth.user as unknown as Record<string, unknown> | null)?.is_admin))
  const canTreasury    = computed(() => flags('treasury'))
  const canSupport     = computed(() => flags('support'))
  const canEnforcement = computed(() => flags('enforcement'))
  const canFederation  = computed(() => flags('federation'))
  const canPlatform    = computed(() => flags('platform'))
  const hasAnyAdminFlag = computed(() =>
    isAdmin.value ||
    canTreasury.value ||
    canSupport.value ||
    canEnforcement.value ||
    canFederation.value ||
    canPlatform.value,
  )

  function can(action: AdminAction): boolean {
    return flags(action)
  }

  // §pass66 — mainframe-only gates. All derive from the local registry's
  // `identity.tier`. To add a new gate: 1 line below + 1 line in the consumer.
  const { isMainframe } = useMainframe()
  const canMintAvt            = isMainframe
  const canManageFrames       = isMainframe
  const canProvisionOperators = isMainframe
  const canIssueLicenses      = isMainframe

  return {
    isAdmin,
    canTreasury,
    canSupport,
    canEnforcement,
    canFederation,
    canPlatform,
    hasAnyAdminFlag,
    can,
    isMainframe,
    canMintAvt,
    canManageFrames,
    canProvisionOperators,
    canIssueLicenses,
  }
}
