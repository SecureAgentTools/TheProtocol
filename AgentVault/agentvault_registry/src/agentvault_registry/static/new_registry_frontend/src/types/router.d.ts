/**
 * Vue Router meta key augmentation — RBAC §65 (2026-05-08).
 *
 * Extends `RouteMeta` so TypeScript validates the `requiresAdminFlag`
 * key against the canonical `AdminAction` union from `usePermissions`.
 *
 * Usage in route definitions:
 *   meta: {
 *     requiresAuth: true,
 *     requiresRole: 'admin',
 *     requiresAdminFlag: 'treasury',  // typed: must be one of the 5 sub-flags
 *     title: 'Treasury & Fee Audit'
 *   }
 *
 * Reading in `router.beforeEach`:
 *   if (to.meta.requiresAdminFlag) { ... }   // inferred as AdminAction|undefined
 *
 * Hard-gating semantics: `requiresRole: 'admin'` accepts any admin
 * (super-or-any-flag, post-§60 fix in stores/auth.ts:checkAuth). The new
 * `requiresAdminFlag` adds a SECOND check for the SPECIFIC sub-flag the
 * route needs — so a treasury-only admin direct-URL'ing to /admin/agents
 * is redirected to /mission-control instead of landing on a 403-toasting
 * page. See router/index.ts beforeEach for implementation.
 */
import 'vue-router'
import type { AdminAction } from '@/composables/usePermissions'

declare module 'vue-router' {
  interface RouteMeta {
    requiresAuth?: boolean
    requiresRole?: 'admin' | 'developer' | 'agent' | 'user'
    requiresAdminFlag?: AdminAction
    requiresAgent?: boolean
    requiresDeveloper?: boolean
    allowAnonymous?: boolean
    title?: string
    /** The route's component (or its layout) renders its own <main id="main-content">, so App.vue adds none */
    ownsMain?: boolean
  }
}

export {}
